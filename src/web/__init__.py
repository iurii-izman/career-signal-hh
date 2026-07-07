"""Web package — local UI server."""

from __future__ import annotations

from typing import Any

__all__ = ["create_app"]


def create_app(*args: Any, **kwargs: Any):
    """Lazily import the FastAPI app factory.

    This keeps lightweight modules such as ``src.web.jobs`` importable even when
    optional web dependencies are not installed in the environment.
    """
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)
