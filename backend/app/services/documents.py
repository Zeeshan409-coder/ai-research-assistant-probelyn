"""Document RAG: parse → chunk → embed → store, and hybrid retrieval for Q&A."""

from __future__ import annotations

import io
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import numpy as np
from pypdf import PdfReader

from .. import db
from ..config import get_settings
from ..llm import LLM
from . import prompts
from .recording import STORE_SOURCES, recorded
from .text import bm25_rank, chunk_text

log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".txt", ".md", ".markdown"}


class DocumentError(ValueError):
    pass


# ------------------------------------------------------------------ parsing
def extract_pages(data: bytes, filename: str) -> list[tuple[int, str]]:
    """Return [(page_number, text)]. Plain-text files are treated as one page."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise DocumentError(f"Unsupported file type '{ext}'. Upload PDF, TXT or Markdown.")
    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as e:
            raise DocumentError(f"Could not read PDF: {e}") from e
        pages = [(i, page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
        if not any(t.strip() for _, t in pages):
            raise DocumentError("No extractable text – the PDF may be scanned images (OCR not supported).")
        return pages
    return [(1, data.decode("utf-8", errors="ignore"))]


def chunk_pages(pages: list[tuple[int, str]], size: int, overlap: int) -> list[dict]:
    out = []
    for page, text in pages:
        # re-join words hyphenated across line breaks in PDFs
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        out.extend({"page": page, "text": c} for c in chunk_text(text, size, overlap))
    return out


def guess_title(pages: list[tuple[int, str]], filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    for _, text in pages[:1]:
        for line in text.splitlines()[:8]:
            line = line.strip()
            if 12 <= len(line) <= 160 and not line.lower().startswith(("arxiv", "http", "doi", "preprint")):
                return line
    return stem or "Untitled document"


# ---------------------------------------------------------------- ingestion
async def ingest(llm: LLM, doc_id: str, data: bytes, filename: str) -> None:
    """Background job: parse, chunk, embed and store. Updates the document status."""
    s = get_settings()
    try:
        pages = extract_pages(data, filename)
        chunks = chunk_pages(pages, s.chunk_size, s.chunk_overlap)
        if not chunks:
            raise DocumentError("Document contains no text.")
        embeddings = await llm.embed([c["text"] for c in chunks])
        db.insert_chunks(doc_id, chunks, embeddings)
        doc = db.get_document(doc_id) or {}
        fields = {"status": "ready", "pages": len(pages), "chunks": len(chunks)}
        if doc.get("title") == Path(filename).stem:  # user didn't supply a title
            fields["title"] = guess_title(pages, filename)
        db.update_document(doc_id, **fields)
    except Exception as e:
        log.exception("ingest failed for %s", filename)
        db.update_document(doc_id, status="error", error=str(e)[:500])


async def download_pdf(url: str) -> bytes:
    s = get_settings()
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers={"User-Agent": s.user_agent}) as c:
        r = await c.get(url)
        r.raise_for_status()
        if len(r.content) > s.max_upload_mb * 1024 * 1024:
            raise DocumentError("PDF is too large.")
        if not r.content.startswith(b"%PDF"):
            raise DocumentError("URL did not return a PDF.")
        return r.content


# ---------------------------------------------------------------- retrieval
def _normalize(x: np.ndarray) -> np.ndarray:
    if x.size == 0 or x.max() == x.min():
        return np.zeros_like(x)
    return (x - x.min()) / (x.max() - x.min())


def hybrid_rank(query_vec: np.ndarray, query: str, chunks: list[dict], top_k: int, alpha: float = 0.75) -> list[dict]:
    """Blend dense cosine similarity with BM25 keyword relevance."""
    if not chunks:
        return []
    mat = np.stack([c["embedding"] for c in chunks])
    q = query_vec / (np.linalg.norm(query_vec) or 1)
    cos = mat @ q / (np.linalg.norm(mat, axis=1) + 1e-9)
    lex = np.asarray(bm25_rank(query, [c["text"] for c in chunks]), dtype=np.float32)
    score = alpha * _normalize(cos) + (1 - alpha) * _normalize(lex)
    idx = np.argsort(-score)[:top_k]
    return [{**chunks[i], "score": float(score[i])} for i in idx]


async def retrieve(llm: LLM, question: str, document_ids: list[str], top_k: int) -> list[dict]:
    chunks = db.load_chunks(document_ids)
    if not chunks:
        return []
    [qvec] = await llm.embed([question])
    return hybrid_rank(np.asarray(qvec, dtype=np.float32), question, chunks, top_k)


def run_document_qa(
    llm: LLM,
    question: str,
    document_ids: list[str],
    history: list[dict] | None = None,
    model: str | None = None,
) -> AsyncIterator[dict]:
    return recorded(
        "documents", question, model or getattr(llm, "chat_model", None),
        _doc_qa(llm, question, document_ids, history, model),
    )


async def _doc_qa(llm, question, document_ids, history, model) -> AsyncIterator[dict]:
    s = get_settings()
    yield {"event": "status", "data": {"step": "retrieve", "message": "Searching your documents…"}}
    hits = await retrieve(llm, question, document_ids, s.top_k)
    if not hits:
        yield {"event": "error", "data": {"message": "No indexed text found in the selected documents."}}
        return
    sources = [
        {
            "n": i,
            "title": h["title"],
            "document_id": h["document_id"],
            "page": h["page"],
            "snippet": h["text"][:320],
            "score": round(h["score"], 3),
            "domain": f"p. {h['page']}",
        }
        for i, h in enumerate(hits, start=1)
    ]
    yield {"event": "sources", "data": sources}
    yield {"event": STORE_SOURCES, "data": sources}

    block = "\n\n".join(f"[{i}] {h['title']} — page {h['page']}\n{h['text']}" for i, h in enumerate(hits, start=1))
    yield {"event": "status", "data": {"step": "write", "message": "Writing answer…"}}
    async for tok in llm.stream_chat(prompts.document_answer(question, block, history or []), model=model):
        yield {"event": "token", "data": tok}
