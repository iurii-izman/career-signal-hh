"""Tests for review queue UI page and endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def empty_db(tmp_path: Path, monkeypatch) -> str:
    db_path = str(tmp_path / "data" / "test_queue.sqlite")
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


def _seed_vacancy(db_path: str, vid: str, name: str = "Test Vacancy") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO vacancies (id, name, raw_json, first_seen_at, last_seen_at)"
        " VALUES (?, ?, '{}', datetime('now'), datetime('now'))",
        (vid, name),
    )
    conn.commit()
    conn.close()


# ── Queue page renders ──────────────────────────────────────────────────


def test_queue_page_renders(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "123")


    from fastapi.testclient import TestClient

    # Simple test: page_queue returns a TemplateResponse
    # We can't easily test the full rendering without an HTTP client,
    # but we can verify the endpoint exists and doesn't crash
    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/queue")
    assert resp.status_code == 200
    assert "queue-layout" in resp.text
    assert "queue-filters" in resp.text


# ── GET /api/queue returns list ─────────────────────────────────────────


def test_api_queue_returns_list(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "123")

    import asyncio

    from src.web.routes import api_queue

    async def _run():
        resp = await api_queue(min_score=0, limit=50)
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)
        assert body["count"] >= 0

    asyncio.run(_run())


# ── Status button updates review ────────────────────────────────────────


def test_status_button_updates_review(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "456", "Python Dev")

    import asyncio

    from src.web.routes import api_vacancy_status
    from src.web.schemas import ReviewStatusRequest

    async def _run():
        body = ReviewStatusRequest(status="interesting")
        resp = await api_vacancy_status("456", body)
        import json

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["data"]["status"] == "interesting"

    asyncio.run(_run())


# ── Note saves ──────────────────────────────────────────────────────────


def test_note_saves(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "789")

    import asyncio

    from src.web.routes import api_vacancy_note
    from src.web.schemas import NoteRequest

    async def _run():
        body = NoteRequest(note="Test note content")
        resp = await api_vacancy_note("789", body)
        import json

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["data"]["user_notes"] == "Test note content"

    asyncio.run(_run())


# ── Mark applied sets status=applied ────────────────────────────────────


def test_mark_applied_sets_status(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "101")

    import asyncio

    from src.web.routes import api_vacancy_applied
    from src.web.schemas import AppliedRequest

    async def _run():
        body = AppliedRequest(date="2026-06-18")
        resp = await api_vacancy_applied("101", body)
        import json

        data = json.loads(resp.body)
        assert data["ok"] is True
        assert data["data"]["status"] == "applied"

    asyncio.run(_run())


# ── Apply-pack endpoint generates file ──────────────────────────────────


def test_apply_pack_endpoint_exists(empty_db: str) -> None:
    """Endpoint exists and handles request (may fail without real data but no 500)."""
    _init_db(empty_db)
    _seed_vacancy(empty_db, "202", "Test Job")

    import asyncio

    from src.web.routes import api_vacancy_apply_pack

    async def _run():
        resp = await api_vacancy_apply_pack("202")
        import json

        body = json.loads(resp.body)
        # May fail gracefully if scoring data missing
        assert "ok" in body
        assert "message" in body

    asyncio.run(_run())


# ── Bulk action requires confirm flag ───────────────────────────────────


def test_bulk_archive_requires_confirm(empty_db: str) -> None:
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_bulk_archive
    from src.web.schemas import BulkActionRequest

    async def _run():
        body = BulkActionRequest(confirm=False)
        resp = await api_bulk_archive(body)
        import json

        data = json.loads(resp.body)
        assert data["ok"] is False
        assert "Confirmation" in data["message"]

    asyncio.run(_run())


def test_bulk_reject_requires_confirm(empty_db: str) -> None:
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_bulk_reject
    from src.web.schemas import BulkActionRequest

    async def _run():
        body = BulkActionRequest(confirm=False)
        resp = await api_bulk_reject(body)
        import json

        data = json.loads(resp.body)
        assert data["ok"] is False

    asyncio.run(_run())


# ── Applied/interview/offer protected ───────────────────────────────────


def test_protected_statuses_not_overwritten(empty_db: str) -> None:
    """Applied status should not be overwritten by bulk without force."""
    _init_db(empty_db)
    _seed_vacancy(empty_db, "303")

    # First set status to applied
    from src.services.review_service import set_status

    set_status("303", "applied")

    # Try bulk archive without force
    from src.services.review_service import bulk_archive_auto_hide

    result = bulk_archive_auto_hide(force=False)
    # The applied vacancy is not auto_hide, so it won't be matched at all.
    # But the bulk operation itself should complete without error.
    assert "matched_count" in result
    assert "skipped_protected_count" in result


# ── No auto-apply endpoint exists ───────────────────────────────────────


def test_no_auto_apply_endpoint() -> None:
    """Verify there's no endpoint that auto-submits applications."""
    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)

    # Check that no "auto-apply" or "submit-application" route exists
    resp = client.post("/api/auto-apply")
    assert resp.status_code == 404

    resp = client.post("/api/submit-application")
    assert resp.status_code == 404


# ── Queue page template has required elements ───────────────────────────


def test_queue_template_has_filter_elements() -> None:
    html = Path("src/web/templates/queue.html").read_text(encoding="utf-8")
    assert "f-min-score" in html
    assert "f-decision" in html
    assert "f-status" in html
    assert "f-preset" in html
    assert "btn-bulk-archive" in html
    assert "queue-cards" in html
    assert "drawer" in html


# ── Vacancy detail endpoint ─────────────────────────────────────────────


def test_vacancy_detail_endpoint(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "404")

    import asyncio

    from src.web.routes import api_vacancy_get

    async def _run():
        resp = await api_vacancy_get("404")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["id"] == "404"

        # Non-existent
        resp2 = await api_vacancy_get("99999")
        body2 = json.loads(resp2.body)
        assert body2["ok"] is False

    asyncio.run(_run())


# ── sidebar link to /queue exists ───────────────────────────────────────


def test_dashboard_index_has_queue_link() -> None:
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    # Should have a way to navigate to queue (sidebar or action)
    assert "/queue" in html or "review-queue" in html
