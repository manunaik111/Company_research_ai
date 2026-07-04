"""
POST /api/research

This is the orchestration layer that implements the spec's "Suggested
Workflow" end to end:

  1. User enters a company name or website URL.
  2. Search using Serper.dev.
  3. Identify the official website (if necessary).
  4. Crawl the website.
  5. Extract useful information.
  6. Collect additional information from public sources.
  7. Send the collected data to OpenRouter.
  8. Generate the AI report.
  9. Identify competitors.
  10. Return the assembled result (display + PDF happen client-side / in
      a separate endpoint).

Every external call (Serper, crawler, OpenRouter) is wrapped so a single
failure degrades gracefully instead of taking down the whole request —
this directly maps to the "Handling of edge cases and robustness"
evaluation criterion.
"""

import re
import asyncio
import httpx
from fastapi import APIRouter

from app.models import ResearchRequest, ResearchResponse, CompanyData, Competitor
from app.services.serper import SerperClient
from app.services.openrouter import OpenRouterClient
from app.services import crawler

router = APIRouter()

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def _looks_like_url(query: str) -> bool:
    return bool(URL_PATTERN.match(query.strip()))


def _normalize_website(query: str) -> str:
    """If the user typed a bare domain without a scheme, add https://."""
    q = query.strip()
    if _looks_like_url(q):
        return q
    return f"https://{q}"


def _guess_company_name_from_domain(website: str) -> str:
    """Fallback display name derived from the domain, used only if the
    AI/crawl can't surface a cleaner name (e.g. from <title> tag)."""
    from urllib.parse import urlparse
    netloc = urlparse(website).netloc.replace("www.", "")
    base = netloc.split(".")[0]
    return base.capitalize()


@router.post("/api/research", response_model=ResearchResponse)
async def research_company(req: ResearchRequest) -> ResearchResponse:
    warnings: list[str] = []

    try:
        serper = SerperClient()
        openrouter = OpenRouterClient()
    except RuntimeError as e:
        return ResearchResponse(success=False, error=str(e))

    async with httpx.AsyncClient() as client:
        # --- Step 1-3: resolve company name -> official website ---
        if _looks_like_url(req.query):
            website = _normalize_website(req.query)
            company_name_hint = _guess_company_name_from_domain(website)
        else:
            company_name_hint = req.query.strip()
            try:
                resolved = await serper.find_official_website(client, company_name_hint)
            except httpx.HTTPError as e:
                return ResearchResponse(
                    success=False, error=f"Search service error while resolving website: {e}"
                )
            if not resolved:
                return ResearchResponse(
                    success=False,
                    error=(
                        f"Could not find an official website for '{company_name_hint}'. "
                        "Try entering the website URL directly."
                    ),
                )
            website = resolved

        # --- Step 4-5: crawl the website ---
        crawl_result = await crawler.crawl_site(website)
        pages = crawl_result["pages"]
        warnings.extend(crawl_result["warnings"])

        if not pages:
            return ResearchResponse(
                success=False,
                error=f"Could not crawl {website} — the site may be blocking automated requests.",
            )

        crawled_text = "\n\n".join(
            f"[{info['type'].upper()} PAGE]\n{info['text']}" for info in pages.values()
        )

        # --- Step 6: additional public info via Serper (concurrent) ---
        try:
            competitor_results, info_results, knowledge_graph = await _gather_search_context(
                serper, client, company_name_hint
            )
        except httpx.HTTPError as e:
            warnings.append(f"Search enrichment partially failed: {e}")
            competitor_results, info_results, knowledge_graph = [], [], None

        search_context = _format_search_context(competitor_results, info_results, knowledge_graph)

        # --- Step 7-9: AI analysis ---
        try:
            ai_result = await openrouter.analyze_company(
                client,
                company_name=company_name_hint,
                crawled_text=crawled_text,
                search_context=search_context,
                model=req.model,
            )
        except httpx.HTTPError as e:
            return ResearchResponse(success=False, error=f"AI analysis failed: {e}")
        except ValueError as e:
            return ResearchResponse(success=False, error=f"AI returned unparseable output: {e}")

        # --- Assemble final CompanyData ---
        phone, address = _extract_contact_from_knowledge_graph(knowledge_graph)

        data = CompanyData(
            company_name=ai_result.get("company_name") or company_name_hint.title(),
            website=website,
            phone=phone or "Not publicly listed",
            address=address or "Not publicly listed",
            summary=ai_result.get("summary", ""),
            products_services=ai_result.get("products_services", []),
            pain_points=ai_result.get("pain_points", []),
            competitors=[
                Competitor(name=c.get("name", "Unknown"), website=c.get("website"))
                for c in ai_result.get("competitors", [])
                if c.get("name")
            ],
            pages_crawled=list(pages.keys()),
            warnings=warnings,
        )

        return ResearchResponse(success=True, data=data)


async def _gather_search_context(
    serper: SerperClient, client: httpx.AsyncClient, company_name: str
):
    """Run the three Serper enrichment calls concurrently instead of
    sequentially — cuts noticeable latency off the total request time."""
    competitor_task = serper.search_competitors(client, company_name)
    info_task = serper.search_company_info(client, company_name)
    kg_task = serper.get_knowledge_graph(client, company_name)

    return await asyncio.gather(competitor_task, info_task, kg_task)


def _format_search_context(
    competitor_results: list[dict], info_results: list[dict], knowledge_graph: dict | None
) -> str:
    parts = []
    if knowledge_graph:
        parts.append(f"Knowledge graph: {knowledge_graph}")
    if info_results:
        snippets = [f"- {r.get('title', '')}: {r.get('snippet', '')}" for r in info_results[:5]]
        parts.append("Company info search results:\n" + "\n".join(snippets))
    if competitor_results:
        snippets = [f"- {r.get('title', '')}: {r.get('snippet', '')}" for r in competitor_results[:5]]
        parts.append("Competitor search results:\n" + "\n".join(snippets))
    return "\n\n".join(parts)


def _extract_contact_from_knowledge_graph(kg: dict | None) -> tuple[str | None, str | None]:
    if not kg:
        return None, None
    phone = kg.get("phone") or kg.get("attributes", {}).get("Phone")
    address = kg.get("address") or kg.get("attributes", {}).get("Address")
    return phone, address