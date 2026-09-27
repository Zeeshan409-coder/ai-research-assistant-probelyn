"""Academic paper search across arXiv and Semantic Scholar, plus LLM overviews."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from itertools import zip_longest

import httpx

from ..config import get_settings
from ..llm import LLM
from . import prompts
from .recording import STORE_SOURCES, recorded
from .text import clean

log = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,authors,year,venue,citationCount,url,openAccessPdf,externalIds"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class PaperSearchError(RuntimeError):
    pass


# -------------------------------------------------------------------- arXiv
def parse_arxiv(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    papers = []
    for e in root.findall("a:entry", ATOM):
        abs_url = (e.findtext("a:id", "", ATOM) or "").strip()
        arxiv_id = abs_url.rsplit("/abs/", 1)[-1]
        pdf = next(
            (lk.get("href") for lk in e.findall("a:link", ATOM) if lk.get("title") == "pdf"),
            abs_url.replace("/abs/", "/pdf/"),
        )
        published = e.findtext("a:published", "", ATOM)
        papers.append(
            {
                "id": f"arxiv:{arxiv_id}",
                "title": clean(e.findtext("a:title", "", ATOM)),
                "authors": [clean(a.findtext("a:name", "", ATOM)) for a in e.findall("a:author", ATOM)],
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "venue": "arXiv" + (f" · {c.get('term')}" if (c := e.find("arxiv:primary_category", ATOM)) is not None else ""),
                "abstract": clean(e.findtext("a:summary", "", ATOM)),
                "url": abs_url,
                "pdf_url": pdf,
                "citations": None,
                "source": "arXiv",
            }
        )
    return papers


async def search_arxiv(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w-]+", query)[:8]) or f"all:{query}"
    r = await client.get(
        ARXIV_API, params={"search_query": terms, "start": 0, "max_results": limit, "sortBy": "relevance"}
    )
    r.raise_for_status()
    return parse_arxiv(r.text)


# --------------------------------------------------------- Semantic Scholar
def parse_s2(payload: dict) -> list[dict]:
    papers = []
    for p in payload.get("data") or []:
        if not p.get("title"):
            continue
        ext = p.get("externalIds") or {}
        pdf = (p.get("openAccessPdf") or {}).get("url") or (
            f"https://arxiv.org/pdf/{ext['ArXiv']}" if ext.get("ArXiv") else None
        )
        papers.append(
            {
                "id": f"s2:{p.get('paperId')}",
                "title": clean(p["title"]),
                "authors": [a.get("name", "") for a in p.get("authors") or []],
                "year": p.get("year"),
                "venue": p.get("venue") or "",
                "abstract": clean(p.get("abstract") or ""),
                "url": p.get("url") or "",
                "pdf_url": pdf,
                "citations": p.get("citationCount"),
                "source": "Semantic Scholar",
            }
        )
    return papers


async def search_s2(client: httpx.AsyncClient, query: str, limit: int, year_from: int | None) -> list[dict]:
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    if year_from:
        params["year"] = f"{year_from}-"
    headers = {}
    if key := get_settings().semantic_scholar_api_key:
        headers["x-api-key"] = key
    for attempt in range(3):  # the free tier rate-limits aggressively
        r = await client.get(S2_API, params=params, headers=headers)
        if r.status_code == 429:
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        r.raise_for_status()
        return parse_s2(r.json())
    raise PaperSearchError("Semantic Scholar rate limit reached – try again in a minute.")


# -------------------------------------------------------------------- merge
def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def merge_papers(groups: list[list[dict]], limit: int) -> list[dict]:
    by_title: dict[str, dict] = {}
    for p in (p for g in zip_longest(*groups) for p in g if p):
        key = _norm(p["title"])
        if key in by_title:  # fill gaps from the other source
            existing = by_title[key]
            for field in ("abstract", "pdf_url", "citations", "venue", "year"):
                if not existing.get(field) and p.get(field):
                    existing[field] = p[field]
            if p["source"] not in existing["source"]:
                existing["source"] += f" + {p['source']}"
        else:
            by_title[key] = dict(p)
    return list(by_title.values())[:limit]


def sort_papers(papers: list[dict], sort: str) -> list[dict]:
    if sort == "citations":
        return sorted(papers, key=lambda p: p.get("citations") or -1, reverse=True)
    if sort == "recent":
        return sorted(papers, key=lambda p: p.get("year") or 0, reverse=True)
    return papers


async def search_papers(
    query: str,
    limit: int = 12,
    sources: tuple[str, ...] = ("arxiv", "s2"),
    year_from: int | None = None,
    sort: str = "relevance",
) -> tuple[list[dict], list[str]]:
    """Returns (papers, warnings). One provider failing doesn't fail the search."""
    per = max(4, limit)
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "Probelyn/1.0"}) as client:
        tasks, names = [], []
        if "arxiv" in sources:
            tasks.append(search_arxiv(client, query, per))
            names.append("arXiv")
        if "s2" in sources:
            tasks.append(search_s2(client, query, per, year_from))
            names.append("Semantic Scholar")
        results = await asyncio.gather(*tasks, return_exceptions=True)
    groups, warnings = [], []
    for name, res in zip(names, results, strict=True):
        if isinstance(res, Exception):
            log.warning("%s search failed: %s", name, res)
            warnings.append(f"{name} unavailable: {res}")
        else:
            groups.append(res)
    papers = merge_papers(groups, limit * 2)
    if year_from:
        papers = [p for p in papers if not p.get("year") or p["year"] >= year_from]
    return sort_papers(papers, sort)[:limit], warnings


# ---------------------------------------------------------------- pipeline
def run_paper_research(
    llm: LLM,
    query: str,
    limit: int = 10,
    year_from: int | None = None,
    sort: str = "relevance",
    sources: tuple[str, ...] = ("arxiv", "s2"),
    model: str | None = None,
) -> AsyncIterator[dict]:
    return recorded(
        "papers", query, model or getattr(llm, "chat_model", None),
        _papers(llm, query, limit, year_from, sort, sources, model),
    )


async def _papers(llm, query, limit, year_from, sort, sources, model) -> AsyncIterator[dict]:
    yield {"event": "status", "data": {"step": "search", "message": "Searching arXiv and Semantic Scholar…"}}
    papers, warnings = await search_papers(query, limit, sources, year_from, sort)
    for w in warnings:
        yield {"event": "warning", "data": {"message": w}}
    if not papers:
        yield {"event": "error", "data": {"message": "No papers found. Try broader keywords."}}
        return
    for i, p in enumerate(papers, start=1):
        p["n"] = i
    yield {"event": "papers", "data": papers}
    yield {
        "event": STORE_SOURCES,
        "data": [
            {
                "n": p["n"],
                "title": p["title"],
                "url": p["url"],
                "authors": p["authors"][:6],
                "year": p["year"],
                "venue": p["venue"],
                "domain": p["source"],
            }
            for p in papers
        ],
    }

    with_abs = [p for p in papers if p["abstract"]]
    block = "\n\n".join(
        f"[{p['n']}] {p['title']} ({', '.join(p['authors'][:3])}{' et al.' if len(p['authors']) > 3 else ''}, "
        f"{p['year'] or 'n.d.'})\n{p['abstract'][:1500]}"
        for p in with_abs
    )
    yield {"event": "status", "data": {"step": "write", "message": "Writing literature overview…"}}
    async for tok in llm.stream_chat(prompts.literature_review(query, block), model=model):
        yield {"event": "token", "data": tok}
