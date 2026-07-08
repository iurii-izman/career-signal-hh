"""Controlled apply assist service.

Separates preview/draft generation from the explicit operator handoff step.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from ..briefing_core import briefing_output_paths
from ..commands.apply_pack import prepare_apply_pack_preview
from ..storage import Storage

MIN_ASSIST_SCORE = 85
MIN_ASSIST_CONFIDENCE = 60
MAX_ASSIST_NOISE = 35
REQUIRED_REVIEW_STATUS = "interesting"

HARD_RED_FLAGS = {
    "title": [
        "sales manager",
        "менеджер по продажам",
        "account manager",
        "support specialist",
        "специалист поддержки",
        "call center",
        "оператор",
        "ml engineer",
        "data scientist",
        "qa automation",
        "php developer",
    ],
    "description": [
        "холодные звонки",
        "обзвон",
        "работа в офисе без удаленного формата",
        "командировки обязательны",
        "график 6/1",
        "unpaid internship",
        "стажировка без оплаты",
        "casino",
        "gambling",
    ],
}


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _hard_red_flag_hits(vacancy: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    title = _normalize_text(vacancy.get("name"))
    description = _normalize_text(vacancy.get("description_text"))
    for phrase in HARD_RED_FLAGS["title"]:
        if phrase in title:
            hits.append(f"title:{phrase}")
    for phrase in HARD_RED_FLAGS["description"]:
        if phrase in description:
            hits.append(f"description:{phrase}")
    return hits


def _apply_pack_paths(vacancy: dict[str, Any]) -> dict[str, str | None]:
    from ..commands.apply_pack import _slug

    out_dir = Path("exports/apply_packs")
    slug = _slug(vacancy.get("name", "vacancy"))
    stem = f"{vacancy.get('id', '')}_{slug}"
    md = out_dir / f"{stem}.md"
    html = out_dir / f"{stem}.html"
    return {
        "md": str(md.resolve()) if md.exists() else None,
        "html": str(html.resolve()) if html.exists() else None,
    }


def _briefing_paths(vacancy: dict[str, Any]) -> dict[str, str | None]:
    paths = briefing_output_paths(vacancy, Path("exports/briefings"))
    return {
        key: str(path.resolve()) if path.exists() else None
        for key, path in paths.items()
    }


def _gate(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def prepare_apply_assist(storage: Storage, vacancy_id: str) -> dict[str, Any]:
    vacancy = storage.get_vacancy_full(vacancy_id)
    if vacancy is None:
        return {
            "ok": False,
            "message": f"Vacancy not found: {vacancy_id}",
            "error_type": "not_found",
            "data": None,
        }

    details = storage.get_score_details(vacancy_id) or {}
    review = storage.get_review(vacancy_id)
    briefing = storage.get_briefing_report(vacancy_id, lang="ru")
    preview = prepare_apply_pack_preview(storage, vacancy_id, lang="ru", style="medium")
    hard_red_flags = _hard_red_flag_hits(vacancy)

    total_score = int(details.get("total_score") or vacancy.get("total_score") or 0)
    confidence = int(details.get("confidence_score") or 0)
    noise = int(details.get("noise_score") or 0)
    review_status = str(review.get("status") or "new")
    letter_validation = ((preview.get("data") or {}).get("letter_validation")) or {
        "ok": False,
        "reasons": ["preview_unavailable"],
        "metrics": {},
    }

    gates = [
        _gate(
            "score_threshold",
            total_score >= MIN_ASSIST_SCORE,
            f"score={total_score}, required>={MIN_ASSIST_SCORE}",
        ),
        _gate(
            "confidence_threshold",
            confidence >= MIN_ASSIST_CONFIDENCE,
            f"confidence={confidence}, required>={MIN_ASSIST_CONFIDENCE}",
        ),
        _gate(
            "noise_threshold",
            noise <= MAX_ASSIST_NOISE,
            f"noise={noise}, required<={MAX_ASSIST_NOISE}",
        ),
        _gate(
            "review_status",
            review_status == REQUIRED_REVIEW_STATUS,
            f"review_status={review_status}, required={REQUIRED_REVIEW_STATUS}",
        ),
        _gate(
            "not_already_applied",
            review_status != "applied",
            f"review_status={review_status}",
        ),
        _gate(
            "briefing_saved",
            briefing is not None,
            "briefing report must exist in DB",
        ),
        _gate(
            "draft_saved",
            bool(review.get("cover_letter_draft")),
            "apply-pack draft must be saved in review",
        ),
        _gate(
            "letter_validated",
            bool(letter_validation.get("ok")),
            "validator=" + (
                "ok"
                if letter_validation.get("ok")
                else ",".join(letter_validation.get("reasons", [])) or "failed"
            ),
        ),
        _gate(
            "hard_red_flags",
            not hard_red_flags,
            "hits=" + (", ".join(hard_red_flags) if hard_red_flags else "none"),
        ),
        _gate(
            "vacancy_url",
            bool(vacancy.get("alternate_url")),
            "alternate_url required for browser handoff",
        ),
    ]

    failed = [gate["name"] for gate in gates if not gate["ok"]]
    ready = len(failed) == 0
    return {
        "ok": ready,
        "message": (
            f"Apply assist ready for {vacancy_id}"
            if ready
            else f"Apply assist blocked for {vacancy_id}"
        ),
        "error_type": None if ready else "gates",
        "data": {
            "vacancy_id": vacancy_id,
            "vacancy": {
                "id": vacancy.get("id"),
                "name": vacancy.get("name"),
                "employer_name": vacancy.get("employer_name"),
                "alternate_url": vacancy.get("alternate_url"),
            },
            "score": {
                "total_score": total_score,
                "confidence_score": confidence,
                "noise_score": noise,
                "decision": details.get("decision") or vacancy.get("decision"),
            },
            "review": {
                "status": review_status,
                "applied_at": review.get("applied_at"),
                "updated_at": review.get("updated_at"),
            },
            "briefing": {
                "lang": briefing.get("lang"),
                "decision": briefing.get("decision"),
                "score_total": briefing.get("score_total"),
                "updated_at": briefing.get("updated_at"),
            }
            if briefing
            else None,
            "gates": gates,
            "failed_gates": failed,
            "letter_validation": letter_validation,
            "hard_red_flags": hard_red_flags,
            "artifacts": {
                "briefing": _briefing_paths(vacancy),
                "apply_pack": _apply_pack_paths(vacancy),
            },
            "next_commands": {
                "mark_applied": f"python -m src.main review apply {vacancy_id} --date today",
                "show_draft": f"python -m src.main review draft {vacancy_id}",
            },
        },
    }


def execute_apply_assist(
    storage: Storage,
    vacancy_id: str,
    *,
    approve: bool,
    open_browser: bool,
) -> dict[str, Any]:
    preview = prepare_apply_assist(storage, vacancy_id)
    if preview.get("error_type") == "not_found":
        return preview

    storage.record_vacancy_event(
        vacancy_id,
        event_type="apply_assist_requested",
        source="apply_assist",
        payload={"approve": approve, "open_browser": open_browser},
    )

    data = preview["data"] or {}
    if not preview["ok"]:
        storage.record_vacancy_event(
            vacancy_id,
            event_type="apply_assist_blocked",
            source="apply_assist",
            payload={
                "failed_gates": data.get("failed_gates", []),
                "letter_validation_reasons": (data.get("letter_validation") or {}).get("reasons", []),
                "hard_red_flags": data.get("hard_red_flags", []),
            },
        )
        return preview

    storage.record_vacancy_event(
        vacancy_id,
        event_type="apply_assist_ready",
        source="apply_assist",
        payload={
            "approve": approve,
            "open_browser": open_browser,
            "gates_passed": [gate["name"] for gate in data.get("gates", []) if gate.get("ok")],
        },
    )

    if not approve:
        preview["message"] = (
            f"Apply assist ready for {vacancy_id}. Re-run with --approve to perform operator handoff."
        )
        return preview

    storage.record_vacancy_event(
        vacancy_id,
        event_type="apply_assist_approved",
        source="apply_assist",
        payload={"open_browser": open_browser},
        enqueue_outbox=True,
    )

    if open_browser:
        url = ((data.get("vacancy") or {}).get("alternate_url")) or ""
        if url:
            webbrowser.open(url)
            storage.record_vacancy_event(
                vacancy_id,
                event_type="apply_assist_handoff_opened",
                source="apply_assist",
                payload={"target": "browser", "url": url},
                enqueue_outbox=True,
            )

    preview["message"] = f"Apply assist handoff prepared for {vacancy_id}"
    return preview
