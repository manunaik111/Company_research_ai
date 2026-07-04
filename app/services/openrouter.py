"""
OpenRouter client.

OpenRouter exposes a single OpenAI-compatible /chat/completions endpoint
that can route to many different underlying models. We use it for the
one "reasoning" step in the pipeline: turning raw crawled text + search
snippets into a structured summary, pain points, and competitor list.

Model choice is user-selectable (bonus requirement) with a safe default
from the environment.
"""

import os
import json
import httpx
from typing import Optional

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a B2B company research analyst. You will be given \
raw text scraped from a company's website plus some web search snippets. \
Analyze it and respond with ONLY valid JSON (no markdown fences, no prose) \
matching exactly this shape:

{
  "summary": "2-4 sentence plain-language summary of what the company does",
  "products_services": ["short phrase", "..."],
  "pain_points": ["a likely business/operational pain point this company faces, inferred from their market position, products, and competition", "..."],
  "competitors": [{"name": "Competitor Inc", "website": "https://competitor.com or null if unknown"}]
}

Guidelines:
- pain_points should be genuinely inferred insight (e.g. competitive pressure, \
scaling challenges, market shifts), not generic filler like "needs more customers".
- competitors must operate in a similar industry/country with similar products. \
Prefer 3-5 real, named competitors over a padded list.
- If information is missing from the source text, do not invent specifics — \
keep the summary honest about what's known.
- Output raw JSON only. No ```json fences, no explanation before or after.
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
        """
        Send assembled research context to the AI and get back structured
        JSON: summary, products_services, pain_points, competitors.
        """
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
        """Models occasionally wrap JSON in ```json fences despite instructions;
        strip those before parsing so a single formatting slip doesn't blow up
        the whole request."""
        text = raw.strip()
        # Remove markdown code fences line-by-line (avoids str.strip(chars)
        # which strips individual characters, not whole-line prefixes).
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop the opening fence line (e.g. "```json" or "```")
            lines = lines[1:]
            # Drop the closing fence line if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Last resort: find the outermost { ... } block
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start : end + 1])
            raise