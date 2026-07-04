# Design Decisions

This document explains *why* the project is built the way it is — the
tradeoffs considered and the reasoning behind each major choice, for
anyone reviewing the submission.

---

## 1. Why Python + FastAPI (not Node/Next.js, Flask, or Django)

The assignment explicitly allows any language/framework ("Can I use any
programming language or framework? Yes."). Python was chosen because:

- **Async by default.** The pipeline makes several independent I/O calls per
  request (Serper searches, page crawls, OpenRouter call). FastAPI's native
  `async`/`await` lets these run concurrently (`asyncio.gather`) instead of
  serially, meaningfully cutting response time without added complexity.
- **Validation built in.** Pydantic models (`app/models.py`) define one shared
  contract for the crawler, AI layer, PDF generator, and Discord sender —
  reducing the chance that one part of the pipeline silently drifts out of
  sync with another.
- **Lighter than Flask/Django for this scope.** No ORM, no templating engine
  beyond a single Jinja2 page, no admin panel — FastAPI gives just the routing
  + validation + async support this project actually needs, nothing more.
- **Familiarity.** Faster, more careful iteration in the time available beats
  a "should be fine" attempt in an unfamiliar stack.

## 2. Why a single FastAPI app instead of separate frontend/backend services

The spec requires deployment "as a single unified project." A Python backend
serving a plain HTML/CSS/JS frontend directly (via Jinja2 + StaticFiles)
avoids:
- A second deploy target (no separate Vercel/Netlify frontend + API split)
- A build step (no bundler, no `npm run build`) — clone, `pip install`, run
- CORS complexity — frontend and backend share an origin

The tradeoff: a framework like React would make the "chat conversation" state
management slightly more elegant. Given the actual UI complexity here (one
form, a scrolling log, cloneable result cards), vanilla JS with a `<template>`
element does the job without that overhead.

## 3. Why a lightweight HTTP crawler instead of a headless browser

`httpx` + `selectolax` was chosen over Playwright/Selenium:
- **Speed.** No browser process to spin up per page — fetches are just HTTP
  requests, which matters when crawling up to 8 pages per request inside a
  reasonable total response time.
- **Resource footprint.** No Chromium binary to install/ship, which simplifies
  the Render deployment (no extra buildpack/system dependencies).
- **Sufficient for the target content.** Company marketing sites (About,
  Products, Pricing, Contact) are overwhelmingly server-rendered HTML.

**Tradeoff, stated plainly:** JavaScript-heavy single-page apps that render
content client-side will return thin/empty extracted text with this approach.
This is a known limitation, documented in the README rather than hidden. A
production iteration could add a headless-browser fallback specifically for
domains that return suspiciously little text.

## 4. Why link-priority-based crawling instead of naive breadth-first crawling

Links are classified (about/products/services/solutions/pricing/contact) and
sorted by that priority *before* the page-count cap is applied
(`app/services/crawler.py`). A large site with hundreds of links would, under
naive breadth-first crawling, likely burn the page budget on irrelevant pages
discovered first (e.g. blog posts, footer links). Prioritizing ensures the
crawl reliably lands on the informative pages the spec explicitly asks for,
regardless of a site's link ordering.

## 5. Why Serper's Knowledge Graph is used opportunistically for contact info

Rather than relying solely on crawling a site's Contact page (which may not
exist, may be JS-rendered, or may lack a clean phone/address), the app also
queries Serper's Knowledge Graph data (surfaced from Google's own structured
data) as a parallel, low-cost source. When both are available, this improves
the odds of a report having real contact info instead of "Not publicly
listed" — directly supporting the "Company Research" scoring criterion.

## 6. Why the AI prompt explicitly bans generic/padded pain points

Early in scoping, "AI-generated pain points" is easy to satisfy shallowly
(e.g. "needs more customers," "wants to grow revenue" — true of almost any
company and therefore low-value). The system prompt
(`app/services/openrouter.py`) explicitly instructs the model to infer
pain points from competitive position, product scope, and market context —
aiming for the kind of insight that demonstrates actual reasoning over the
crawled/searched content, not filler.

## 7. Why the app filters low-trust sources and weak competitor suggestions

The raw search API can surface helpful material, but it also returns plenty of
low-signal pages such as complaint sites, YouTube explainers, listicles, and
generic competitor roundups. The research pipeline now post-processes sources
and competitor suggestions so the final report stays closer to the company's
own website and higher-trust public references. That tradeoff makes the output
more defensible in a hiring review, even if it occasionally drops a plausible
but lower-confidence source.

## 8. Why every external call has its own try/except, returning a soft error

Serper, the crawler, and OpenRouter are three independent points of failure
outside this app's control (rate limits, site blocking bots, model timeouts).
Rather than letting any one of them raise an unhandled exception (→ a raw
500 to the user), each stage in `app/routes/research.py` returns a specific,
readable `ResearchResponse(success=False, error=...)`. This maps directly to
the "Handling of edge cases and robustness" evaluation criterion — the app
degrading gracefully with a clear message is a deliberate design goal, not
an afterthought.

## 9. Why Discord uses direct REST calls instead of a bot library

`discord.py` (or similar) requires a persistent websocket "gateway"
connection to function as a running bot — appropriate for a bot that listens
for events, inappropriate for an app that only ever needs to *send* one
message with an attachment after a report is generated. A direct
`POST /channels/{id}/messages` call with a bot token (`app/services/
discord_sender.py`) accomplishes the same outcome with zero extra process
management, and keeps the app single-process/stateless — consistent with
the "no persistent server processes beyond the web service" spirit of a
serverless-friendly deploy.

## 10. Why API keys are environment-variables-only (no key entry in the UI)

Although the spec's sample screenshots show key-entry fields in a Settings
panel, storing real secrets in browser state (even client-side-only) adds
risk with no real benefit here: the evaluator provides one set of credentials
to test the one deployed instance. Reading keys exclusively from server-side
environment variables (`.env` locally, Render's secret env vars in
production) means:
- Keys are never present in any HTTP response, browser storage, or client JS
- The same deployed instance can be re-tested without re-entering keys
- There's no risk of keys leaking via browser devtools/network tab

This was an explicit instruction from the project owner and is treated as
the correct choice for a real deployment, not just a shortcut.

## 11. Why PDF generation is a separate endpoint from research

`/api/research` (slow: search + crawl + AI call) and `/api/pdf` (fast: pure
rendering from already-known data) are split so that downloading a PDF, or
re-downloading it, never re-triggers external API calls. This avoids
unnecessary Serper/OpenRouter usage (both often rate-limited or metered) and
keeps the PDF button responsive regardless of how slow the original research
call was.

## 12. Why Render over Vercel/Netlify for this specific app

Vercel/Netlify's serverless functions are optimized for short-lived requests
(often 10–15s default limits on free tiers) and don't suit Python well
(cold starts, limited native library support for something like `reportlab`
in some serverless Python runtimes). A crawl + AI call can reasonably take
5–15 seconds on its own. Render (or Railway/Fly.io) runs the app as a
long-lived process, avoiding timeout edge cases entirely — the FAQ
explicitly allows "any equivalent deployment platform," and this was judged
the more reliable choice for this specific workload.

---

## Summary

Every decision above optimizes for the same underlying goal the assignment
itself names as its purpose: evaluating real engineering judgment under
constraints, not just checking boxes. Where a shortcut was tempting (naive
crawling, no error handling, bot-library overkill, browser-stored secrets),
the tradeoff is named explicitly here rather than left implicit — the aim
is for the reasoning to be as legible as the code.
