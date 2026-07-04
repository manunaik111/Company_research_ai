"""
POST /api/research

Orchestrates the end-to-end company research workflow.
"""

import asyncio
import re

import httpx
from fastapi import APIRouter

from app.models import (
    CompanyData,
    Competitor,
    ResearchRequest,
    ResearchResponse,
    SourceReference,
)
from app.services import crawler
from app.services.openrouter import OpenRouterClient
from app.services.serper import SerperClient

router = APIRouter()

URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def _looks_like_url(query: str) -> bool:
    return bool(URL_PATTERN.match(query.strip()))


def _normalize_website(query: str) -> str:
    q = query.strip()
    if _looks_like_url(q):
        return q
    return f"https://{q}"


def _guess_company_name_from_domain(website: str) -> str:
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
        if _looks_like_url(req.query):
            website = _normalize_website(req.query)
            company_name_hint = _guess_company_name_from_domain(website)
        else:
            company_name_hint = req.query.strip()
            try:
                resolved = await serper.find_official_website(client, company_name_hint)
            except httpx.HTTPError as e:
                return ResearchResponse(
                    success=False,
                    error=f"Search service error while resolving website: {e}",
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

        crawl_result = await crawler.crawl_site(website)
        pages = crawl_result["pages"]
        warnings.extend(crawl_result["warnings"])

        if not pages:
            return ResearchResponse(
                success=False,
                error=f"Could not crawl {website} - the site may be blocking automated requests.",
            )

        crawled_text = "\n\n".join(
            f"[{info['type'].upper()} PAGE]\n{info['text']}" for info in pages.values()
        )

        try:
            competitor_results, info_results, knowledge_graph = await _gather_search_context(
                serper, client, company_name_hint
            )
        except httpx.HTTPError as e:
            warnings.append(f"Search enrichment partially failed: {e}")
            competitor_results, info_results, knowledge_graph = [], [], None

        search_context = _format_search_context(competitor_results, info_results, knowledge_graph)
        sources = _build_sources(website, pages, info_results, competitor_results)

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

        phone, address = _extract_contact_from_knowledge_graph(knowledge_graph)

        data = CompanyData(
            company_name=ai_result.get("company_name") or company_name_hint.title(),
            website=website,
            phone=phone or "Not publicly listed",
            address=address or "Not publicly listed",
            summary=ai_result.get("summary", ""),
            industry=ai_result.get("industry", ""),
            target_customers=ai_result.get("target_customers", ""),
            business_model=ai_result.get("business_model", ""),
            key_highlights=_clean_text_list(ai_result.get("key_highlights", [])),
            products_services=_clean_text_list(ai_result.get("products_services", [])),
            pain_points=_clean_text_list(ai_result.get("pain_points", [])),
            competitors=[
                Competitor(
                    name=c.get("name", "Unknown"),
                    website=c.get("website"),
                    rationale=(c.get("rationale") or "").strip(),
                )
                for c in ai_result.get("competitors", [])
                if c.get("name")
            ],
            sources=sources,
            pages_crawled=list(pages.keys()),
            warnings=warnings,
        )

        return ResearchResponse(success=True, data=data)


async def _gather_search_context(
    serper: SerperClient, client: httpx.AsyncClient, company_name: str
):
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
        snippets = [
            f"- {r.get('title', '')}: {r.get('snippet', '')}" for r in competitor_results[:5]
        ]
        parts.append("Competitor search results:\n" + "\n".join(snippets))
    return "\n\n".join(parts)


def _extract_contact_from_knowledge_graph(kg: dict | None) -> tuple[str | None, str | None]:
    if not kg:
        return None, None
    phone = kg.get("phone") or kg.get("attributes", {}).get("Phone")
    address = kg.get("address") or kg.get("attributes", {}).get("Address")
    return phone, address


def _build_sources(
    website: str,
    pages: dict[str, dict],
    info_results: list[dict],
    competitor_results: list[dict],
) -> list[SourceReference]:
    sources: list[SourceReference] = []
    seen_urls: set[str] = set()

    def add_source(label: str, url: str | None, source_type: str, notes: str = ""):
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        sources.append(
            SourceReference(
                label=label[:90],
                url=url,
                source_type=source_type,
                notes=notes[:180],
            )
        )

    add_source("Official company website", website, "website", "Resolved official homepage")

    for url, info in list(pages.items())[:6]:
        page_type = info.get("type", "website")
        add_source(
            f"Website: {page_type.title()} page",
            url,
            "website",
            f"Crawled {page_type} page content",
        )

    for result in info_results[:4]:
        add_source(
            result.get("title") or "Search result",
            result.get("link"),
            "search",
            result.get("snippet", ""),
        )

    for result in competitor_results[:3]:
        add_source(
            result.get("title") or "Competitor search result",
            result.get("link"),
            "competitor-search",
            result.get("snippet", ""),
        )

    return sources


def _clean_text_list(items: list | None) -> list[str]:
    if not items:
        return []
    cleaned: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned
