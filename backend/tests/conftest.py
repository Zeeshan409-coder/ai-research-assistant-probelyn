import hashlib
import os
import tempfile

import numpy as np
import pytest

os.environ["PROBELYN_DATA_DIR"] = tempfile.mkdtemp(prefix="probelyn-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.main import app  # noqa: E402


class FakeLLM:
    """Deterministic stand-in for Ollama so tests run offline and fast."""

    chat_model = "fake-model"

    def __init__(self):
        self.calls = []

    async def stream_chat(self, messages, model=None, temperature=None):
        self.calls.append(messages)
        system = messages[0]["content"]
        if "search queries" in system:
            text = "first alternative query\nsecond alternative query"
        else:
            text = "Solar panels convert sunlight into electricity [1]. Efficiency is improving [2]."
        for word in text.split(" "):
            yield word + " "

    async def chat(self, messages, model=None, temperature=None):
        return "".join([t async for t in self.stream_chat(messages, model, temperature)])

    async def embed(self, texts):
        # bag-of-words hashing embedding: similar texts -> similar vectors
        out = []
        for t in texts:
            v = np.zeros(64, dtype=np.float32)
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
            out.append(v.tolist())
        return out

    async def list_models(self):
        return ["llama3.2:latest", "nomic-embed-text:latest"]

    async def health(self):
        return True


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    db.init_db()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def parse_sse(text: str) -> list[tuple[str, str]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        ev = lines[0].removeprefix("event: ")
        data = lines[1].removeprefix("data: ")
        events.append((ev, data))
    return events
