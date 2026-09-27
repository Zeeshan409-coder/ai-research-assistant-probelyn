"""A tiny fake Ollama server for UI development and demos on machines without a GPU.

    python scripts/mock_ollama.py          # listens on :11434

It implements /api/tags, /api/chat (streaming) and /api/embed with canned,
deterministic output. Do not use it for real research – answers are fake.
"""

import asyncio
import hashlib
import json
import os
import re

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
DELAY = float(os.environ.get("MOCK_DELAY", "0.02"))  # seconds per token

CANNED = """**Short answer:** the sources agree on the core idea, with some differences in emphasis [1][2].

### Key points
- The first source gives a clear overview of the fundamentals and the main mechanism involved [1].
- Recent work reports measurable improvements, although results depend on the setup [2][3].
- Several sources note open challenges around cost, scalability and evaluation [3].

### Details
Taken together, the evidence suggests steady progress rather than a single breakthrough [1][3]. \
Where the sources disagree, it is mostly about *how fast* adoption will happen, not the direction [2].

> Note: this is output from the **mock** Ollama server – install Ollama for real answers."""


@app.get("/api/tags")
async def tags():
    return {"models": [{"name": "llama3.2:latest"}, {"name": "nomic-embed-text:latest"}, {"name": "qwen2.5:7b"}]}


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    system = body["messages"][0]["content"]
    user = body["messages"][-1]["content"]
    if "search queries" in system:
        q = user.split("Question:")[-1].strip()
        text = f"{q} latest research\n{q} explained"
    elif "Summarize the research paper" in system:
        text = ("**TL;DR** – The paper proposes a new method and shows it beats strong baselines.\n\n"
                "**Problem** – Existing approaches are slow or inaccurate.\n\n**Method** – A new architecture.\n\n"
                "**Key results**\n- Better accuracy on standard benchmarks\n- Lower compute cost\n\n"
                "**Limitations** – Not stated in abstract.")
    else:
        n = len(set(re.findall(r"^\[(\d+)\]", user, flags=re.M))) or 3
        text = CANNED if n >= 3 else re.sub(r"\[3\]", "[1]", CANNED)

    async def gen():
        for tok in re.findall(r"\S+\s*|\n", text):
            yield json.dumps({"message": {"role": "assistant", "content": tok}, "done": False}) + "\n"
            await asyncio.sleep(DELAY)
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/embed")
async def embed(req: Request):
    body = await req.json()
    inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
    out = []
    for t in inputs:
        v = [0.0] * 128
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 128] += 1.0
        out.append(v)
    return {"model": body.get("model"), "embeddings": out}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=11434)
