"""Application settings, loaded from environment variables or a .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PROBELYN_", extra="ignore")

    # --- Ollama ---
    ollama_url: str = "http://localhost:11434"
    chat_model: str = "llama3.2"
    embed_model: str = "nomic-embed-text"
    temperature: float = 0.2
    llm_timeout: float = 300.0

    # --- Storage ---
    data_dir: Path = Path("data")

    # --- Web research ---
    web_results_per_query: int = 5
    fetch_timeout: float = 12.0
    max_chars_per_source: int = 2500
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Probelyn/1.0"
    )

    # --- Document RAG ---
    chunk_size: int = 1000
    chunk_overlap: int = 200
    top_k: int = 6
    max_upload_mb: int = 25

    # --- Papers ---
    semantic_scholar_api_key: str | None = None

    # --- Server ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "probelyn.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
