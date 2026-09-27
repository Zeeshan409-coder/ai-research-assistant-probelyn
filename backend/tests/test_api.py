import asyncio
import json
import time

from fpdf import FPDF

from app.services import papers, web_search
from conftest import parse_sse


def make_pdf(pages: list[str]) -> bytes:
    pdf = FPDF()
    pdf.set_font("helvetica", size=11)
    for text in pages:
        pdf.add_page()
        pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


def wait_ready(client, doc_id, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] != "processing":
            return doc
        time.sleep(0.05)
    raise AssertionError("document never finished processing")


# ------------------------------------------------------------------ system
def test_health(client):
    r = client.get("/api/health").json()
    assert r["ollama"] is True
    assert r["chat_model_installed"] and r["embed_model_installed"]


# --------------------------------------------------------------- web flow
def test_web_research_stream(client, fake_llm, monkeypatch):
    async def fake_search(query, n):
        return [
            {"title": "Solar basics", "url": "https://example.com/solar", "snippet": "Solar panels make power."},
            {"title": "PV efficiency", "url": "https://example.org/pv", "snippet": "Efficiency keeps rising."},
            {"title": "Dup", "url": "https://example.com/solar/", "snippet": "duplicate"},
        ]

    async def fake_fetch(client_, url):
        return "Photovoltaic cells convert sunlight directly into electricity. " * 20

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr(web_search, "fetch_page", fake_fetch)

    r = client.post("/api/research/web", json={"question": "How do solar panels work?", "depth": "standard"})
    assert r.status_code == 200
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert kinds[0] == "entry" and kinds[1] == "status" and kinds[-1] == "done"
    assert "_store_sources" not in kinds  # internal events never reach the browser
    queries = json.loads(next(d for e, d in events if e == "queries"))
    assert queries[0] == "How do solar panels work?" and len(queries) == 2
    sources = json.loads(next(d for e, d in events if e == "sources"))
    assert len(sources) == 2  # duplicate URL removed
    answer = "".join(json.loads(d) for e, d in events if e == "token")
    assert "[1]" in answer
    # source excerpts were passed to the model
    assert "Photovoltaic" in fake_llm.calls[-1][-1]["content"]

    entry_id = json.loads(events[-1][1])["entry_id"]
    entry = client.get(f"/api/history/{entry_id}").json()
    assert entry["kind"] == "web" and entry["sources"][0]["url"] == "https://example.com/solar"


def test_answer_saved_even_if_client_leaves(client, fake_llm, monkeypatch):
    """User clicks 'New research' mid-answer: the run must still finish and be saved."""
    import time

    async def fake_search(query, n):
        return [{"title": "A", "url": "https://example.com/a", "snippet": "text"}]

    async def fake_fetch(c, url):
        return "content " * 50

    async def slow_stream(messages, model=None, temperature=None):
        for word in ["Slow ", "answer ", "[1] ", "finished."]:
            await asyncio.sleep(0.05)
            yield word

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr(web_search, "fetch_page", fake_fetch)
    monkeypatch.setattr(fake_llm, "stream_chat", slow_stream)

    with client.stream("POST", "/api/research/web", json={"question": "Leave early?", "depth": "quick"}) as r:
        first = next(r.iter_lines())  # read only the first event, then disconnect
        assert first == "event: entry"

    for _ in range(100):
        entry = next((e for e in client.get("/api/history").json() if e["question"] == "Leave early?"), None)
        if entry and entry["status"] == "done":
            break
        time.sleep(0.05)
    assert entry["status"] == "done"
    assert entry["answer"] == "Slow answer [1] finished."
    assert entry["sources"][0]["url"] == "https://example.com/a"


def test_web_research_no_results(client, monkeypatch):
    async def empty(q, n):
        return []

    monkeypatch.setattr(web_search, "search", empty)
    events = parse_sse(client.post("/api/research/web", json={"question": "zzzz qqq", "depth": "quick"}).text)
    assert events[-1][0] == "error"


