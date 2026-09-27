"""SQLite persistence: research history, documents and their embedded chunks."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import numpy as np

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,              -- web | papers | documents
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]', -- JSON list
    model       TEXT,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'done' -- running | done | stopped | error
);
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    filename    TEXT NOT NULL,
    pages       INTEGER DEFAULT 0,
    chunks      INTEGER DEFAULT 0,
    status      TEXT NOT NULL,              -- processing | ready | error
    error       TEXT,
    source_url  TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    page        INTEGER,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def connect():
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(entries)")}
        if "status" not in cols:  # migrate databases created by v1.0
            c.execute("ALTER TABLE entries ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")
        # anything still 'running' was interrupted by a server restart
        c.execute("UPDATE entries SET status = 'error' WHERE status = 'running'")


# ------------------------------------------------------------------ entries
def save_entry(
    kind: str, question: str, answer: str, sources: list[dict], model: str | None, status: str = "done"
) -> str:
    eid = new_id()
    with connect() as c:
        c.execute(
            "INSERT INTO entries (id, kind, question, answer, sources, model, created_at, status)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (eid, kind, question, answer, json.dumps(sources), model, now(), status),
        )
    return eid


def update_entry(eid: str, **fields) -> None:
    if "sources" in fields:
        fields["sources"] = json.dumps(fields["sources"])
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE entries SET {cols} WHERE id = ?", (*fields.values(), eid))


class EntryRecorder:
    """Saves a research run to history from the moment it starts.

    The entry is created as 'running', receives the answer progressively and is
    marked 'done' (or 'error') at the end, so nothing is lost if the user
    navigates away mid-answer.
    """

    FLUSH_EVERY = 1.5  # seconds between partial-answer writes

    def __init__(self, kind: str, question: str, model: str | None):
        self.id = save_entry(kind, question, "", [], model, status="running")
        self.answer = ""
        self._last_flush = datetime.now().timestamp()

    def sources(self, sources: list[dict]) -> None:
        update_entry(self.id, sources=sources)

    def token(self, tok: str) -> None:
        self.answer += tok
        t = datetime.now().timestamp()
        if t - self._last_flush > self.FLUSH_EVERY:
            update_entry(self.id, answer=self.answer)
            self._last_flush = t

    def finish(self) -> str:
        update_entry(self.id, answer=self.answer, status="done")
        return self.id

    def stop(self) -> None:
        text = (self.answer.rstrip() + "\n\n" if self.answer else "") + "> ⏹ Stopped by user."
        update_entry(self.id, answer=text, status="stopped")

    def fail(self, message: str) -> None:
        text = (self.answer + "\n\n" if self.answer else "") + f"> ⚠️ {message}"
        update_entry(self.id, answer=text, status="error")


def _entry(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d["sources"])
    return d


def list_entries(kind: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM entries", ()
    if kind:
        q, args = q + " WHERE kind = ?", (kind,)
    with connect() as c:
        return [_entry(r) for r in c.execute(q + " ORDER BY created_at DESC", args)]


def get_entries(ids: list[str]) -> list[dict]:
    with connect() as c:
        rows = {r["id"]: _entry(r) for r in c.execute(
            f"SELECT * FROM entries WHERE id IN ({','.join('?' * len(ids))})", ids
        )}
    return [rows[i] for i in ids if i in rows]


def delete_entries(ids: list[str] | None = None) -> int:
    """Delete the given entries, or every entry when ids is None. Returns the count removed."""
    with connect() as c:
        if ids is None:
            return c.execute("DELETE FROM entries").rowcount
        if not ids:
            return 0
        return c.execute(f"DELETE FROM entries WHERE id IN ({','.join('?' * len(ids))})", ids).rowcount


def delete_entry(eid: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM entries WHERE id = ?", (eid,)).rowcount > 0


# ---------------------------------------------------------------- documents
def create_document(title: str, filename: str, source_url: str | None = None) -> str:
    did = new_id()
    with connect() as c:
        c.execute(
            "INSERT INTO documents (id,title,filename,status,source_url,created_at) VALUES (?,?,?,?,?,?)",
            (did, title, filename, "processing", source_url, now()),
        )
    return did


def update_document(did: str, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE documents SET {cols} WHERE id = ?", (*fields.values(), did))


def list_documents() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM documents ORDER BY created_at DESC")]


def get_document(did: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
        return dict(r) if r else None


def delete_document(did: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM documents WHERE id = ?", (did,)).rowcount > 0


def insert_chunks(did: str, chunks: list[dict], embeddings: list[list[float]]) -> None:
    with connect() as c:
        c.executemany(
            "INSERT INTO chunks (document_id, idx, page, text, embedding) VALUES (?,?,?,?,?)",
            [
                (did, i, ch["page"], ch["text"], np.asarray(emb, dtype=np.float32).tobytes())
                for i, (ch, emb) in enumerate(zip(chunks, embeddings, strict=True))
            ],
        )


def load_chunks(document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    with connect() as c:
        rows = c.execute(
            f"""SELECT c.document_id, c.idx, c.page, c.text, c.embedding, d.title
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.document_id IN ({','.join('?' * len(document_ids))})
                ORDER BY c.document_id, c.idx""",
            document_ids,
        ).fetchall()
    return [
        {
            "document_id": r["document_id"],
            "title": r["title"],
            "page": r["page"],
            "text": r["text"],
            "embedding": np.frombuffer(r["embedding"], dtype=np.float32),
        }
        for r in rows
    ]
