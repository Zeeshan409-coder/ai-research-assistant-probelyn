"""Text utilities: cleaning, chunking and lightweight lexical relevance scoring."""

from __future__ import annotations

import math
import re
from collections import Counter

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = set(
    "a an the and or but if then of to in on for with by from at as is are was were be been being it its "
    "this that these those what which who whom how why when where do does did can could should would will "
    "about into than too very not no so such i you he she we they me my our your their".split()
)


def clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into ~size-char chunks with overlap, preferring sentence boundaries."""
    text = clean(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # try to end on a sentence boundary in the last 30% of the window
            window = text[start + int(size * 0.7) : end]
            m = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
            if m != -1:
                end = start + int(size * 0.7) + m + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def bm25_rank(query: str, passages: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 scores of each passage for the query (no external deps)."""
    q = tokens(query)
    docs = [tokens(p) for p in passages]
    if not docs or not q:
        return [0.0] * len(passages)
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n or 1
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        scores.append(s)
    return scores


def best_passages(query: str, text: str, max_chars: int, passage_size: int = 500) -> str:
    """Pick the most query-relevant passages of a long page, keeping original order."""
    if len(text) <= max_chars:
        return text
    passage_size = max(150, min(passage_size, max_chars // 4))  # leave room for several passages
    passages = chunk_text(text, size=passage_size, overlap=0)
    scores = bm25_rank(query, passages)
    # always keep the opening passage (usually the summary/lede)
    order = sorted(range(1, len(passages)), key=lambda i: scores[i], reverse=True)
    chosen, total = {0}, len(passages[0])
    for i in order:
        if total + len(passages[i]) > max_chars:
            continue
        chosen.add(i)
        total += len(passages[i])
    return " … ".join(passages[i] for i in sorted(chosen))


def cited_numbers(answer: str) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d{1,3})\]", answer)}
