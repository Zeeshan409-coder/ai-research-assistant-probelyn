"""Web research pipeline: plan queries → search → fetch & extract → rank → cited answer."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from itertools import zip_longest
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import get_settings
from ..llm import LLM
from . import prompts
from .recording import STORE_SOURCES, recorded
from .text import best_passages, clean

log = logging.getLogger(__name__)

DEPTH = {"quick": (1, 4), "standard": (2, 6), "deep": (3, 10)}  # (queries, max sources)


# ---------------------------------------------------------------- searching
def _ddg_search(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS  # imported lazily: network library, not needed in tests

    try:
        results = DDGS().text(query, max_results=max_results) or []
    except Exception as e:  # rate limits, network errors …
        log.warning("search failed for %r: %s", query, e)
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in results
        if r.get("href", "").startswith("http")
    ]


async def search(query: str, max_results: int) -> list[dict]:
    return await asyncio.to_thread(_ddg_search, query, max_results)


# ----------------------------------------------------------------- fetching
def extract_text(html: str) -> tuple[str, str]:
    """Return (title, main text) from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text()) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = [clean(el.get_text(" ")) for el in root.find_all(["h1", "h2", "h3", "p", "li", "td", "blockquote"])]
    text = " ".join(b for b in blocks if len(b) > 30) or clean(root.get_text(" "))
    return title, text


async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, follow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
            return ""
        return extract_text(r.text)[1]
    except Exception as e:
        log.info("fetch failed %s: %s", url, e)
        return ""


# ------------------------------------------------------------------ pipeline
async def plan_queries(llm: LLM, question: str, n: int, model: str | None) -> list[str]:
    if n <= 1:
        return [question]
    try:
        raw = await llm.chat(prompts.query_planner(question, n - 1), model=model, temperature=0.4)
        extra = [clean(line.strip("-*•0123456789. \"'")) for line in raw.splitlines()]
        extra = [q for q in extra if 3 < len(q) < 200][: n - 1]
    except Exception as e:
        log.warning("query planning failed: %s", e)
        extra = []
    return [question, *extra]


def _dedupe(results: list[dict], limit: int) -> list[dict]:
    seen, out = set(), []
    for r in results:
        key = r["url"].split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def run_web_research(
    llm: LLM, question: str, depth: str = "standard", model: str | None = None
) -> AsyncIterator[dict]:
    return recorded("web", question, model or getattr(llm, "chat_model", None), _web(llm, question, depth, model))


async def _web(llm: LLM, question: str, depth: str, model: str | None) -> AsyncIterator[dict]:
    s = get_settings()
    n_queries, max_sources = DEPTH.get(depth, DEPTH["standard"])

    yield {"event": "status", "data": {"step": "plan", "message": "Planning search queries…"}}
    queries = await plan_queries(llm, question, n_queries, model)
    yield {"event": "queries", "data": queries}

    yield {"event": "status", "data": {"step": "search", "message": f"Searching the web ({len(queries)} queries)…"}}
    batches = await asyncio.gather(*(search(q, s.web_results_per_query) for q in queries))
    # interleave results so each query contributes its top hits
    merged = [r for group in zip_longest(*batches) for r in group if r]
    results = _dedupe(merged, max_sources)
    if not results:
        yield {"event": "error", "data": {"message": "No web results found. Try rephrasing, or check your internet connection."}}
        return

    yield {"event": "status", "data": {"step": "read", "message": f"Reading {len(results)} sources…"}}
    async with httpx.AsyncClient(timeout=s.fetch_timeout, headers={"User-Agent": s.user_agent}) as client:
        pages = await asyncio.gather(*(fetch_page(client, r["url"]) for r in results))

    sources = []
    for i, (r, page) in enumerate(zip(results, pages, strict=True), start=1):
        body = page if len(page) > len(r["snippet"]) else r["snippet"]
        sources.append(
            {
                "n": i,
                "title": r["title"] or urlparse(r["url"]).netloc,
                "url": r["url"],
                "domain": urlparse(r["url"]).netloc.removeprefix("www."),
                "snippet": r["snippet"],
                "excerpt": best_passages(question, body, s.max_chars_per_source),
            }
        )
    stored = [{k: v for k, v in src.items() if k != "excerpt"} for src in sources]
    yield {"event": "sources", "data": stored}
    yield {"event": STORE_SOURCES, "data": stored}

    block = "\n\n".join(f"[{src['n']}] {src['title']} ({src['url']})\n{src['excerpt']}" for src in sources)
    yield {"event": "status", "data": {"step": "write", "message": "Writing cited answer…"}}
    async for tok in llm.stream_chat(prompts.web_answer(question, block), model=model):
        yield {"event": "token", "data": tok}
