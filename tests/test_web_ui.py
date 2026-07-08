"""Tests for local web UI foundation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────


@pytest.fixture
def empty_db(tmp_path: Path, monkeypatch) -> str:
    """Create an empty DB and point DB_PATH at it."""
    db_path = str(tmp_path / "data" / "test_web.sqlite")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.close()
    monkeypatch.setenv("DB_PATH", db_path)
    # Suppress load_dotenv to avoid overriding our env vars
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None, raising=False)
    return db_path


def _init_db(db_path: str) -> None:
    """Run migrations on the test DB."""
    from src.db_migrations import apply_migrations

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    conn.close()


# ── Web app can be imported ──────────────────────────────────────────────


def test_web_app_can_be_imported() -> None:
    """create_app must return a FastAPI instance."""
    from src.web import create_app

    app = create_app()
    assert app is not None
    assert app.title == "CareerSignal HH"
    assert app.version == "0.8.0"


# ── Dashboard service works with empty DB ────────────────────────────────


def test_dashboard_service_empty_db(empty_db: str) -> None:
    """get_dashboard_state must not crash on empty DB."""
    _init_db(empty_db)

    from src.services.app_service import get_dashboard_state

    state = get_dashboard_state()
    assert isinstance(state, dict)
    assert "total_vacancies" in state
    assert state["total_vacancies"] == 0
    assert state["strong_matches"] == 0
    assert state["pending_queue"] == 0
    assert state["applied"] == 0


# ── GET /api/dashboard returns ok ────────────────────────────────────────


def test_api_dashboard_returns_ok(empty_db: str) -> None:
    """Dashboard endpoint must return ok=True with data."""
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_dashboard

    async def _run():
        resp = await api_dashboard()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"] is not None
        assert body["data"]["total_vacancies"] == 0

    asyncio.run(_run())


# ── Token is not present in response ─────────────────────────────────────


def test_health_endpoint_no_token_leak(empty_db: str, monkeypatch) -> None:
    """Health endpoint must never reveal the actual token value."""
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "SECRET_TOKEN_12345")
    monkeypatch.setenv("HH_AUTH_MODE", "application_token")
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_health

    async def _run():
        resp = await api_health()
        import json

        body = json.loads(resp.body)
        body_str = json.dumps(body)
        assert "SECRET_TOKEN_12345" not in body_str
        # Should indicate token is set
        assert "set" in body_str.lower() or "token" in body_str.lower()

    asyncio.run(_run())


def test_health_endpoint_no_user_oauth_token_leak(empty_db: str, monkeypatch) -> None:
    """Health endpoint must not reveal the OAuth token either."""
    monkeypatch.setenv("HH_USER_ACCESS_TOKEN", "USER_SECRET_TOKEN_12345")
    monkeypatch.setenv("HH_AUTH_MODE", "user_oauth")
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_health

    async def _run():
        resp = await api_health()
        import json

        body = json.loads(resp.body)
        body_str = json.dumps(body)
        assert "USER_SECRET_TOKEN_12345" not in body_str
        assert "set" in body_str.lower() or "token" in body_str.lower()

    asyncio.run(_run())


# ── Host safety rejects non-localhost without --allow-lan ────────────────


def test_ui_command_rejects_non_localhost(monkeypatch) -> None:
    """UI command must reject non-localhost bind without --allow-lan."""
    import argparse

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None, raising=False)

    args = argparse.Namespace(
        host="0.0.0.0",
        port=8765,
        open_browser=False,
        allow_lan=False,
        debug=False,
    )

    from src.commands.ui import command_ui

    rc = command_ui(args)
    assert rc == 1  # Must refuse


def test_ui_command_allows_localhost(monkeypatch, capsys) -> None:
    """UI command must accept 127.0.0.1 without --allow-lan."""
    import argparse

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None, raising=False)

    args = argparse.Namespace(
        host="127.0.0.1",
        port=8765,
        open_browser=False,
        allow_lan=False,
        debug=False,
    )

    # Mock uvicorn import so we don't actually start a server
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *a, **kw):
        if name == "uvicorn":
            raise ImportError("Mocked")
        return original_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    from src.commands.ui import command_ui

    rc = command_ui(args)
    # With ImportError raised, it reaches the import block -> exit 1
    # But the host check passes first (127.0.0.1 is allowed)
    assert rc == 1  # Import error = 1
    captured = capsys.readouterr().out
    assert "127.0.0.1" in captured


def test_ui_command_no_browser_suppresses_browser_open(monkeypatch) -> None:
    """--no-browser must suppress browser side effects."""
    import argparse
    import types

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None, raising=False)

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    class FakeApp:
        def __init__(self) -> None:
            self.state = types.SimpleNamespace()

        def on_event(self, _name: str):
            def _decorator(fn):
                return fn

            return _decorator

    monkeypatch.setattr("src.web.create_app", lambda: FakeApp())

    calls: list[dict[str, object]] = []
    fake_uvicorn = types.SimpleNamespace(
        run=lambda app, host, port, log_level, access_log: calls.append(
            {
                "app": app,
                "host": host,
                "port": port,
                "log_level": log_level,
                "access_log": access_log,
            }
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    args = argparse.Namespace(
        host="127.0.0.1",
        port=8765,
        open_browser=True,
        no_browser=True,
        allow_lan=False,
        debug=False,
        shortcut=False,
        app_mode=False,
    )

    from src.commands.ui import command_ui

    rc = command_ui(args)
    assert rc == 0
    assert opened == []
    assert calls and calls[0]["host"] == "127.0.0.1"


# ── Static files exist ───────────────────────────────────────────────────


def test_static_files_exist() -> None:
    """CSS and JS static files must be present."""
    base = Path("src/web/static")
    assert (base / "app.css").is_file(), "app.css missing"
    assert (base / "app.js").is_file(), "app.js missing"


# ── Templates exist ──────────────────────────────────────────────────────


def test_templates_exist() -> None:
    """HTML templates must be present."""
    base = Path("src/web/templates")
    assert (base / "base.html").is_file(), "base.html missing"
    assert (base / "index.html").is_file(), "index.html missing"


# ── UI command parser exists ─────────────────────────────────────────────


def test_ui_parser_exists() -> None:
    """The 'ui' subcommand must be registered in the CLI parser."""
    from src.cli import build_parser

    parser = build_parser()
    # Find 'ui' in subcommands
    ui_found = False
    for action in parser._actions:
        if hasattr(action, "choices") and "ui" in (action.choices or {}):
            ui_found = True
            break
    assert ui_found, "ui subcommand not registered in CLI parser"


# ── Review queue endpoint ────────────────────────────────────────────────


def test_review_queue_endpoint_empty(empty_db: str) -> None:
    """Review queue endpoint must return empty list on empty DB."""
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_queue

    async def _run():
        resp = await api_queue(min_score=70, decision=None, limit=20, new_only=True)
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"] == []

    asyncio.run(_run())


def test_briefing_endpoint_returns_ok(empty_db: str, monkeypatch) -> None:
    """Briefing endpoint must return ok=True when generation succeeds."""
    _init_db(empty_db)

    import asyncio
    import json

    from src.web import routes

    monkeypatch.setattr(
        routes.review_service,
        "generate_briefing_for",
        lambda vacancy_id: {
            "ok": True,
            "message": f"Briefing generated for {vacancy_id}",
            "data": {"vacancy_id": vacancy_id, "decision": "strong_match"},
        },
    )

    async def _run():
        resp = await routes.api_vacancy_briefing("vac-1")
        body = json.loads(resp.body)
        assert resp.status_code == 200
        assert body["ok"] is True
        assert body["data"]["vacancy_id"] == "vac-1"

    asyncio.run(_run())


# ── Health endpoint structure ────────────────────────────────────────────


def test_health_endpoint_structure(empty_db: str, monkeypatch) -> None:
    """Health endpoint must return list of check dicts."""
    monkeypatch.setenv("HH_AUTH_MODE", "none")
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "")
    _init_db(empty_db)

    import asyncio

    from src.web.routes import api_health

    async def _run():
        resp = await api_health()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)
        # Should have at least version check
        checks_by_name = {c["check"]: c for c in body["data"]}
        assert "Version" in checks_by_name
        assert checks_by_name["Version"]["status"] == "OK"

    asyncio.run(_run())


# ── UI command help ──────────────────────────────────────────────────────


def test_ui_command_help(capsys) -> None:
    """python -m src.main ui --help must print usage."""
    import sys

    from src.main import main

    sys.argv = ["src.main", "ui", "--help"]
    try:
        main()
    except SystemExit:
        pass
    captured = capsys.readouterr().out
    assert "ui" in captured
    assert "--host" in captured
    assert "--port" in captured
    assert "--no-browser" in captured
