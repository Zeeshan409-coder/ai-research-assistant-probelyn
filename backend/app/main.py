"""Probelyn – local-first AI research assistant (FastAPI + Ollama)."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import get_settings
from .routers import api

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Built frontend (npm run build) – served by FastAPI in production / Docker.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Probelyn API",
        description="Local-first AI research assistant: web research, paper search and document Q&A powered by Ollama.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"]
    )
    app.include_router(api)

    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            file = FRONTEND_DIST / path
            if path and file.is_file() and FRONTEND_DIST in file.resolve().parents:
                return FileResponse(file)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
