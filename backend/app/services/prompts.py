"""Prompt templates. Kept in one place so they are easy to tune."""

from datetime import date

CITATION_RULES = """Rules:
- Use ONLY the numbered sources below. If they don't contain the answer, say so plainly.
- Cite every factual claim with the source number in square brackets, e.g. [1] or [2][4].
- Never invent sources, numbers, quotes, authors or URLs.
- Write in clear Markdown: a short direct answer first, then details with headings or bullets where useful.
- Do NOT add a references/sources list at the end; the app renders it."""


def query_planner(question: str, n: int) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You turn a research question into web search queries. "
                f"Return exactly {n} short, diverse search queries, one per line, no numbering, no quotes, "
                "no extra text."
            ),
        },
        {"role": "user", "content": f"Today is {date.today().isoformat()}.\nQuestion: {question}"},
    ]


def web_answer(question: str, sources_block: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are Probelyn, a careful research assistant. You write accurate, well-structured, "
                "cited answers from web sources.\n" + CITATION_RULES
            ),
        },
        {
            "role": "user",
            "content": f"Today is {date.today().isoformat()}.\n\nSOURCES:\n{sources_block}\n\nQUESTION: {question}",
        },
    ]


def literature_review(topic: str, papers_block: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are Probelyn, an academic research assistant. From the paper abstracts provided, write a "
                "concise literature overview: (1) the main research directions, (2) key findings and methods, "
                "(3) open problems / gaps, (4) which papers to read first and why.\n" + CITATION_RULES
            ),
        },
        {"role": "user", "content": f"PAPERS:\n{papers_block}\n\nTOPIC: {topic}"},
    ]


def paper_summary(title: str, abstract: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Summarize the research paper for a busy graduate student using this Markdown structure:\n"
                "**TL;DR** – one sentence.\n\n**Problem** – ...\n\n**Method** – ...\n\n**Key results** – bullets\n\n"
                "**Limitations** – ...\n\nBase everything strictly on the abstract; if something isn't stated, "
                "write 'Not stated in abstract'."
            ),
        },
        {"role": "user", "content": f"Title: {title}\n\nAbstract: {abstract}"},
    ]


def document_answer(question: str, context_block: str, history: list[dict]) -> list[dict]:
    msgs = [
        {
            "role": "system",
            "content": (
                "You are Probelyn, answering questions about the user's uploaded documents. "
                "Each excerpt is numbered and labelled with its document and page.\n" + CITATION_RULES
            ),
        }
    ]
    msgs.extend(history[-6:])  # short conversational memory
    msgs.append({"role": "user", "content": f"EXCERPTS:\n{context_block}\n\nQUESTION: {question}"})
    return msgs
