"""Review service — queue management, status updates, bulk actions, dedupe."""

from __future__ import annotations

import os
from typing import Any

from ..storage import Storage


def _get_storage() -> Storage:
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def get_queue(
    min_score: int = 0,
    max_score: int | None = None,
    decision: str | None = None,
    decisions: list[str] | None = None,
    preset: str | None = None,
    status: str | None = None,
    limit: int = 20,
    remote_only: bool = False,
    with_salary: bool = False,
    hide_risk: bool = False,
    new_only: bool = False,
    dedupe: bool = False,
) -> list[dict[str, Any]]:
    """Return review queue with filters and optional deduplication."""
    storage = _get_storage()
    rows = storage.list_queue(
        min_score=min_score,
        max_score=max_score,
        decision=decision,
        decisions=decisions,
        preset=preset,
        status=status,
        limit=limit,
        remote_only=remote_only,
        with_salary=with_salary,
        hide_risk=hide_risk,
        new_only=new_only,
    )
    if dedupe and rows:
        rows = _dedupe_queue(storage, rows)
    return rows


def _dedupe_queue(storage: Storage, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter rows keeping only the best vacancy per cluster."""
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    cluster_map = storage.get_clusters_for_vacancies(ids)

    clustered: dict[str, list[dict[str, Any]]] = {}
    unclustered: list[dict[str, Any]] = []
    for row in rows:
        cinfo = cluster_map.get(row["id"])
        if cinfo:
            clustered.setdefault(cinfo["cluster_id"], []).append(row)
        else:
            unclustered.append(row)

    result: list[dict[str, Any]] = []
    for _cid, members in clustered.items():
        best = max(
            members,
            key=lambda r: (r.get("total_score", 0), r.get("published_at", "")),
        )
        best["_cluster_id"] = _cid
        best["_cluster_size"] = len(members)
        result.append(best)

    result.extend(unclustered)
    result.sort(key=lambda r: r.get("total_score", 0), reverse=True)
    return result


def set_status(vacancy_id: str, status: str) -> dict[str, Any]:
    """Update review status for a vacancy."""
    storage = _get_storage()
    return storage.set_review_status(vacancy_id, status)


def set_note(vacancy_id: str, note: str) -> dict[str, Any]:
    """Set a note on a vacancy."""
    storage = _get_storage()
    return storage.set_review_note(vacancy_id, note)


def mark_applied(vacancy_id: str, applied_at: str) -> dict[str, Any]:
    """Mark vacancy as applied."""
    storage = _get_storage()
    return storage.mark_applied(vacancy_id, applied_at)


def set_next_action(vacancy_id: str, action: str, next_action_at: str) -> dict[str, Any]:
    """Set next action for a vacancy."""
    storage = _get_storage()
    return storage.set_next_action(vacancy_id, action, next_action_at)


def get_vacancy_full(vacancy_id: str) -> dict[str, Any] | None:
    """Return full vacancy data including description, score, review."""
    storage = _get_storage()
    return storage.get_vacancy_full(vacancy_id)


def bulk_archive_auto_hide(force: bool = False) -> dict[str, Any]:
    """Archive all auto_hide vacancies."""
    storage = _get_storage()
    result = storage.bulk_update_review_status(
        new_status="archived",
        force=force,
        decision="auto_hide",
    )
    return {
        "matched_count": result["matched_count"],
        "updated_count": result["updated_count"],
        "skipped_protected_count": result["skipped_protected_count"],
    }


def bulk_reject_low_score(max_score: int = 35, force: bool = False) -> dict[str, Any]:
    """Reject all vacancies with score <= max_score."""
    storage = _get_storage()
    result = storage.bulk_update_review_status(
        new_status="rejected",
        force=force,
        max_score=max_score,
    )
    return {
        "matched_count": result["matched_count"],
        "updated_count": result["updated_count"],
        "skipped_protected_count": result["skipped_protected_count"],
    }


def bulk_mark_interesting(
    min_score: int = 85,
    decision: str = "strong_match",
    force: bool = False,
) -> dict[str, Any]:
    """Mark strong matches as interesting."""
    storage = _get_storage()
    result = storage.bulk_update_review_status(
        new_status="interesting",
        force=force,
        min_score=min_score,
        decision=decision,
    )
    return {
        "matched_count": result["matched_count"],
        "updated_count": result["updated_count"],
        "skipped_protected_count": result["skipped_protected_count"],
    }


def get_queue_count(filters: dict[str, Any]) -> int:
    """Count matching queue items for bulk action preview."""
    storage = _get_storage()
    rows = storage.list_queue(**{**filters, "limit": 10000})
    return len(rows)


def generate_apply_pack_for(vacancy_id: str) -> dict[str, Any]:
    """Generate apply pack for a single vacancy, save draft to review."""
    import argparse

    from ..commands.apply_pack import command_apply_pack, prepare_apply_pack_preview

    storage = _get_storage()
    preview = prepare_apply_pack_preview(storage, vacancy_id, lang="ru", style="medium")
    if not preview["ok"]:
        return preview

    pack_args = argparse.Namespace(
        vacancy_id=vacancy_id,
        top=None,
        limit=None,
        decision=None,
        preset=None,
        min_score=0,
        lang="ru",
        format="both",
        style="medium",
        template=None,
        save_review=True,
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
        return {"ok": False, "message": f"Apply pack failed: {exc}", "data": preview.get("data")}


def generate_briefing_for(vacancy_id: str) -> dict[str, Any]:
    """Generate briefing for a single vacancy and save it to review storage."""
    import argparse

    from ..commands.briefing import command_briefing

    storage = _get_storage()
    vacancy = storage.get_vacancy_full(vacancy_id)
    if vacancy is None:
        return {
            "ok": False,
            "message": f"Vacancy not found: {vacancy_id}",
            "error_type": "not_found",
            "data": None,
        }

    briefing_args = argparse.Namespace(
        vacancy_id=vacancy_id,
        top=None,
        limit=None,
        min_score=0,
        decision=None,
        preset=None,
        status=None,
        remote_only=False,
        with_salary=False,
        hide_risk=False,
        new_only=False,
        lang="ru",
        format="all",
        save_review=True,
    )
    try:
        rc = command_briefing(briefing_args)
        if rc != 0:
            return {
                "ok": False,
                "message": f"Briefing failed for {vacancy_id}",
                "error_type": "generation_failed",
                "data": None,
            }

        report = storage.get_briefing_report(vacancy_id, lang="ru")
        return {
            "ok": True,
            "message": f"Briefing generated for {vacancy_id}",
            "data": {
                "vacancy_id": vacancy_id,
                "lang": "ru",
                "decision": report.get("decision") if report else None,
                "score_total": report.get("score_total") if report else None,
                "updated_at": report.get("updated_at") if report else None,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Briefing failed: {exc}",
            "error_type": "generation_failed",
            "data": None,
        }
