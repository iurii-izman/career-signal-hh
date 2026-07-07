"""Tests for health command — read-only sanity checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.storage import Storage


def _make_empty_storage(db_path: str) -> Storage:
    """Return a Storage pointed at an empty temporary DB."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.close()
    return Storage(db_path)


# ── Health runs on empty DB ──────────────────────────────────────────────────


def test_health_works_on_empty_db(tmp_path: Path, monkeypatch, capsys) -> None:
    """health command must not crash on empty/missing DB."""
    db_path = str(tmp_path / "data" / "test_health.sqlite")
    _make_empty_storage(db_path)

    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setattr("src.commands.health.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    captured = capsys.readouterr().out
    assert result == 0, f"health exit code should be 0, got {result}"
    assert "Version" in captured
    assert "DB integrity" in captured


# ── Health does not print token ──────────────────────────────────────────────


def test_health_does_not_print_token(tmp_path: Path, monkeypatch, capsys) -> None:
    """health must never print the actual token value."""
    db_path = str(tmp_path / "data" / "test_health.sqlite")
    _make_empty_storage(db_path)

    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("HH_AUTH_MODE", "application_token")
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "SECRET_TOKEN_VALUE_12345")
    monkeypatch.setattr("src.commands.health.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    captured = capsys.readouterr().out
    # Token value itself must never appear
    assert "SECRET_TOKEN_VALUE_12345" not in captured
    assert result in (0, 1)  # exit code depends on other checks
    # But "set" indicator may appear
    assert "token=set" in captured or "set" in captured.lower(), (
        "Should indicate token is set without revealing value"
    )


def test_health_does_not_print_user_oauth_token(tmp_path: Path, monkeypatch, capsys) -> None:
    """health must never print the actual OAuth token value."""
    db_path = str(tmp_path / "data" / "test_health.sqlite")
    _make_empty_storage(db_path)

    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("HH_AUTH_MODE", "user_oauth")
    monkeypatch.setenv("HH_USER_ACCESS_TOKEN", "USER_SECRET_TOKEN_VALUE_12345")
    monkeypatch.setattr("src.commands.health.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    captured = capsys.readouterr().out
    assert "USER_SECRET_TOKEN_VALUE_12345" not in captured
    assert result in (0, 1)
    assert "token=set" in captured or "set" in captured.lower()


# ── Health exit code 1 on critical failures ──────────────────────────────────


def test_health_fails_on_missing_required_config(tmp_path: Path, monkeypatch, capsys) -> None:
    """health must exit 1 when scoring_rules.yaml is missing (required)."""
    db_path = str(tmp_path / "data" / "test_health.sqlite")
    _make_empty_storage(db_path)

    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setattr("src.commands.health.load_dotenv", lambda *a, **kw: None)

    # Ensure scoring_rules.yaml does not exist in tmp_path
    monkeypatch.chdir(tmp_path)

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    captured = capsys.readouterr().out
    assert result == 1, f"health should exit 1 when required config missing, got {result}"
    assert "scoring_rules.yaml" in captured
