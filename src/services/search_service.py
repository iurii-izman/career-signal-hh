"""Search service — dry-run, autopilot, smoke/normal search operations."""

from __future__ import annotations

import argparse
from typing import Any


def dry_run_search(mode: str = "normal", preset: str | None = None) -> dict[str, Any]:
    """Perform a search dry-run and return estimate."""
    from ..commands.search import command_search

    search_args = argparse.Namespace(
        mode=mode,
        max_pages=None,
        per_page=None,
        profile=None,
        preset=preset,
        adhoc=False,
        include=None,
        exclude=None,
        remote_only=None,
        dry_run=True,
        force_details=False,
        verbose=False,
        yes=False,
    )
    try:
        rc = command_search(search_args)
        return {"ok": rc == 0, "message": "Dry-run complete. No API requests made."}
    except Exception as exc:
        return {"ok": False, "message": f"Dry-run failed: {exc}"}


def run_autopilot_daily(
    mode: str = "normal",
    preset: str | None = None,
    backup_first: bool = True,
) -> dict[str, Any]:
    """Run daily autopilot pipeline."""
    from ..commands.autopilot import command_autopilot_daily

    autopilot_args = argparse.Namespace(
        mode=mode,
        preset=preset,
        skip_auth_check=False,
        skip_search=False,
        skip_rescore=False,
        skip_export=False,
        skip_queue=False,
        queue_limit=20,
        min_score=70,
        backup_first=backup_first,
        allow_deep=False,
        ignore_doctor_warnings=False,
        yes=False,
    )
    try:
        rc = command_autopilot_daily(autopilot_args)
        return {
            "ok": rc == 0,
            "message": "Autopilot completed" if rc == 0 else "Autopilot completed with warnings",
        }
    except Exception as exc:
        return {"ok": False, "message": f"Autopilot failed: {exc}"}


def run_search_smoke(preset: str | None = None) -> dict[str, Any]:
    """Run smoke search (1 page, 10 per page)."""
    from ..commands.search import command_search

    search_args = argparse.Namespace(
        mode="smoke",
        max_pages=None,
        per_page=None,
        profile=None,
        preset=preset,
        adhoc=False,
        include=None,
        exclude=None,
        remote_only=None,
        dry_run=False,
        force_details=False,
        verbose=False,
        yes=True,
    )
    try:
        rc = command_search(search_args)
        return {"ok": rc == 0, "message": "Smoke search completed"}
    except Exception as exc:
        return {"ok": False, "message": f"Smoke search failed: {exc}"}


def run_search_normal(preset: str | None = None) -> dict[str, Any]:
    """Run normal search."""
    from ..commands.search import command_search

    search_args = argparse.Namespace(
        mode="normal",
        max_pages=None,
        per_page=None,
        profile=None,
        preset=preset,
        adhoc=False,
        include=None,
        exclude=None,
        remote_only=None,
        dry_run=False,
        force_details=False,
        verbose=False,
        yes=True,
    )
    try:
        rc = command_search(search_args)
        return {"ok": rc == 0, "message": "Normal search completed"}
    except Exception as exc:
        return {"ok": False, "message": f"Normal search failed: {exc}"}
