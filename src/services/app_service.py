"""App service — dashboard, health, action-plan, and operator control plane."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..hh_oauth import HHOAuthManager
from ..hh_sync import HHSyncService
from ..storage import OUTBOX_TARGET_EXTERNAL_SYNC, Storage


def _get_storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def get_dashboard_state() -> dict[str, Any]:
    """Return dashboard snapshot with operational counters and action context."""
    load_dotenv()
    storage = _get_storage()
    stats = storage.stats()
    operational = storage.get_operational_metrics()

    # Queue counts
    try:
        strong_matches = len(storage.list_queue(min_score=0, decision="strong_match", limit=10000))
    except Exception:
        strong_matches = 0
    try:
        pending = len(storage.list_queue(min_score=70, new_only=True, limit=10000))
    except Exception:
        pending = 0

    # Review funnel
    applied = 0
    interview = 0
    offer = 0
    try:
        with storage.connect() as conn:
            applied = conn.execute(
                "SELECT COUNT(*) FROM vacancy_reviews WHERE status='applied'"
            ).fetchone()[0]
            interview = conn.execute(
                "SELECT COUNT(*) FROM vacancy_reviews WHERE status='interview'"
            ).fetchone()[0]
            offer = conn.execute(
                "SELECT COUNT(*) FROM vacancy_reviews WHERE status='offer'"
            ).fetchone()[0]
    except Exception:
        pass

    # Latest search run
    latest_search: str | None = None
    try:
        with storage.connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM search_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            if row:
                latest_search = (row[0] or "")[:19]
    except Exception:
        pass

    # Latest backup + overdue flag
    latest_backup: str | None = None
    backup_overdue = False
    backups_dir = Path("backups")
    if backups_dir.exists():
        backups = sorted(backups_dir.glob("vacancies_*.sqlite"), reverse=True)
        if backups:
            latest_backup = backups[0].name
    backup_age = _latest_file_age("backups/vacancies_*.sqlite")
    if backup_age is not None and backup_age > 48:
        backup_overdue = True

    # Latest export
    latest_export: str | None = None
    export_html = Path("exports/vacancies_report.html")
    if export_html.exists():
        mtime = datetime.fromtimestamp(export_html.stat().st_mtime, tz=timezone.utc)
        latest_export = mtime.strftime("%Y-%m-%d %H:%M")

    # Cluster count
    cluster_count = 0
    try:
        with storage.connect() as conn:
            cluster_count = conn.execute(
                "SELECT COUNT(DISTINCT cluster_id) FROM vacancy_clusters"
            ).fetchone()[0]
    except Exception:
        pass

    # Calibration suggestions
    calibration_count = 0
    try:
        sp = Path("data/calibration_suggestions.json")
        if sp.exists():
            suggestions = json.loads(sp.read_text(encoding="utf-8"))
            calibration_count = sum(
                1 for s in suggestions if s.get("status", "pending") == "pending"
            )
    except Exception:
        pass

    # Follow-up applied vacancies
    follow_ups = _get_follow_ups(storage)

    # Available reports
    reports = _get_available_reports()

    state = {
        "total_vacancies": stats["total"],
        "new_24h": stats["new_24h"],
        "avg_score": round(stats["avg_score"], 1),
        "remote_count": stats["remote"],
        "with_salary_count": stats["with_salary"],
        "strong_matches": strong_matches,
        "pending_queue": pending,
        "applied": applied,
        "interview": interview,
        "offer": offer,
        "latest_search_run": latest_search,
        "latest_backup": latest_backup,
        "latest_export": latest_export,
        "backup_overdue": backup_overdue,
        "cluster_count": cluster_count,
        "calibration_count": calibration_count,
        "follow_ups": follow_ups,
        "reports": reports,
        "pipeline": operational.get("pipeline", {}),
        "queue_health": operational.get("queue_health", {}),
        "status_buckets": operational.get("status_buckets", []),
        "risk_buckets": operational.get("risk_buckets", []),
        "preset_performance": operational.get("preset_performance", []),
        "recent_activity": operational.get("recent_activity", []),
        "attention_items": operational.get("attention_items", []),
        "briefing_summary": operational.get("briefing_summary", {}),
        "outbox_summary": operational.get("outbox_summary", {}),
        "operator": get_operator_state(storage=storage),
    }
    state["action_plan"] = _build_action_plan(state)
    return state


def get_operator_state(
    *,
    storage: Storage | None = None,
    readiness_limit: int = 5,
    activity_limit: int = 8,
) -> dict[str, Any]:
    """Return operator-facing control plane state for UI surfaces."""
    load_dotenv()
    active_storage = storage or _get_storage()

    oauth: dict[str, Any]
    try:
        oauth_status = HHOAuthManager(storage=active_storage).status()
        oauth = {
            "ok": True,
            "configured": bool(oauth_status.get("configured")),
            "storage_backend": oauth_status.get("storage_backend"),
            "managed_access_token_present": bool(oauth_status.get("managed_access_token_present")),
            "managed_refresh_token_present": bool(oauth_status.get("managed_refresh_token_present")),
            "manual_env_token_present": bool(oauth_status.get("manual_env_token_present")),
            "account_email": oauth_status.get("account_email"),
            "scope": oauth_status.get("scope"),
            "expired": bool(oauth_status.get("expired")),
            "last_refresh_at": oauth_status.get("last_refresh_at"),
            "last_sync_at": oauth_status.get("last_sync_at"),
            "last_error": oauth_status.get("last_error"),
            "storage_error": oauth_status.get("storage_error"),
        }
    except Exception as exc:
        oauth = {
            "ok": False,
            "configured": False,
            "message": str(exc),
        }

    hh_sync = {
        **HHSyncService(storage=active_storage).reconcile(),
        "sync_actions": ["me", "resumes", "negotiations", "reconcile"],
        "read_only_remote": True,
    }

    from .apply_assist_service import prepare_apply_assist
    from .notion_sync_service import (
        NotionSyncService,
        load_notion_sync_config,
        redact_webhook_url,
    )

    notion_service = NotionSyncService(active_storage, load_notion_sync_config())
    outbox_summary = active_storage.summarize_outbox(target=notion_service.config.target)
    push_ready, push_reason = notion_service.validate_push_ready()
    outbox_recent = _get_recent_outbox_activity(
        active_storage,
        target=notion_service.config.target,
        limit=activity_limit,
    )

    candidate_ids = _get_apply_assist_candidate_ids(active_storage, limit=max(readiness_limit * 3, 8))
    readiness_items: list[dict[str, Any]] = []
    ready_count = 0
    blocked_count = 0
    for vacancy_id in candidate_ids:
        preview = prepare_apply_assist(active_storage, vacancy_id)
        data = preview.get("data") or {}
        vacancy = data.get("vacancy") or {}
        item = {
            "vacancy_id": vacancy_id,
            "ok": bool(preview.get("ok")),
            "message": preview.get("message"),
            "vacancy": vacancy,
            "score": data.get("score") or {},
            "review": data.get("review") or {},
            "failed_gates": data.get("failed_gates") or [],
            "artifacts": data.get("artifacts") or {},
        }
        if item["ok"]:
            ready_count += 1
        else:
            blocked_count += 1
        readiness_items.append(item)
        if len(readiness_items) >= readiness_limit:
            break

    return {
        "oauth": oauth,
        "hh_sync": hh_sync,
        "outbox": {
            "summary": outbox_summary,
            "config": {
                "enabled": notion_service.config.enabled,
                "provider": notion_service.config.provider,
                "target": notion_service.config.target or OUTBOX_TARGET_EXTERNAL_SYNC,
                "webhook": redact_webhook_url(notion_service.config.webhook_url)
                or notion_service.config.webhook_url_env,
                "push_ready": push_ready,
                "push_reason": push_reason,
            },
            "recent": outbox_recent,
        },
        "apply_assist": {
            "read_only_remote": True,
            "explicit_approval_required": True,
            "auto_apply": False,
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "evaluated": len(readiness_items),
            "items": readiness_items,
        },
        "recent_activity": {
            "assist": _get_recent_assist_activity(active_storage, limit=activity_limit),
            "outbox": outbox_recent,
        },
    }


def _get_follow_ups(storage: Storage) -> list[dict[str, Any]]:
    """Return applied vacancies needing follow-up."""
    follow_ups = []
    try:
        with storage.connect() as conn:
            rows = conn.execute(
                "SELECT v.id, v.name, v.employer_name, v.alternate_url,"
                " r.applied_at, r.next_action, r.next_action_at,"
                " COALESCE(s.total_score, 0) total_score"
                " FROM vacancies v"
                " JOIN vacancy_reviews r ON r.vacancy_id = v.id"
                " LEFT JOIN scores s ON s.vacancy_id = v.id"
                " WHERE r.status = 'applied'"
                " AND (r.next_action IS NULL OR r.next_action_at IS NULL"
                "  OR datetime(r.applied_at) <= datetime('now', '-5 days'))"
                " ORDER BY r.applied_at ASC"
                " LIMIT 15"
            ).fetchall()
            follow_ups = [dict(row) for row in rows]
    except Exception:
        pass
    return follow_ups


def _get_apply_assist_candidate_ids(storage: Storage, *, limit: int) -> list[str]:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT v.id
            FROM vacancies v
            LEFT JOIN score_details sd ON sd.vacancy_id = v.id
            LEFT JOIN scores s ON s.vacancy_id = v.id
            LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
            WHERE COALESCE(r.status, 'new') IN ('interesting', 'maybe', 'new')
              AND COALESCE(sd.total_score, s.total_score, 0) >= 70
            ORDER BY COALESCE(sd.total_score, s.total_score, 0) DESC, v.last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def _get_recent_assist_activity(storage: Storage, *, limit: int) -> list[dict[str, Any]]:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT
                ve.vacancy_id,
                ve.event_type,
                ve.created_at,
                ve.new_status,
                v.name,
                v.employer_name
            FROM vacancy_events ve
            JOIN vacancies v ON v.id = ve.vacancy_id
            WHERE ve.event_type LIKE 'apply_assist_%'
            ORDER BY ve.created_at DESC, ve.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_recent_outbox_activity(
    storage: Storage,
    *,
    target: str,
    limit: int,
) -> list[dict[str, Any]]:
    with storage.connect() as connection:
        rows = connection.execute(
            """
            SELECT
                o.id,
                o.vacancy_id,
                o.event_type,
                o.status,
                o.attempts,
                o.last_error,
                o.created_at,
                o.updated_at,
                v.name,
                v.employer_name
            FROM integration_outbox o
            LEFT JOIN vacancies v ON v.id = o.vacancy_id
            WHERE o.target = ?
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ?
            """,
            (target, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _get_available_reports() -> list[dict[str, str]]:
    """Return list of available report files."""
    reports = []
    candidates = [
        ("exports/vacancies_report.html", "Vacancies Report"),
        ("exports/cockpit.html", "Cockpit"),
        ("exports/analytics_report.html", "Analytics"),
        ("exports/data_quality_report.html", "Data Quality"),
        ("exports/calibration_report.html", "Calibration"),
        ("apply_packs/index.html", "Apply Packs Index"),
        ("exports/analytics_summary.json", "Summary JSON"),
    ]
    for path, label in candidates:
        if Path(path).exists():
            reports.append({"path": path, "label": label})
    return reports


def get_health_summary() -> list[dict[str, str]]:
    """Return health check results."""
    from .. import __version__

    load_dotenv()
    checks: list[dict[str, str]] = []

    def add(label: str, status: str, detail: str) -> None:
        checks.append({"check": label, "status": status, "detail": detail})

    add("Version", "OK", __version__)

    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")
    db_file = Path(db_path)
    if db_file.is_file():
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            pragma_ok = row is not None and row[0] == "ok"
            if pragma_ok:
                add("DB integrity", "OK", "integrity_check passed")
            else:
                detail = row[0] if row else "no result"
                add("DB integrity", "FAIL", f"integrity_check: {detail}")

            from ..db_migrations import apply_migrations, check_integrity_extended

            ext = check_integrity_extended(conn)
            wf_ok = ext.get("score_details_has_wf_flags", True)
            ver_current = ext.get("current_schema_version", 0)
            ver_expected = ext.get("expected_schema_version", 0)

            add(
                "DB work_format column",
                "OK" if wf_ok else "FAIL",
                "OK" if wf_ok else "work_format_flags_json missing",
            )
            if ver_current < ver_expected:
                add("DB schema version", "WARN", f"{ver_current} < {ver_expected}")
            else:
                add("DB schema version", "OK", f"{ver_current}")
            mig_result = apply_migrations(conn)
            if mig_result["failed"] > 0:
                add("DB migrations", "FAIL", f"{mig_result['failed']} failed")
            else:
                add("DB migrations", "OK", "up to date")
        finally:
            conn.close()
    else:
        add("DB integrity", "WARN", "DB file not found")

    for filename, required in [
        (".env", False),
        ("config/search_presets.yaml", False),
        ("config/scoring_rules.yaml", True),
        ("config/maintenance.yaml", False),
    ]:
        path = Path(filename)
        if required:
            s, d = ("OK", "exists") if path.is_file() else ("FAIL", "missing (required)")
        else:
            s, d = ("OK", "exists") if path.is_file() else ("WARN", "missing (optional)")
        add(f"Config: {filename}", s, d)

    from ..hh_client import HHClient

    client = HHClient()
    if client.auth_mode in {"application_token", "user_oauth"} and not client.active_token_present:
        add("Auth token", "FAIL", f"{client.auth_mode} mode but token missing")
    else:
        add(
            "Auth token",
            "OK",
            f"mode={client.auth_mode}, token={'set' if client.active_token_present else 'not set'}",
        )

    backup_age = _latest_file_age("backups/vacancies_*.sqlite")
    if backup_age is None:
        add("Latest backup", "WARN", "no backups found")
    elif backup_age > 48:
        add("Latest backup", "WARN", f"{backup_age}h old (>48h)")
    else:
        add("Latest backup", "OK", f"{backup_age}h ago")

    export_age = _latest_file_age("exports/vacancies_report.html")
    if export_age is None:
        add("Latest export", "WARN", "no export found")
    elif export_age > 48:
        add("Latest export", "WARN", f"{export_age}h old (>48h)")
    else:
        add("Latest export", "OK", f"{export_age}h ago")

    return checks


def get_recent_runs(limit: int = 5) -> list[dict[str, Any]]:
    load_dotenv()
    storage = _get_storage()
    try:
        with storage.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM search_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def get_action_plan() -> list[dict[str, str]]:
    state = get_dashboard_state()
    return state.get("action_plan", [])


def _build_action_plan(state: dict[str, Any]) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []

    if state["pending_queue"] > 0:
        plan.append(
            {
                "action": "review_queue",
                "label": f"Review {state['pending_queue']} pending vacancies",
                "priority": "high",
            }
        )
    if state["latest_search_run"] is None:
        plan.append(
            {
                "action": "run_autopilot",
                "label": "Run first autopilot daily scan",
                "priority": "high",
            }
        )
    else:
        try:
            last = datetime.fromisoformat(state["latest_search_run"])
            hours_ago = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            if hours_ago > 24:
                plan.append(
                    {
                        "action": "run_autopilot",
                        "label": f"Search stale ({hours_ago:.0f}h ago), run autopilot",
                        "priority": "medium",
                    }
                )
        except (ValueError, TypeError):
            pass
    if state.get("backup_overdue"):
        plan.append(
            {
                "action": "run_backup",
                "label": "Backup overdue — create database backup",
                "priority": "high",
            }
        )
    if state["latest_backup"] is None:
        plan.append(
            {
                "action": "run_backup",
                "label": "Create first database backup",
                "priority": "medium",
            }
        )
    if state.get("follow_ups") and len(state["follow_ups"]) > 0:
        plan.append(
            {
                "action": "follow_up",
                "label": f"Follow up {len(state['follow_ups'])} applied vacancies",
                "priority": "medium",
            }
        )
    if state.get("calibration_count", 0) > 0:
        plan.append(
            {
                "action": "calibrate",
                "label": f"Review {state['calibration_count']} calibration suggestions",
                "priority": "low",
            }
        )
    if state.get("cluster_count", 0) > 0:
        plan.append(
            {
                "action": "quality",
                "label": f"Review {state['cluster_count']} duplicate clusters",
                "priority": "low",
            }
        )
    missing_briefing = int(state.get("queue_health", {}).get("missing_briefing", 0))
    if missing_briefing > 0:
        plan.append(
            {
                "action": "briefing_focus",
                "label": f"Create briefing for {missing_briefing} strong matches",
                "priority": "high" if missing_briefing >= 3 else "medium",
            }
        )
    outbox_failed = int(state.get("queue_health", {}).get("outbox_failed", 0))
    if outbox_failed > 0:
        plan.append(
            {
                "action": "outbox_focus",
                "label": f"Resolve {outbox_failed} failed sync events",
                "priority": "medium",
            }
        )
    plan.append(
        {
            "action": "run_health",
            "label": "Run health check",
            "priority": "low",
        }
    )
    return plan


def _latest_file_age(glob_pattern: str) -> int | None:
    best_mtime: float | None = None
    for path in Path().glob(glob_pattern):
        if path.is_file():
            mt = path.stat().st_mtime
            if best_mtime is None or mt > best_mtime:
                best_mtime = mt
    if best_mtime is None:
        return None
    return int((datetime.now().timestamp() - best_mtime) / 3600)
