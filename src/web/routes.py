"""Web routes — FastAPI endpoints for dashboard, health, actions, jobs, and queue."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..services import (
    app_service,
    job_handlers,
    presets_service,
    review_service,
    settings_service,
    vacancy_service,
)
from ..services.apply_assist_service import execute_apply_assist, prepare_apply_assist
from ..services.notion_sync_service import NotionSyncService, load_notion_sync_config
from ..storage import Storage
from ..utils import redact_secrets
from .jobs import JobManager
from .schemas import (
    ActionRequest,
    AppliedRequest,
    BulkActionRequest,
    NextActionRequest,
    NoteRequest,
    OperatorApplyAssistApprovalRequest,
    OperatorHHSyncRequest,
    OperatorOutboxRequest,
    ReviewStatusRequest,
)

router = APIRouter()

_templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _template_globals() -> dict[str, str]:
    return {
        "app_name": "CareerSignal HH",
        "app_version": __version__,
    }


def _job_manager() -> JobManager:
    return JobManager.get()


def _storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def _normalize_date(value: str) -> str:
    if value.strip().lower() == "today":
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid date {value!r}. Use today or YYYY-MM-DD.") from exc


# ═══════════════════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════════════════


@router.get("/", response_class=HTMLResponse)
async def page_index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {**_template_globals()})


@router.get("/queue", response_class=HTMLResponse)
async def page_queue(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "queue.html", {**_template_globals()})


@router.get("/presets", response_class=HTMLResponse)
async def page_presets(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "presets.html", {**_template_globals()})


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", {**_template_globals()})


@router.get("/campaigns", response_class=HTMLResponse)
async def page_campaigns(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "campaigns.html", {**_template_globals()})


@router.get("/vacancy/{vacancy_id}", response_class=HTMLResponse)
async def page_vacancy(request: Request, vacancy_id: str) -> HTMLResponse:
    """Vacancy detail page with tabs."""
    return templates.TemplateResponse(
        request,
        "vacancy.html",
        {
            "vacancy_id": vacancy_id,
            **_template_globals(),
        },
    )


# ═══════════════════════════════════════════════════════════════════════
# API: Dashboard
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/dashboard")
async def api_dashboard() -> JSONResponse:
    try:
        state = app_service.get_dashboard_state()
        return JSONResponse(content={"ok": True, "data": state})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Health
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/health")
async def api_health() -> JSONResponse:
    try:
        checks = app_service.get_health_summary()
        sanitized = []
        for c in checks:
            detail = redact_secrets(c.get("detail", "")) or ""
            sanitized.append({**c, "detail": detail})
        return JSONResponse(content={"ok": True, "data": sanitized})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/actions/health")
async def api_action_health(body: ActionRequest) -> JSONResponse:
    try:
        checks = app_service.get_health_summary()
        critical = [c for c in checks if c["status"] == "FAIL"]
        ok = len(critical) == 0
        return JSONResponse(
            content={
                "ok": ok,
                "message": ("Health check complete" if ok else f"{len(critical)} critical issues"),
                "data": checks,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Review Queue
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/queue")
async def api_queue(
    min_score: int = 70,
    max_score: int | None = None,
    decision: str | None = None,
    preset: str | None = None,
    status: str | None = None,
    limit: int = 50,
    remote_only: bool = False,
    with_salary: bool = False,
    hide_risk: bool = False,
    new_only: bool = False,
    dedupe: bool = True,
) -> JSONResponse:
    """Return review queue with full filters."""
    try:
        decisions = decision.split(",") if decision else None
        rows = review_service.get_queue(
            min_score=min_score,
            max_score=max_score,
            decisions=decisions,
            preset=preset,
            status=status,
            limit=limit,
            remote_only=remote_only,
            with_salary=with_salary,
            hide_risk=hide_risk,
            new_only=new_only,
            dedupe=dedupe,
        )
        return JSONResponse(content={"ok": True, "data": rows, "count": len(rows)})
    except ValueError as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Vacancy operations
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/vacancies/{vacancy_id}")
async def api_vacancy_get(vacancy_id: str) -> JSONResponse:
    """Return full vacancy detail."""
    try:
        v = review_service.get_vacancy_full(vacancy_id)
        if v is None:
            return JSONResponse(
                content={"ok": False, "message": "Vacancy not found", "data": None},
                status_code=404,
            )
        v["raw_json"] = redact_secrets(v.get("raw_json"))
        return JSONResponse(content={"ok": True, "data": v})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/status")
async def api_vacancy_status(vacancy_id: str, body: ReviewStatusRequest) -> JSONResponse:
    """Update review status for a vacancy."""
    try:
        review = review_service.set_status(vacancy_id, body.status)
        return JSONResponse(
            content={
                "ok": True,
                "message": f"Status updated to {review['status']}",
                "data": review,
            }
        )
    except ValueError as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/note")
async def api_vacancy_note(vacancy_id: str, body: NoteRequest) -> JSONResponse:
    """Save a note on a vacancy."""
    try:
        review = review_service.set_note(vacancy_id, body.note)
        return JSONResponse(
            content={
                "ok": True,
                "message": "Note saved",
                "data": review,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/applied")
async def api_vacancy_applied(vacancy_id: str, body: AppliedRequest) -> JSONResponse:
    """Mark vacancy as applied (manual only)."""
    try:
        applied_at = _normalize_date(body.date)
        review = review_service.mark_applied(vacancy_id, applied_at)
        return JSONResponse(
            content={
                "ok": True,
                "message": f"Applied at {applied_at}",
                "data": review,
            }
        )
    except ValueError as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/next-action")
async def api_vacancy_next_action(vacancy_id: str, body: NextActionRequest) -> JSONResponse:
    """Set next action date for a vacancy."""
    try:
        next_at = _normalize_date(body.date)
        review = review_service.set_next_action(vacancy_id, body.action, next_at)
        return JSONResponse(
            content={
                "ok": True,
                "message": f"Next action set: {body.action} on {next_at}",
                "data": review,
            }
        )
    except ValueError as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/apply-pack")
async def api_vacancy_apply_pack(vacancy_id: str) -> JSONResponse:
    """Generate apply pack for a single vacancy (synchronous — usually fast)."""
    try:
        result = review_service.generate_apply_pack_for(vacancy_id)
        if result["ok"]:
            status_code = 200
        elif result.get("error_type") == "not_found":
            status_code = 404
        elif result.get("error_type") == "validation":
            status_code = 422
        else:
            status_code = 500
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/vacancies/{vacancy_id}/briefing")
async def api_vacancy_briefing(vacancy_id: str) -> JSONResponse:
    """Generate briefing for a single vacancy and persist it."""
    try:
        result = review_service.generate_briefing_for(vacancy_id)
        status_code = 200 if result["ok"] else 404 if result.get("error_type") == "not_found" else 500
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Vacancy detail (enhanced)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/vacancies/{vacancy_id}/full")
async def api_vacancy_full(vacancy_id: str) -> JSONResponse:
    """Return enhanced vacancy detail with parsed keywords, cluster, draft."""
    try:
        v = vacancy_service.get_full(vacancy_id)
        if v is None:
            return JSONResponse(
                content={"ok": False, "message": "Vacancy not found", "data": None},
                status_code=404,
            )
        v["raw_json"] = redact_secrets(v.get("raw_json"))
        return JSONResponse(content={"ok": True, "data": v})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.get("/api/vacancies/{vacancy_id}/score-explain")
async def api_vacancy_score_explain(vacancy_id: str) -> JSONResponse:
    """Return score explanation with category scores, keywords, formula."""
    try:
        data = vacancy_service.get_score_explain(vacancy_id)
        if data is None:
            return JSONResponse(
                content={"ok": False, "message": "Vacancy not found", "data": None},
                status_code=404,
            )
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.get("/api/vacancies/{vacancy_id}/apply-pack-preview")
async def api_vacancy_apply_pack_preview(
    vacancy_id: str, lang: str = "ru", style: str = "medium"
) -> JSONResponse:
    """Generate apply pack and return preview info."""
    try:
        result = vacancy_service.generate_apply_pack_preview(vacancy_id, lang, style)
        if result["ok"]:
            status_code = 200
        elif result.get("error_type") == "not_found":
            status_code = 404
        elif result.get("error_type") == "validation":
            status_code = 422
        else:
            status_code = 500
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.get("/api/vacancies/{vacancy_id}/similar")
async def api_vacancy_similar(vacancy_id: str, limit: int = 10) -> JSONResponse:
    """Return similar vacancies: same cluster, employer, title."""
    try:
        data = vacancy_service.get_similar(vacancy_id, limit)
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Bulk review actions
# ═══════════════════════════════════════════════════════════════════════


@router.post("/api/review/bulk-archive")
async def api_bulk_archive(body: BulkActionRequest) -> JSONResponse:
    """Bulk archive auto_hide vacancies. Requires confirm=true."""
    if not body.confirm:
        return JSONResponse(
            content={
                "ok": False,
                "message": "Confirmation required. Set confirm=true.",
                "data": None,
            },
            status_code=400,
        )
    try:
        result = review_service.bulk_archive_auto_hide(force=body.force)
        return JSONResponse(
            content={
                "ok": True,
                "message": (
                    f"Archived {result['updated_count']} / {result['matched_count']} matched"
                    + (
                        f" (skipped {result['skipped_protected_count']} protected)"
                        if result["skipped_protected_count"]
                        else ""
                    )
                ),
                "data": result,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/review/bulk-reject")
async def api_bulk_reject(body: BulkActionRequest) -> JSONResponse:
    """Bulk reject low-score vacancies. Requires confirm=true."""
    if not body.confirm:
        return JSONResponse(
            content={
                "ok": False,
                "message": "Confirmation required. Set confirm=true.",
                "data": None,
            },
            status_code=400,
        )
    try:
        result = review_service.bulk_reject_low_score(
            max_score=body.max_score or 35,
            force=body.force,
        )
        return JSONResponse(
            content={
                "ok": True,
                "message": (
                    f"Rejected {result['updated_count']} / {result['matched_count']} matched"
                    + (
                        f" (skipped {result['skipped_protected_count']} protected)"
                        if result["skipped_protected_count"]
                        else ""
                    )
                ),
                "data": result,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/review/bulk-interesting")
async def api_bulk_interesting(body: BulkActionRequest) -> JSONResponse:
    """Bulk mark strong matches as interesting. Requires confirm=true."""
    if not body.confirm:
        return JSONResponse(
            content={
                "ok": False,
                "message": "Confirmation required. Set confirm=true.",
                "data": None,
            },
            status_code=400,
        )
    try:
        result = review_service.bulk_mark_interesting(
            min_score=body.min_score or 85,
            decision=body.decision or "strong_match",
            force=body.force,
        )
        return JSONResponse(
            content={
                "ok": True,
                "message": (
                    f"Marked {result['updated_count']} / {result['matched_count']} as interesting"
                    + (
                        f" (skipped {result['skipped_protected_count']} protected)"
                        if result["skipped_protected_count"]
                        else ""
                    )
                ),
                "data": result,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Recent runs
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/recent-runs")
async def api_recent_runs(limit: int = 5) -> JSONResponse:
    try:
        runs = app_service.get_recent_runs(limit=limit)
        return JSONResponse(content={"ok": True, "data": runs})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Follow-ups
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/follow-ups")
async def api_follow_ups() -> JSONResponse:
    try:
        state = app_service.get_dashboard_state()
        return JSONResponse(content={"ok": True, "data": state.get("follow_ups", [])})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/follow-ups/{vacancy_id}/next-action")
async def api_follow_up_next(vacancy_id: str) -> JSONResponse:
    from datetime import date

    try:
        tomorrow = date.today().isoformat()
        from ..services.review_service import set_next_action

        result = set_next_action(vacancy_id, "follow-up", tomorrow)
        return JSONResponse(
            content={"ok": True, "message": "Follow-up set for tomorrow", "data": result},
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Presets & Campaigns
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/presets")
async def api_presets_list() -> JSONResponse:
    try:
        data = presets_service.list_all_presets()
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.get("/api/presets/{name}")
async def api_presets_get(name: str) -> JSONResponse:
    try:
        data = presets_service.get_preset_raw(name)
        if data is None:
            return JSONResponse(
                content={"ok": False, "message": "Preset not found", "data": None}, status_code=404
            )
        return JSONResponse(content={"ok": True, "data": {"_name": name, **data}})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.post("/api/presets/{name}")
async def api_presets_save(name: str, body: dict = {}) -> JSONResponse:
    try:
        result = presets_service.save_preset(name, body)
        status_code = 200 if result["ok"] else 400
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "errors": []}, status_code=500
        )


@router.post("/api/presets/{name}/clone")
async def api_presets_clone(name: str, new_name: str = "") -> JSONResponse:
    try:
        result = presets_service.clone_preset(name, new_name)
        status_code = 200 if result["ok"] else 400
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.post("/api/presets/{name}/enable")
async def api_presets_enable(name: str) -> JSONResponse:
    try:
        result = presets_service.set_preset_enabled(name, True)
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.post("/api/presets/{name}/disable")
async def api_presets_disable(name: str) -> JSONResponse:
    try:
        result = presets_service.set_preset_enabled(name, False)
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.post("/api/presets/{name}/validate")
async def api_presets_validate(name: str, body: dict = {}) -> JSONResponse:
    try:
        result = presets_service.validate_preset_ui(name, body)
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.get("/api/presets/{name}/suggestions")
async def api_presets_suggestions(name: str) -> JSONResponse:
    try:
        data = presets_service.get_calibration_suggestions(name)
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.post("/api/calibration/{suggestion_id}/apply")
async def api_calibration_apply(suggestion_id: str) -> JSONResponse:
    try:
        result = presets_service.apply_calibration_suggestion(suggestion_id)
        status_code = 200 if result["ok"] else 400
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.post("/api/calibration/{suggestion_id}/dismiss")
async def api_calibration_dismiss(suggestion_id: str) -> JSONResponse:
    try:
        result = presets_service.dismiss_calibration_suggestion(suggestion_id)
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.get("/api/campaigns")
async def api_campaigns_list() -> JSONResponse:
    try:
        data = presets_service.list_all_campaigns()
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.get("/api/campaigns/{name}")
async def api_campaigns_get(name: str) -> JSONResponse:
    try:
        data = presets_service.get_campaign_raw(name)
        if data is None:
            return JSONResponse(
                content={"ok": False, "message": "Campaign not found", "data": None},
                status_code=404,
            )
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.post("/api/campaigns/{name}")
async def api_campaigns_save(name: str, body: dict = {}) -> JSONResponse:
    try:
        result = presets_service.save_campaign(name, body)
        status_code = 200 if result["ok"] else 400
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# API: Settings
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/settings")
async def api_settings() -> JSONResponse:
    try:
        data = settings_service.get_settings()
        return JSONResponse(content={"ok": True, "data": data})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None}, status_code=500
        )


@router.post("/api/settings/env")
async def api_settings_env(body: dict = {}) -> JSONResponse:
    try:
        result = settings_service.save_env_settings(body)
        status_code = 200 if result["ok"] else 400
        # Ensure token is never echoed back
        if "message" in result and "updated" in result["message"]:
            pass  # message says 'updated' but never reveals token value
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "errors": []}, status_code=500
        )


@router.post("/api/settings/candidate")
async def api_settings_candidate(body: dict = {}) -> JSONResponse:
    try:
        result = settings_service.save_candidate_profile(body)
        status_code = 200 if result["ok"] else 400
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "errors": []}, status_code=500
        )


@router.post("/api/settings/test-auth")
async def api_settings_test_auth() -> JSONResponse:
    try:
        result = settings_service.test_auth()
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


@router.post("/api/settings/health")
async def api_settings_health() -> JSONResponse:
    try:
        import argparse

        from ..commands.health import command_health

        rc = command_health(argparse.Namespace())
        return JSONResponse(content={"ok": rc == 0, "message": "Health check completed"})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "message": str(exc)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# API: Operator control plane
# ═══════════════════════════════════════════════════════════════════════


@router.post("/api/operator/oauth/refresh")
async def api_operator_oauth_refresh() -> JSONResponse:
    from ..hh_oauth import HHOAuthManager

    try:
        bundle = HHOAuthManager(storage=_storage()).refresh()
        return JSONResponse(
            content={
                "ok": True,
                "message": "Managed OAuth access token refreshed.",
                "data": {
                    "expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
                },
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )


@router.post("/api/operator/hh-sync")
async def api_operator_hh_sync(body: OperatorHHSyncRequest) -> JSONResponse:
    from ..hh_sync import HHSyncService

    try:
        service = HHSyncService(storage=_storage())
        entity = body.entity.strip().lower()
        if entity == "me":
            result = service.sync_me()
        elif entity == "resumes":
            result = service.sync_resumes()
        elif entity == "negotiations":
            result = service.sync_negotiations(status=body.status, per_page=body.per_page)
        elif entity == "reconcile":
            result = service.reconcile()
        else:
            return JSONResponse(
                content={"ok": False, "message": f"Unsupported hh-sync entity: {body.entity}", "data": None},
                status_code=400,
            )
        return JSONResponse(
            content={
                "ok": True,
                "message": f"HH sync completed for {entity}.",
                "data": result,
            }
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )


@router.post("/api/operator/outbox")
async def api_operator_outbox(body: OperatorOutboxRequest) -> JSONResponse:
    try:
        service = NotionSyncService(_storage(), load_notion_sync_config())
        action = body.action.strip().lower()
        if action == "dry_run":
            result = service.dry_run_entries(
                status="pending",
                outbox_id=body.outbox_id,
                limit=body.limit,
            )
            return JSONResponse(
                content={
                    "ok": True,
                    "message": f"Prepared {len(result)} outbox payload(s) for dry-run.",
                    "data": result,
                }
            )
        if action == "push_pending":
            result = service.push_entries(
                status="pending",
                outbox_id=body.outbox_id,
                limit=body.limit,
            )
        elif action == "retry_failed":
            result = service.push_entries(
                status="failed",
                outbox_id=body.outbox_id,
                limit=body.limit,
                replayed=True,
            )
        elif action == "replay_one":
            if body.outbox_id is None:
                return JSONResponse(
                    content={"ok": False, "message": "Specify outbox_id for replay_one.", "data": None},
                    status_code=400,
                )
            if body.dry_run:
                result = service.dry_run_entries(
                    outbox_id=body.outbox_id,
                    limit=1,
                    replayed=True,
                )
                return JSONResponse(
                    content={
                        "ok": True,
                        "message": f"Prepared replay dry-run for outbox #{body.outbox_id}.",
                        "data": result,
                    }
                )
            result = service.push_entries(
                status=None,
                outbox_id=body.outbox_id,
                limit=1,
                replayed=True,
            )
        else:
            return JSONResponse(
                content={"ok": False, "message": f"Unsupported outbox action: {body.action}", "data": None},
                status_code=400,
            )
        return JSONResponse(
            content={
                "ok": True,
                "message": f"Outbox action {action} completed.",
                "data": result,
            }
        )
    except ValueError as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=400,
        )
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.get("/api/operator/apply-assist/{vacancy_id}")
async def api_operator_apply_assist_preview(vacancy_id: str) -> JSONResponse:
    try:
        result = prepare_apply_assist(_storage(), vacancy_id)
        status_code = 200 if result["ok"] else 404 if result.get("error_type") == "not_found" else 200
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.post("/api/operator/apply-assist/{vacancy_id}/approve")
async def api_operator_apply_assist_approve(
    vacancy_id: str,
    body: OperatorApplyAssistApprovalRequest,
) -> JSONResponse:
    try:
        result = execute_apply_assist(
            _storage(),
            vacancy_id,
            approve=True,
            open_browser=body.open_browser,
        )
        status_code = 200 if result["ok"] else 404 if result.get("error_type") == "not_found" else 200
        return JSONResponse(content=result, status_code=status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


# ═══════════════════════════════════════════════════════════════════════
# API: Jobs (launch, query, control)
# ═══════════════════════════════════════════════════════════════════════


def _start_job(name: str, handler_fn, **kwargs: Any) -> JSONResponse:
    mgr = _job_manager()

    def wrapper(job):
        return handler_fn(job, **kwargs) if kwargs else handler_fn(job)

    job = mgr.start_job(name, wrapper)

    if job.status == "failed" and not job.started_at:
        return JSONResponse(
            content={
                "ok": False,
                "message": job.error or "Cannot start job",
                "data": job.sanitized_dict(),
            },
            status_code=409,
        )

    return JSONResponse(
        content={
            "ok": True,
            "message": f"Job started: {name}",
            "data": job.sanitized_dict(),
        },
        status_code=202,
    )


@router.post("/api/jobs/autopilot-daily")
async def api_job_autopilot(body: ActionRequest) -> JSONResponse:
    if body.mode == "deep":
        return JSONResponse(
            content={
                "ok": False,
                "message": "Deep mode is not available in UI",
                "data": None,
            },
            status_code=400,
        )
    return _start_job(
        "autopilot-daily",
        job_handlers.job_autopilot_daily,
        mode=body.mode,
        preset=body.preset,
    )


@router.post("/api/jobs/search-smoke")
async def api_job_search_smoke(body: ActionRequest) -> JSONResponse:
    return _start_job("search-smoke", job_handlers.job_search_smoke, preset=body.preset)


@router.post("/api/jobs/search-normal")
async def api_job_search_normal(body: ActionRequest) -> JSONResponse:
    return _start_job("search-normal", job_handlers.job_search_normal, preset=body.preset)


@router.post("/api/jobs/export-all")
async def api_job_export_all() -> JSONResponse:
    return _start_job("export-all", job_handlers.job_export_all)


@router.post("/api/jobs/quality-cluster")
async def api_job_quality_cluster() -> JSONResponse:
    return _start_job("quality-cluster", job_handlers.job_quality_cluster)


@router.post("/api/jobs/calibrate-suggest")
async def api_job_calibrate_suggest() -> JSONResponse:
    return _start_job("calibrate-suggest", job_handlers.job_calibrate_suggest)


@router.post("/api/jobs/apply-pack-top")
async def api_job_apply_pack_top(limit: int = 5) -> JSONResponse:
    return _start_job("apply-pack-top", job_handlers.job_apply_pack_top, limit=limit)


@router.get("/api/jobs")
async def api_jobs_list(limit: int = 20) -> JSONResponse:
    try:
        jobs = _job_manager().list_jobs(limit=limit)
        return JSONResponse(content={"ok": True, "data": jobs})
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "message": str(exc), "data": None},
            status_code=500,
        )


@router.get("/api/jobs/{job_id}")
async def api_jobs_get(job_id: str) -> JSONResponse:
    job = _job_manager().get_job(job_id)
    if job is None:
        return JSONResponse(
            content={"ok": False, "message": "Job not found", "data": None},
            status_code=404,
        )
    return JSONResponse(content={"ok": True, "data": job.sanitized_dict()})


@router.post("/api/jobs/{job_id}/cancel")
async def api_jobs_cancel(job_id: str) -> JSONResponse:
    cancelled = _job_manager().cancel_job(job_id)
    if not cancelled:
        return JSONResponse(
            content={
                "ok": False,
                "message": "Job not found or not in running/queued state",
                "data": None,
            },
            status_code=404,
        )
    return JSONResponse(content={"ok": True, "message": "Cancellation requested", "data": None})
