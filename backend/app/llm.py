"""Thin async client for the local Ollama HTTP API.

Only three endpoints are needed:
  * POST /api/chat   – streaming chat completions (NDJSON)
  * POST /api/embed  – batch embeddings
  * GET  /api/tags   – list locally installed models
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from .config import get_settings


class LLMError(RuntimeError):
    """Raised when the model backend is unreachable or returns an error."""


class LLM(Protocol):
    async def stream_chat(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None
    ) -> AsyncIterator[str]: ...

    async def chat(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None
    ) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def list_models(self) -> list[str]: ...

    async def health(self) -> bool: ...


class OllamaClient:
    def __init__(self, base_url: str | None = None, chat_model: str | None = None, embed_model: str | None = None):
        s = get_settings()
        self.base_url = (base_url or s.ollama_url).rstrip("/")
        self.chat_model = chat_model or s.chat_model
        self.embed_model = embed_model or s.embed_model
        self.temperature = s.temperature
        self.timeout = httpx.Timeout(s.llm_timeout, connect=5.0)

    # ------------------------------------------------------------------ chat
    async def stream_chat(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None
    ) -> AsyncIterator[str]:
        payload = {
            "model": model or self.chat_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.temperature if temperature is None else temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode(errors="ignore")
                        raise LLMError(_friendly_error(resp.status_code, body, payload["model"]))
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise LLMError(data["error"])
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
                        if data.get("done"):
                            break
        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.base_url}. Is it running? (start it with `ollama serve`)"
            ) from e

    async def chat(
        self, messages: list[dict], model: str | None = None, temperature: float | None = None
    ) -> str:
        parts = [c async for c in self.stream_chat(messages, model=model, temperature=temperature)]
        return "".join(parts)

    # ------------------------------------------------------------ embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for i in range(0, len(texts), 32):  # batch to keep requests small
                    batch = texts[i : i + 32]
                    resp = await client.post(
                        f"{self.base_url}/api/embed", json={"model": self.embed_model, "input": batch}
                    )
                    if resp.status_code != 200:
                        raise LLMError(_friendly_error(resp.status_code, resp.text, self.embed_model))
                    out.extend(resp.json()["embeddings"])
        except httpx.ConnectError as e:
            raise LLMError(f"Cannot reach Ollama at {self.base_url}.") from e
        return out

    # ----------------------------------------------------------------- misc
    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                resp.raise_for_status()
                return sorted(m["name"] for m in resp.json().get("models", []))
        except httpx.HTTPError:
            return []

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                return (await client.get(f"{self.base_url}/api/tags")).status_code == 200
        except httpx.HTTPError:
            return False


def _friendly_error(status: int, body: str, model: str) -> str:
    if status == 404 or "not found" in body.lower():
        return f"Model '{model}' is not installed. Run: ollama pull {model}"
    return f"Ollama error {status}: {body[:300]}"


_client: OllamaClient | None = None


def get_llm() -> LLM:
    """FastAPI dependency (overridden in tests with a fake)."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
