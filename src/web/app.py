"""Web application — FastAPI app factory with static files and templates."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import router

_static_dir = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CareerSignal HH",
        version="0.7.0",
        docs_url=None,  # Disable OpenAPI docs for now
        redoc_url=None,
    )

    # Mount static files
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    # Include routes
    app.include_router(router)

    return app
