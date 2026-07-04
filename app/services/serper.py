"""
Serper.dev client.

Serper.dev wraps Google Search results behind a simple REST API.
We use it for three distinct jobs in the research pipeline:

1. Resolving a company name to its official website URL.
2. Enriching data Serper can answer better than a raw crawl.
3. Finding competitors and supporting context.
"""

import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

SERPER_URL = "https://google.serper.dev/search"

CORPORATE_SUFFIXES = {
    "inc",
    "corp",
    "corporation",
    "llc",
    "ltd",
    "limited",
    "company",
    "co",
    "group",
    "technology",
    "technologies",
    "systems",
    "holdings",
}

BLOCKED_DOMAINS = {
    "linkedin.com",
    "wikipedia.org",
    "crunchbase.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "glassdoor.com",
    "indeed.com",
    "bloomberg.com",
    "reuters.com",
    "play.google.com",
    "apps.apple.com",
    "github.com",
    "g2.com",
    "capterra.com",
}

BLOCKED_PATH_KEYWORDS = {
    "/store/apps",
    "/apps/details",
    "/download",
    "/downloads",
    "/support",
    "/help",
    "/docs",
    "/documentation",
    "/blog",
    "/news",
    "/press",
    "/careers",
    "/jobs",
    "/login",
    "/signup",
    "/register",
}


class SerperClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is not set")
        self._headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    async def _search(self, client: httpx.AsyncClient, query: str, num: int = 10) -> dict:
        resp = await client.post(
            SERPER_URL,
            headers=self._headers,
            json={"q": query, "num": num},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    async def find_official_website(
        self, client: httpx.AsyncClient, company_name: str
    ) -> Optional[str]:
        """
        Search for the official website and rank results so the homepage
        beats app stores, help centers, and aggregators.
        """
        data = await self._search(client, f"{company_name} official website", num=10)

        knowledge_graph = data.get("knowledgeGraph") or {}
        answer_box = data.get("answerBox") or {}

        for candidate in (knowledge_graph.get("website"), answer_box.get("link")):
            normalized = _normalize_candidate_url(candidate)
            if normalized and self._score_official_site_candidate(
                normalized, company_name, "official website", ""
            ) > 0:
                return normalized

        best_link = None
        best_score = float("-inf")

        for result in data.get("organic", []):
            link = _normalize_candidate_url(result.get("link"))
            if not link:
                continue
            score = self._score_official_site_candidate(
                link,
                company_name,
                result.get("title", ""),
                result.get("snippet", ""),
            )
            if score > best_score:
                best_score = score
                best_link = link

        if best_score > 0:
            return best_link
        return None

    async def search_competitors(
        self, client: httpx.AsyncClient, company_name: str
    ) -> list[dict]:
        data = await self._search(client, f"{company_name} competitors alternatives", num=10)
        return data.get("organic", [])

    async def search_company_info(
        self, client: httpx.AsyncClient, company_name: str
    ) -> list[dict]:
        data = await self._search(client, f"{company_name} official contact address", num=10)
        return data.get("organic", [])

    async def get_knowledge_graph(
        self, client: httpx.AsyncClient, company_name: str
    ) -> Optional[dict]:
        data = await self._search(client, company_name, num=5)
        return data.get("knowledgeGraph")

    def _score_official_site_candidate(
        self,
        url: str,
        company_name: str,
        title: str,
        snippet: str,
    ) -> int:
        parsed = urlparse(url)
        hostname = parsed.netloc.lower().replace("www.", "")
        path = (parsed.path or "/").lower()
        text = f"{title} {snippet}".lower()
        score = 0

        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in BLOCKED_DOMAINS):
            score -= 80
        if any(keyword in path for keyword in BLOCKED_PATH_KEYWORDS):
            score -= 45
        if parsed.query:
            score -= 10

        labels = [part for part in hostname.split(".") if part]
        main_label = labels[0] if labels else ""
        subdomain_count = max(len(labels) - 2, 0)
        if subdomain_count == 0:
            score += 15
        elif main_label not in {"www", "app"}:
            score -= 10

        if path in {"", "/"}:
            score += 20
        elif path.count("/") <= 1 and len(path.strip("/")) <= 18:
            score += 8
        else:
            score -= 10

        company_tokens = _company_tokens(company_name)
        domain_text = hostname.replace("-", " ")
        if any(token == main_label for token in company_tokens):
            score += 30
        if any(token in domain_text for token in company_tokens):
            score += 18
        if any(token in text for token in company_tokens):
            score += 10

        if "official site" in text or "official website" in text:
            score += 12
        if any(
            bad in text
            for bad in ["app on google play", "app store", "download", "support", "help center"]
        ):
            score -= 35

        return score


def _normalize_candidate_url(url: str | None) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    clean_path = parsed.path or "/"
    if clean_path != "/":
        clean_path = clean_path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}"


def _company_tokens(company_name: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", company_name.lower())
    tokens = [token for token in cleaned.split() if token and token not in CORPORATE_SUFFIXES]
    if tokens:
        return tokens
    fallback = cleaned.strip()
    return [fallback] if fallback else []
