"""Tests for vacancy detail page and score explain endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def empty_db(tmp_path: Path, monkeypatch) -> str:
    db_path = str(tmp_path / "data" / "test_vacancy.sqlite")
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


def _seed_vacancy(
    db_path: str, vid: str, name: str = "Python Developer", employer: str = "Acme Inc"
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO vacancies"
        " (id, name, employer_name, raw_json, first_seen_at, last_seen_at)"
        " VALUES (?, ?, ?, '{}', datetime('now'), datetime('now'))",
        (vid, name, employer),
    )
    conn.commit()
    conn.close()


# ── Full endpoint returns score/details/review ─────────────────────────


def test_full_endpoint_returns_data(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v1", "Python Dev", "Acme")

    import asyncio

    from src.web.routes import api_vacancy_full

    async def _run():
        resp = await api_vacancy_full("v1")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["id"] == "v1"
        assert body["data"]["name"] == "Python Dev"
        assert "_matched_kw" in body["data"]
        assert "_risk_flags" in body["data"]

    asyncio.run(_run())


def test_full_endpoint_404(empty_db: str) -> None:
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_vacancy_full

    async def _run():
        resp = await api_vacancy_full("nonexistent")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is False

    asyncio.run(_run())


# ── Score explain endpoint has category scores ─────────────────────────


def test_score_explain_endpoint(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v2", "ML Engineer")

    import asyncio

    from src.web.routes import api_vacancy_score_explain

    async def _run():
        resp = await api_vacancy_score_explain("v2")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        data = body["data"]
        assert "has_score" in data
        # Without score details, has_score should be false
        if not data["has_score"]:
            assert "vacancy_id" in data

    asyncio.run(_run())


# ── Description tab loads correctly ────────────────────────────────────


def test_description_is_returned(empty_db: str) -> None:
    _init_db(empty_db)
    conn = sqlite3.connect(empty_db)
    conn.execute(
        "INSERT OR IGNORE INTO vacancies"
        " (id, name, description_text, raw_json, first_seen_at, last_seen_at)"
        " VALUES (?, ?, ?, '{}', datetime('now'), datetime('now'))",
        ("v3", "Test Job", "Looking for a Python developer with Django experience"),
    )
    conn.commit()
    conn.close()

    import asyncio

    from src.web.routes import api_vacancy_full

    async def _run():
        resp = await api_vacancy_full("v3")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert "description_text" in body["data"]
        assert "Django" in (body["data"]["description_text"] or "")

    asyncio.run(_run())


# ── Review controls work ───────────────────────────────────────────────


def test_review_controls_in_full(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v4", "Job Title")

    # Set status
    from src.services.review_service import set_note, set_status

    set_status("v4", "interesting")
    set_note("v4", "Good match")

    import asyncio

    from src.web.routes import api_vacancy_full

    async def _run():
        resp = await api_vacancy_full("v4")
        import json

        body = json.loads(resp.body)
        assert body["data"]["review_status"] == "interesting"
        assert body["data"]["user_notes"] == "Good match"

    asyncio.run(_run())


# ── Apply pack preview/generate works ──────────────────────────────────


def test_apply_pack_preview_endpoint(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v5", "Senior Dev")

    import asyncio

    from src.web.routes import api_vacancy_apply_pack_preview

    async def _run():
        resp = await api_vacancy_apply_pack_preview("v5")
        import json

        body = json.loads(resp.body)
        assert "ok" in body
        assert "message" in body

    asyncio.run(_run())


def test_apply_pack_preview_endpoint_returns_validation_without_writing_files(
    empty_db: str, tmp_path: Path, monkeypatch
) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v5b", "Senior CRM Analyst", "Acme CRM")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        "src.commands.apply_pack.build_cover_letter",
        lambda *a, **kw: {
            "text": "Здравствуйте, команда Acme CRM.\n\nОткликаюсь на позицию Senior CRM Analyst.\n\n"
            "Мой релевантный опыт — внедрение и развитие Bitrix24, CRM-процессов, интеграций с 1С и REST API.\n\n"
            "Судя по описанию роли, особенно релевантны задачи вокруг CRM, Bitrix24.\n\n"
            "Если мой опыт релевантен вашей задаче, готов обсудить детали.",
            "validation": {
                "ok": True,
                "reasons": [],
                "metrics": {"word_count": 42, "anchor_hits": ["CRM", "Bitrix24"]},
            },
            "meta": {"role_family": "bitrix"},
        },
    )

    import asyncio

    from src.web.routes import api_vacancy_apply_pack_preview

    async def _run():
        resp = await api_vacancy_apply_pack_preview("v5b")
        import json

        body = json.loads(resp.body)
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["data"]["letter_validation"]["ok"] is True
        assert "cover_letter" in body["data"]

    asyncio.run(_run())
    assert not (tmp_path / "exports" / "apply_packs").exists()


def test_apply_pack_preview_reject_returns_422_with_reasons(empty_db: str, monkeypatch) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v5c", "Weak Job", "Weak Corp")

    monkeypatch.setattr(
        "src.commands.apply_pack.build_cover_letter",
        lambda *a, **kw: {
            "text": "Hello!\n\nMy profile:\n- Python\n\nLooking forward to discussing further.",
            "validation": {
                "ok": False,
                "reasons": ["contains_generic_phrase", "contains_markdown_artifacts"],
                "metrics": {"word_count": 11, "anchor_hits": []},
            },
            "meta": {"role_family": "default"},
        },
    )

    import asyncio

    from src.web.routes import api_vacancy_apply_pack_preview

    async def _run():
        resp = await api_vacancy_apply_pack_preview("v5c", lang="en")
        import json

        body = json.loads(resp.body)
        assert resp.status_code == 422
        assert body["ok"] is False
        assert body["error_type"] == "validation"
        assert body["data"]["letter_validation"]["reasons"] == [
            "contains_generic_phrase",
            "contains_markdown_artifacts",
        ]

    asyncio.run(_run())


def test_apply_pack_generate_reject_returns_422_with_reasons(empty_db: str, monkeypatch) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v5d", "Weak Job", "Weak Corp")

    monkeypatch.setattr(
        "src.commands.apply_pack.build_cover_letter",
        lambda *a, **kw: {
            "text": "Hello!\n\nMy profile:\n- Python\n\nLooking forward to discussing further.",
            "validation": {
                "ok": False,
                "reasons": ["contains_generic_phrase", "contains_markdown_artifacts"],
                "metrics": {"word_count": 11, "anchor_hits": []},
            },
            "meta": {"role_family": "default"},
        },
    )

    import asyncio

    from src.web.routes import api_vacancy_apply_pack

    async def _run():
        resp = await api_vacancy_apply_pack("v5d")
        import json

        body = json.loads(resp.body)
        assert resp.status_code == 422
        assert body["ok"] is False
        assert body["error_type"] == "validation"
        assert body["data"]["letter_validation"]["reasons"] == [
            "contains_generic_phrase",
            "contains_markdown_artifacts",
        ]

    asyncio.run(_run())


# ── Similar endpoint works with clusters ───────────────────────────────


def test_similar_endpoint(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "v6a", "Python Dev", "Acme")
    _seed_vacancy(empty_db, "v6b", "Senior Python", "Acme")

    import asyncio

    from src.web.routes import api_vacancy_similar

    async def _run():
        resp = await api_vacancy_similar("v6a")
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        data = body["data"]
        assert "cluster" in data
        assert "same_employer" in data
        assert "similar_title" in data
        # Should find same employer
        assert len(data["same_employer"]) >= 1

    asyncio.run(_run())


# ── Page renders ───────────────────────────────────────────────────────


def test_vacancy_page_renders(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "vp1")

    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/vacancy/vp1")
    assert resp.status_code == 200
    assert "vacancy-page" in resp.text
    assert "v-tabs" in resp.text
    assert "overview" in resp.text


# ── Template has all required tabs ─────────────────────────────────────


def test_vacancy_template_has_tabs() -> None:
    html = Path("src/web/templates/vacancy.html").read_text(encoding="utf-8")
    assert "overview" in html
    assert "score" in html
    assert "description" in html
    assert "review" in html
    assert "apply-pack" in html
    assert "similar" in html


# ── Service functions ──────────────────────────────────────────────────


def test_vacancy_service_full(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "sv1", "Test Service")

    from src.services.vacancy_service import get_full

    result = get_full("sv1")
    assert result is not None
    assert result["name"] == "Test Service"
    assert "_matched_kw" in result
    assert "_cluster" not in result  # No clusters


def test_score_explain_service(empty_db: str) -> None:
    _init_db(empty_db)
    _seed_vacancy(empty_db, "se1")

    from src.services.vacancy_service import get_score_explain

    result = get_score_explain("se1")
    assert result is not None
    assert result["has_score"] is False  # No score details yet