def test_extract_text_strips_boilerplate():
    html = """<html><head><title> My Page </title><script>var x=1</script></head>
    <body><nav>Home | About | Contact us today please</nav>
    <article><h1>Big headline for the article here</h1>
    <p>This is the main paragraph with enough words to count as content.</p></article>
    <footer>Copyright footer text that is long enough</footer></body></html>"""
    title, text = web_search.extract_text(html)
    assert title == "My Page"
    assert "main paragraph" in text and "Copyright" not in text and "var x" not in text


# ------------------------------------------------------------------ papers
ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All
      You Need</title>
    <summary>The dominant sequence transduction models are based on complex recurrent networks.</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.CL"/>
  </entry>
</feed>"""


def test_parse_arxiv():
    [p] = papers.parse_arxiv(ARXIV_XML)
    assert p["title"] == "Attention Is All You Need"
    assert p["year"] == 2017 and p["authors"][0] == "Ashish Vaswani"
    assert p["pdf_url"].endswith("1706.03762v7") and "cs.CL" in p["venue"]


def test_merge_papers_dedupes_and_fills_fields():
    a = papers.parse_arxiv(ARXIV_XML)
    s2 = papers.parse_s2(
        {"data": [
            {"paperId": "x", "title": "Attention is all you need", "abstract": None,
             "authors": [{"name": "A. Vaswani"}], "year": 2017, "venue": "NeurIPS", "citationCount": 100000, "url": "https://s2/x"},
            {"paperId": "y", "title": "BERT", "abstract": "Bidirectional transformers.", "authors": [],
             "year": 2018, "citationCount": 50000, "externalIds": {"ArXiv": "1810.04805"}},
        ]}
    )
    merged = papers.merge_papers([a, s2], limit=10)
    assert len(merged) == 2
    attn = next(p for p in merged if p["title"].startswith("Attention"))
    assert attn["citations"] == 100000 and "Semantic Scholar" in attn["source"]
    bert = next(p for p in merged if p["title"] == "BERT")
    assert bert["pdf_url"] == "https://arxiv.org/pdf/1810.04805"
    assert papers.sort_papers(merged, "recent")[0]["title"] == "BERT"


def test_paper_research_stream(client, monkeypatch):
    async def fake_search(query, limit, sources, year_from, sort):
        return papers.parse_arxiv(ARXIV_XML), ["Semantic Scholar unavailable: 429"]

    monkeypatch.setattr(papers, "search_papers", fake_search)
    events = parse_sse(client.post("/api/papers/research", json={"query": "transformers"}).text)
    kinds = [e for e, _ in events]
    assert "warning" in kinds and "papers" in kinds and kinds[-1] == "done"


# --------------------------------------------------------------- documents
def test_document_upload_and_ask(client):
    pdf = make_pdf([
        "Chapter one. The mitochondria is the powerhouse of the cell and produces ATP energy.",
        "Chapter two. Chloroplasts perform photosynthesis in plant cells using sunlight.",
    ])
    r = client.post("/api/documents", files={"file": ("biology.pdf", pdf, "application/pdf")})
    assert r.status_code == 202
    doc = wait_ready(client, r.json()["id"])
    assert doc["status"] == "ready" and doc["pages"] == 2 and doc["chunks"] >= 2

    r = client.post(
        "/api/documents/ask",
        json={"question": "What do chloroplasts do with sunlight?", "document_ids": [doc["id"]]},
    )
    events = parse_sse(r.text)
    sources = json.loads(next(d for e, d in events if e == "sources"))
    assert sources[0]["page"] == 2  # hybrid retrieval found the right page
    assert events[-1][0] == "done"


def test_upload_rejects_bad_type(client):
    r = client.post("/api/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415


def test_text_upload_and_delete(client):
    note = ("notes.md", b"# Notes\nSome research notes here.", "text/markdown")
    r = client.post("/api/documents", files={"file": note})
    doc = wait_ready(client, r.json()["id"])
    assert doc["status"] == "ready"
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404


def test_ask_requires_ready_document(client):
    r = client.post("/api/documents/ask", json={"question": "hello?", "document_ids": ["nope"]})
    assert r.status_code == 400


# ------------------------------------------------------------------ export
def test_export_markdown_and_pdf(client, monkeypatch):
    async def fake_search(q, n):
        return [{"title": "Ünïcode — source “quotes”", "url": "https://example.com/a", "snippet": "text"}]

    async def fake_fetch(c, url):
        return "Some content " * 10

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr(web_search, "fetch_page", fake_fetch)
    events = parse_sse(client.post("/api/research/web", json={"question": "Export test?", "depth": "quick"}).text)
    eid = json.loads(events[-1][1])["entry_id"]

    r = client.post("/api/export", json={"entry_ids": [eid], "format": "md"})
    assert r.status_code == 200 and "# Export test?" in r.text and "### Sources" in r.text
    assert "https://example.com/a" in r.text

    r = client.post("/api/export", json={"entry_ids": [eid], "format": "pdf", "title": "My Report"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert "my-report.pdf" in r.headers["content-disposition"]

    assert client.delete(f"/api/history/{eid}").status_code == 204
    assert client.post("/api/export", json={"entry_ids": [eid]}).status_code == 404


def test_bulk_delete_and_clear_history(client):
    from app import db

    ids = [db.save_entry("web", f"q{i}", "a", [], None) for i in range(4)]
    r = client.post("/api/history/delete", json={"entry_ids": ids[:2] + ["missing"]})
    assert r.json() == {"deleted": 2}
    remaining = {e["id"] for e in client.get("/api/history").json()}
    assert not remaining & set(ids[:2]) and set(ids[2:]) <= remaining

    assert client.delete("/api/history").status_code == 400  # safety catch
    assert client.delete("/api/history?confirm=true").json()["deleted"] >= 2
    assert client.get("/api/history").json() == []


def test_deleting_running_entry_is_safe(client):
    """Deleting an entry while it's still being written must not crash or resurrect it."""
    from app import db

    rec = db.EntryRecorder("web", "being written", None)
    client.delete(f"/api/history/{rec.id}")
    rec.token("late tokens")
    rec.finish()
    assert all(e["id"] != rec.id for e in client.get("/api/history").json())


