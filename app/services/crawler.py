"""
Website crawler.

Given a base URL, this module:
  1. Fetches the homepage.
  2. Discovers internal links.
  3. Classifies links against a set of "interesting" page types
     (about, products, services, solutions, contact, pricing).
  4. Dedupes by normalized URL (ignoring query strings / fragments /
     trailing slashes so /about and /about/ and /about?ref=x collapse
     to one entry).
  5. Filters out login/auth pages and obviously irrelevant links
     (social media, mailto:, tel:, anchors, assets).
  6. Fetches the shortlisted pages concurrently (bounded by a semaphore
     so we don't hammer the target site) and extracts clean text.

This is intentionally a lightweight HTTP + HTML-parse crawler rather
than a headless browser: fast, low-resource, and sufficient for the
marketing/informational pages this app targets. JS-rendered SPAs are
a known limitation (documented in the README).
"""

import os
import asyncio
from urllib.parse import urljoin, urlparse, urlunparse
import httpx
from selectolax.parser import HTMLParser

MAX_PAGES = int(os.getenv("CRAWLER_MAX_PAGES", "8"))
PAGE_TIMEOUT = float(os.getenv("CRAWLER_PAGE_TIMEOUT", "10"))
MAX_CONCURRENT_FETCHES = 4

USER_AGENT = (
    "Mozilla/5.0 (compatible; CompanyResearchBot/1.0; "
    "+https://github.com/your-repo/company-research-ai)"
)

# Keywords used to classify a link's likely page type. Order = priority
# when trimming down to MAX_PAGES.
INTERESTING_PATTERNS = [
    ("about", ["about", "company", "who-we-are", "our-story"]),
    ("products", ["product", "features"]),
    ("services", ["service"]),
    ("solutions", ["solution"]),
    ("pricing", ["pricing", "plans"]),
    ("contact", ["contact"]),
]

# Links matching these should never be crawled.
BLOCKED_PATTERNS = [
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "logout", "cart", "checkout", "account", "admin", "wp-admin",
    ".pdf", ".jpg", ".png", ".zip", ".svg", ".css", ".js",
    "mailto:", "tel:", "javascript:", "#",
]

SOCIAL_DOMAINS = [
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com",
    "youtube.com", "tiktok.com", "pinterest.com",
]


def _normalize_url(url: str) -> str:
    """Strip query string, fragment, and trailing slash so equivalent
    URLs dedupe correctly."""
    parsed = urlparse(url)
    cleaned = parsed._replace(query="", fragment="")
    normalized = urlunparse(cleaned)
    return normalized.rstrip("/")


def _classify(url: str) -> str:
    lower = url.lower()
    for label, keywords in INTERESTING_PATTERNS:
        if any(kw in lower for kw in keywords):
            return label
    return "other"


def _is_blocked(url: str, base_domain: str) -> bool:
    lower = url.lower()
    if any(bad in lower for bad in BLOCKED_PATTERNS):
        return True
    if any(social in lower for social in SOCIAL_DOMAINS):
        return True
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != base_domain:
        return True  # external link, not part of this site
    return False


def _extract_text(html: str) -> str:
    """Strip script/style/nav/footer noise and return readable text."""
    tree = HTMLParser(html)
    for tag in tree.css("script, style, nav, footer, noscript, svg"):
        tag.decompose()
    text = tree.text(separator=" ", strip=True)
    # Collapse excessive whitespace
    return " ".join(text.split())


def _discover_links(html: str, base_url: str, base_domain: str) -> dict[str, str]:
    """Return {normalized_url: page_type} for interesting, non-blocked
    internal links found on a page."""
    tree = HTMLParser(html)
    found: dict[str, str] = {}
    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href", "")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if _is_blocked(absolute, base_domain):
            continue
        normalized = _normalize_url(absolute)
        page_type = _classify(normalized)
        if page_type != "other" and normalized not in found:
            found[normalized] = page_type
    return found


async def crawl_site(website: str) -> dict:
    """
    Crawl `website` and return:
    {
        "pages": {url: {"type": str, "text": str}},
        "warnings": [str, ...]
    }
    """
    warnings: list[str] = []
    base_domain = urlparse(website).netloc
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        # 1. Fetch homepage
        try:
            home_resp = await client.get(website, timeout=PAGE_TIMEOUT)
            home_resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            return {
                "pages": {},
                "warnings": [f"Could not reach homepage: {e}"],
            }

        home_html = home_resp.text
        home_url = _normalize_url(str(home_resp.url))
        pages: dict[str, dict] = {home_url: {"type": "home", "text": _extract_text(home_html)}}

        # 2. Discover links from homepage
        discovered = _discover_links(home_html, website, base_domain)
        # Prioritize by INTERESTING_PATTERNS order, cap at MAX_PAGES - 1 (homepage already counted)
        priority_order = [label for label, _ in INTERESTING_PATTERNS]
        ordered_links = sorted(
            discovered.items(),
            key=lambda kv: priority_order.index(kv[1]) if kv[1] in priority_order else 99,
        )[: MAX_PAGES - 1]

        # 3. Fetch shortlisted pages concurrently, bounded by a semaphore
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

        async def fetch_one(url: str, page_type: str):
            async with semaphore:
                try:
                    resp = await client.get(url, timeout=PAGE_TIMEOUT)
                    resp.raise_for_status()
                    return url, page_type, _extract_text(resp.text)
                except (httpx.HTTPError, httpx.TimeoutException) as e:
                    warnings.append(f"Skipped {url} ({e.__class__.__name__})")
                    return url, page_type, None

        results = await asyncio.gather(
            *(fetch_one(url, ptype) for url, ptype in ordered_links)
        )

        for url, page_type, text in results:
            if text:
                pages[url] = {"type": page_type, "text": text}

        missing_types = {label for label, _ in INTERESTING_PATTERNS} - {
            p["type"] for p in pages.values()
        }
        if missing_types:
            warnings.append(
                f"No page found for: {', '.join(sorted(missing_types))}"
            )

    return {"pages": pages, "warnings": warnings}