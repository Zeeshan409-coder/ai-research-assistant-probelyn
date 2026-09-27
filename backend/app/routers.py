"""HTTP API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from . import db
from .config import get_settings
from .llm import LLM, LLMError, get_llm
from .schemas import (
    DeleteEntriesRequest,
    DocumentQuestion,
    ExportRequest,
    PaperImportRequest,
    PaperSearchRequest,
    PaperSummaryRequest,
    WebResearchRequest,
)
from .services import documents, export, papers, prompts, web_search
from .sse import sse_response, stop_run

api = APIRouter(prefix="/api")


# ----------------------------------------------------------------- system
@api.get("/health")
async def health(llm: LLM = Depends(get_llm)):
    s = get_settings()
    models = await llm.list_models()
    ok = await llm.health()

    def installed(name: str) -> bool:
        return any(m == name or m.split(":")[0] == name.split(":")[0] for m in models)

    return {
        "status": "ok",
        "ollama": ok,
        "ollama_url": s.ollama_url,
        "chat_model": s.chat_model,
        "embed_model": s.embed_model,
        "chat_model_installed": installed(s.chat_model),
        "embed_model_installed": installed(s.embed_model),
        "models": models,
    }


# ------------------------------------------------------------- web search
@api.post("/research/web")
async def research_web(req: WebResearchRequest, llm: LLM = Depends(get_llm)):
    return sse_response(web_search.run_web_research(llm, req.question, req.depth, req.model))


@api.post("/runs/{entry_id}/stop")
async def stop_research(entry_id: str):
    """Stop a research run that is still generating. The partial answer is kept in the Library."""
    return {"stopped": stop_run(entry_id)}


# ----------------------------------------------------------------- papers
@api.post("/papers/search")
async def paper_search(req: PaperSearchRequest):
    results, warnings = await papers.search_papers(
        req.query, req.limit, tuple(req.sources), req.year_from, req.sort
    )
    for i, p in enumerate(results, start=1):
        p["n"] = i
    return {"papers": results, "warnings": warnings}


@api.post("/papers/research")
async def paper_research(req: PaperSearchRequest, llm: LLM = Depends(get_llm)):
    return sse_response(
        papers.run_paper_research(
            llm, req.query, req.limit, req.year_from, req.sort, tuple(req.sources), req.model
        )
    )


@api.post("/papers/summarize")
async def paper_summarize(req: PaperSummaryRequest, llm: LLM = Depends(get_llm)):
    async def gen():
        async for tok in llm.stream_chat(prompts.paper_summary(req.title, req.abstract), model=req.model):
            yield {"event": "token", "data": tok}
        yield {"event": "done", "data": {}}

    return sse_response(gen())


@api.post("/papers/import", status_code=202)
async def paper_import(req: PaperImportRequest, background: BackgroundTasks, llm: LLM = Depends(get_llm)):
    try:
        data = await documents.download_pdf(req.pdf_url)
    except Exception as e:
        raise HTTPException(502, f"Could not download PDF: {e}") from e
    doc_id = db.create_document(req.title, Path(req.pdf_url).name or "paper.pdf", source_url=req.pdf_url)
    background.add_task(documents.ingest, llm, doc_id, data, "paper.pdf")
    return db.get_document(doc_id)


# -------------------------------------------------------------- documents
@api.get("/documents")
async def list_documents():
    return db.list_documents()


@api.post("/documents", status_code=202)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    llm: LLM = Depends(get_llm),
):
    s = get_settings()
    filename = file.filename or "upload"
    if Path(filename).suffix.lower() not in documents.SUPPORTED:
        raise HTTPException(415, "Unsupported file type. Upload PDF, TXT or Markdown.")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {s.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, "Empty file.")
    doc_id = db.create_document(title or Path(filename).stem, filename)
    (s.upload_dir / f"{doc_id}{Path(filename).suffix.lower()}").write_bytes(data)
    background.add_task(documents.ingest, llm, doc_id, data, filename)
    return db.get_document(doc_id)


@api.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@api.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: str):
    if not db.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    for f in get_settings().upload_dir.glob(f"{doc_id}.*"):
        f.unlink(missing_ok=True)


@api.post("/documents/ask")
async def ask_documents(req: DocumentQuestion, llm: LLM = Depends(get_llm)):
    ready = [d for d in req.document_ids if (doc := db.get_document(d)) and doc["status"] == "ready"]
    if not ready:
        raise HTTPException(400, "None of the selected documents are ready yet.")
    history = [t.model_dump() for t in req.history]
    return sse_response(documents.run_document_qa(llm, req.question, ready, history, req.model))


# ---------------------------------------------------------------- history
@api.get("/history")
async def history(kind: str | None = None):
    return db.list_entries(kind)


@api.post("/history/delete")
async def delete_history_many(req: DeleteEntriesRequest):
    """Delete several entries at once (e.g. everything ticked in the Library)."""
    return {"deleted": db.delete_entries(req.entry_ids)}


@api.delete("/history")
async def clear_history(confirm: bool = False):
    """Delete the whole history. Requires ?confirm=true as a safety catch."""
    if not confirm:
        raise HTTPException(400, "Add ?confirm=true to delete all history.")
    return {"deleted": db.delete_entries(None)}


@api.get("/history/{entry_id}")
async def history_entry(entry_id: str):
    found = db.get_entries([entry_id])
    if not found:
        raise HTTPException(404, "Entry not found")
    return found[0]


@api.delete("/history/{entry_id}", status_code=204)
async def delete_history(entry_id: str):
    if not db.delete_entry(entry_id):
        raise HTTPException(404, "Entry not found")


@api.post("/export")
async def export_report(req: ExportRequest):
    entries = db.get_entries(req.entry_ids)
    if not entries:
        raise HTTPException(404, "No matching entries")
    name = export.safe_filename(req.title or entries[0]["question"])
    if req.format == "pdf":
        return Response(
            export.to_pdf(entries, req.title),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
        )
    return Response(
        export.to_markdown(entries, req.title),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )


__all__ = ["api", "LLMError"]