async def test_stop_button_halts_generation(client, fake_llm, monkeypatch):
    """Pressing Stop must cancel the model mid-answer and keep the partial text."""
    from app import db, sse

    async def fake_search(query, n):
        return [{"title": "A", "url": "https://example.com/a", "snippet": "text"}]

    async def fake_fetch(c, url):
        return "content " * 50

    produced = []

    async def endless(messages, model=None, temperature=None):
        for i in range(1000):  # would take 20 s if not stopped
            await asyncio.sleep(0.02)
            produced.append(i)
            yield f"w{i} "

    monkeypatch.setattr(web_search, "search", fake_search)
    monkeypatch.setattr(web_search, "fetch_page", fake_fetch)
    monkeypatch.setattr(fake_llm, "stream_chat", endless)

    queue = sse.run_detached(web_search.run_web_research(fake_llm, "Stop me", "quick"))
    events, entry_id, tokens = [], None, 0
    while True:
        ev = await asyncio.wait_for(queue.get(), timeout=5)
        if ev is sse._DONE:
            break
        events.append(ev["event"])
        if ev["event"] == "entry":
            entry_id = ev["data"]["entry_id"]
        if ev["event"] == "token":
            tokens += 1
            if tokens == 5:
                assert sse.stop_run(entry_id) is True

    assert events[-1] == "stopped"
    assert len(produced) < 20  # generation really halted
    [entry] = db.get_entries([entry_id])
    assert entry["status"] == "stopped"
    assert entry["answer"].startswith("w0 w1") and "Stopped by user" in entry["answer"]
    # stopping a finished run is a harmless no-op
    assert client.post(f"/api/runs/{entry_id}/stop").json() == {"stopped": False}
