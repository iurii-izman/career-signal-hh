"""Apply pack service — generate cover letter packs."""

from __future__ import annotations

import argparse
from typing import Any


def generate_apply_pack(
    vacancy_id: str,
    lang: str = "ru",
    style: str = "medium",
    save_review: bool = False,
) -> dict[str, Any]:
    """Generate apply pack for a single vacancy."""
    from ..commands.apply_pack import command_apply_pack, prepare_apply_pack_preview
    from ..services.review_service import _get_storage

    preview = prepare_apply_pack_preview(_get_storage(), vacancy_id, lang=lang, style=style)
    if not preview["ok"]:
        return preview

    pack_args = argparse.Namespace(
        vacancy_id=vacancy_id,
        top=None,
        limit=None,
        decision=None,
        preset=None,
        min_score=0,
        lang=lang,
        format="both",
        style=style,
        template=None,
        save_review=save_review,
        overwrite=False,
        diagnostics=False,
    )
    try:
        rc = command_apply_pack(pack_args)
        preview["ok"] = rc == 0
        preview["message"] = (
            f"Apply pack generated for {vacancy_id}"
            if rc == 0
            else f"Apply pack failed for {vacancy_id}"
        )
        return preview
    except Exception as exc:
        return {"ok": False, "message": f"Apply pack failed: {exc}"}


def generate_top_apply_packs(
    limit: int = 5,
    decision: str = "strong_match",
) -> dict[str, Any]:
    """Generate apply packs for top-matching vacancies."""
    from ..commands.apply_pack import command_apply_pack

    pack_args = argparse.Namespace(
        vacancy_id=None,
        top=limit,
        limit=None,
        decision=decision,
        preset=None,
        min_score=0,
        lang="ru",
        format="both",
        style="medium",
        template=None,
        save_review=True,
        overwrite=False,
    )
    try:
        rc = command_apply_pack(pack_args)
        return {"ok": rc == 0, "message": f"Top {limit} apply packs generated"}
    except Exception as exc:
        return {"ok": False, "message": f"Top apply packs failed: {exc}"}
