from typing import Literal

from pydantic import BaseModel, Field


class WebResearchRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    depth: Literal["quick", "standard", "deep"] = "standard"
    model: str | None = None


class PaperSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(10, ge=1, le=30)
    year_from: int | None = Field(None, ge=1900, le=2100)
    sort: Literal["relevance", "citations", "recent"] = "relevance"
    sources: list[Literal["arxiv", "s2"]] = ["arxiv", "s2"]
    overview: bool = True
    model: str | None = None


class PaperSummaryRequest(BaseModel):
    title: str
    abstract: str = Field(min_length=20)
    model: str | None = None


class PaperImportRequest(BaseModel):
    pdf_url: str = Field(pattern=r"^https?://")
    title: str


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class DocumentQuestion(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[str] = Field(min_length=1)
    history: list[ChatTurn] = []
    model: str | None = None


class ExportRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1)
    title: str | None = None
    format: Literal["md", "pdf"] = "md"


class DeleteEntriesRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=1000)
