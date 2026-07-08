"""Tests for the upgraded daily action center dashboard."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import Vacancy
from src.storage import Storage


@pytest.fixture
def empty_db(tmp_path: Path, monkeypatch) -> str:
    db_path = str(tmp_path / "data" / "test_dash.sqlite")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.close()
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None, raising=False)
    return db_path


def _init_db(db_path: str) -> None:
    from src.db_migrations import apply_migrations

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    conn.close()


def test_dashboard_renders_empty_db() -> None:
    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "action-plan" in resp.text
    assert "follow-ups-panel" in resp.text
    assert "reports-panel" in resp.text


def test_dashboard_state_has_new_fields(empty_db: str) -> None:
    _init_db(empty_db)

    from src.services.app_service import get_dashboard_state

    state = get_dashboard_state()
    assert "backup_overdue" in state
    assert "cluster_count" in state
    assert "calibration_count" in state
    assert "follow_ups" in state
    assert "reports" in state
    assert isinstance(state["follow_ups"], list)
    assert isinstance(state["reports"], list)
    assert "pipeline" in state
    assert "queue_health" in state
    assert "risk_buckets" in state
    assert "preset_performance" in state
    assert "recent_activity" in state
    assert "attention_items" in state
    assert "action_plan" in state
    assert "operator" in state


def test_dashboard_uses_briefing_events_and_outbox(empty_db: str) -> None:
    _init_db(empty_db)
    storage = Storage(empty_db)
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="dash-1",
            name="AI Systems Analyst",
            employer_name="Acme",
            alternate_url="https://hh.ru/vacancy/dash-1",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
            source_profile="ai_rag_remote",
            source_query="ai systems analyst",
        )
    )

    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO scores (vacancy_id, total_score, best_profile, scored_at, work_format_flags_json, risk_flags_json, match_reasons_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("dash-1", 91, "ai_rag_remote", now, '["remote"]', "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO score_details (vacancy_id, preset_name, total_score, confidence_score, noise_score, decision, "
            "category_scores_json, matched_keywords_json, excluded_keywords_json, risk_flags_json, quality_flags_json, work_format_flags_json, explanation_json, scored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "dash-1",
                "ai_rag_remote",
                91,
                70,
                10,
                "strong_match",
                "{}",
                "[]",
                "[]",
                "[]",
                '["remote_confirmed"]',
                '["remote"]',
                "{}",
                now,
            ),
        )

    storage.upsert_review("dash-1", status="interesting", cover_letter_draft="draft")
    storage.upsert_briefing_report(
        "dash-1",
        lang="ru",
        score_total=91,
        decision="strong_match",
        report_md="# Briefing",
        payload={"vacancy_id": "dash-1", "blocks": []},
    )

    from src.services.app_service import get_dashboard_state

    state = get_dashboard_state()
    assert state["pipeline"]["briefed"] >= 1
    assert state["pipeline"]["drafted"] >= 1
    assert state["briefing_summary"]["saved"] >= 1
    assert state["queue_health"]["outbox_pending"] >= 1
    assert any(item["preset"] == "ai_rag_remote" for item in state["preset_performance"])
    assert any(item["event_type"] == "briefing_saved" for item in state["recent_activity"])
    assert any(item["action"] == "briefing_focus" or item["action"] == "run_health" for item in state["action_plan"])


def test_action_plan_generated() -> None:
    from src.services.app_service import get_action_plan

    plan = get_action_plan()
    assert isinstance(plan, list)
    assert len(plan) > 0
    actions = [p["action"] for p in plan]
    assert any("health" in a for a in actions)


def test_overdue_backup_action(empty_db: str) -> None:
    _init_db(empty_db)

    from src.services.app_service import get_dashboard_state

    state = get_dashboard_state()
    assert "latest_backup" in state
    assert "backup_overdue" in state


def test_queue_action_in_plan() -> None:
    from src.services.app_service import get_action_plan

    plan = get_action_plan()
    actions = [p["action"] for p in plan]
    assert len(actions) >= 1


def test_index_template_has_sections() -> None:
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    assert "action-plan" in html
    assert "ext-status" in html
    assert "follow-ups-panel" in html
    assert "reports-panel" in html
    assert "quick-actions" in html
    assert "pipeline-cards" in html
    assert "queue-health-cards" in html
    assert "risk-buckets-panel" in html
    assert "preset-performance-panel" in html
    assert "activity-panel" in html
    assert "operator-cards" in html
    assert "apply-assist-panel" in html
    assert "operator-assist-activity" in html
    assert "operator-outbox-activity" in html


def test_follow_ups_endpoint() -> None:
    import asyncio

    from src.web.routes import api_follow_ups

    async def _run():
        resp = await api_follow_ups()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)

    asyncio.run(_run())


def test_no_external_resources_in_template() -> None:
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    assert "cdn." not in html.lower()
    assert "googleapis" not in html.lower()
    assert "unpkg" not in html.lower()


def test_no_external_resources_in_js() -> None:
    js = Path("src/web/static/app.js").read_text(encoding="utf-8")
    assert "cdn." not in js.lower()
    assert "googleapis" not in js.lower()
    assert "unpkg" not in js.lower()


def test_attention_panel_has_shortcut_actions() -> None:
    js = Path("src/web/static/app.js").read_text(encoding="utf-8")
    assert 'data-va="briefing"' in js
    assert "Generate Briefing" in js
    assert '"/briefing"' in js
    assert "Follow-up tmrw" in js
    assert "operator-preview-assist" in js
    assert "operator-approve-assist" in js


def test_dashboard_operator_state_surfaces_control_plane(empty_db: str) -> None:
    _init_db(empty_db)
    storage = Storage(empty_db)
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="assist-1",
            name="Platform Python Engineer",
            employer_name="Signal",
            alternate_url="https://hh.ru/vacancy/assist-1",
            raw_json="{}",
            description_text="Remote platform role",
            first_seen_at=now,
            last_seen_at=now,
            source_profile="python",
            source_query="python engineer",
        )
    )
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO scores (vacancy_id, total_score, best_profile, scored_at, work_format_flags_json, risk_flags_json, match_reasons_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("assist-1", 92, "python", now, '["remote"]', "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO score_details (vacancy_id, preset_name, total_score, confidence_score, noise_score, decision, "
            "category_scores_json, matched_keywords_json, excluded_keywords_json, risk_flags_json, quality_flags_json, work_format_flags_json, explanation_json, scored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "assist-1",
                "python",
                92,
                70,
                10,
                "strong_match",
                "{}",
                "[]",
                "[]",
                "[]",
                "[]",
                '["remote"]',
                "{}",
                now,
            ),
        )
    storage.upsert_review("assist-1", status="interesting", cover_letter_draft="draft")
    storage.upsert_briefing_report(
        "assist-1",
        lang="ru",
        score_total=92,
        decision="strong_match",
        report_md="# Briefing",
        payload={"vacancy_id": "assist-1"},
    )

    from src.services.app_service import get_operator_state

    state = get_operator_state(storage=storage)

    assert "oauth" in state
    assert "hh_sync" in state
    assert "outbox" in state
    assert "apply_assist" in state
    assert "recent_activity" in state
    assert state["apply_assist"]["evaluated"] >= 1
