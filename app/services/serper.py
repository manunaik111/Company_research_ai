"""
Serper.dev client.

Serper.dev wraps Google Search results behind a simple REST API.
We use it for three distinct jobs in the research pipeline:

1. Resolving a company NAME to its official website URL.
2. Enriching data Serper can answer better than a raw crawl
   (e.g. "site:linkedin.com <company>" for HQ address).
3. Finding competitors ("<company> competitors", "alternatives to <company>").

All methods are async and share one httpx.AsyncClient for connection reuse.
"""

import os
import httpx
from typing import Optional

SERPER_URL = "https://google.serper.dev/search"


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
        """Low-level call to the Serper /search endpoint."""
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
        Given a company name, find the most likely official website.
        Strategy: search the name, take the first organic result whose
        domain doesn't belong to a known aggregator/social site.
        """
        data = await self._search(client, company_name, num=10)
        blocked_domains = (
            "linkedin.com", "wikipedia.org", "crunchbase.com", "facebook.com",
            "twitter.com", "x.com", "instagram.com", "youtube.com", "glassdoor.com",
            "indeed.com", "bloomberg.com", "reuters.com",
        )
        for result in data.get("organic", []):
            link = result.get("link", "")
            if link and not any(bad in link for bad in blocked_domains):
                return link
        return None

    async def search_competitors(
        self, client: httpx.AsyncClient, company_name: str
    ) -> list[dict]:
        """Search for competitor mentions; returns raw organic results
        for the AI step to interpret (titles + snippets + links)."""
        data = await self._search(client, f"{company_name} competitors alternatives", num=10)
        return data.get("organic", [])

    async def search_company_info(
        self, client: httpx.AsyncClient, company_name: str
    ) -> list[dict]:
        """General enrichment search — HQ address, phone, overview —
        used to supplement whatever the crawler couldn't find."""
        data = await self._search(client, f"{company_name} official contact address", num=10)
        return data.get("organic", [])

    async def get_knowledge_graph(
        self, client: httpx.AsyncClient, company_name: str
    ) -> Optional[dict]:
        """Serper sometimes returns a Google Knowledge Graph block with
        structured info (address, phone, description) — free bonus data
        when available."""
        data = await self._search(client, company_name, num=5)
        return data.get("knowledgeGraph")