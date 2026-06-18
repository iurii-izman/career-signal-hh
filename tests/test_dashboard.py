"""Tests for the upgraded daily action center dashboard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


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
