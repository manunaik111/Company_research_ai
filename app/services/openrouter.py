"""
OpenRouter client.

OpenRouter exposes a single OpenAI-compatible /chat/completions endpoint
that can route to many different underlying models.
"""

import json
import os
from typing import Optional

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a B2B company research analyst. You will be given \
raw text scraped from a company's website plus some web search snippets. \
Analyze it and respond with ONLY valid JSON (no markdown fences, no prose) \
matching exactly this shape:

{
  "company_name": "best clean display name for the company",
  "summary": "2-4 sentence plain-language summary of what the company does",
  "industry": "primary industry/category in a short phrase",
  "target_customers": "who the company mainly serves in one sentence",
  "business_model": "how the company makes money in one sentence",
  "key_highlights": ["specific fact or important observation grounded in the source material", "..."],
  "products_services": ["short phrase", "..."],
  "pain_points": ["a likely business or operational pain point inferred from the context", "..."],
  "competitors": [
    {
      "name": "Competitor Inc",
      "website": "https://competitor.com or null if unknown",
      "rationale": "why this company is a relevant competitor"
    }
  ]
}

Guidelines:
- Prefer concrete, source-grounded details over generic marketing language.
- key_highlights should be factual and specific, not filler.
- pain_points should be genuinely inferred insight, not generic filler.
- competitors must operate in a similar industry, region, or product category.
- Prefer 3-5 real competitors and explain each choice briefly.
- If information is missing from the source text, do not invent specifics.
- Output raw JSON only. No markdown fences or extra prose.
"""


class OpenRouterClient:
    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.default_model = default_model or os.getenv(
            "OPENROUTER_DEFAULT_MODEL", "openai/gpt-4o-mini"
        )

    async def analyze_company(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        crawled_text: str,
        search_context: str,
        model: Optional[str] = None,
    ) -> dict:
        user_prompt = (
            f"Company name: {company_name}\n\n"
            f"--- Website content (crawled) ---\n{crawled_text[:12000]}\n\n"
            f"--- Web search context ---\n{search_context[:4000]}\n\n"
            "Produce the JSON now."
        )

        payload = {
            "model": model or self.default_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
        }

        resp = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

        return self._parse_json_safely(raw)

    @staticmethod
    def _parse_json_safely(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start : end + 1])
            raise
