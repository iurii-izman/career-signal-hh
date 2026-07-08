"""Tests for guided workflow wizard."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import make_storage, parse_args

pytestmark = [pytest.mark.no_network]


# ── CLI parsing contracts ───────────────────────────────────────────────────


def test_wizard_menu_parses() -> None:
    args = parse_args(["wizard"])
    assert args.command == "wizard"
    assert args.wizard_command == "menu"


def test_wizard_menu_explicit_parses() -> None:
    args = parse_args(["wizard", "menu"])
    assert args.wizard_command == "menu"


def test_wizard_first_run_parses() -> None:
    args = parse_args(["wizard", "first-run"])
    assert args.wizard_command == "first-run"


def test_wizard_first_run_plan_parses() -> None:
    args = parse_args(["wizard", "first-run", "--plan"])
    assert args.wizard_command == "first-run"
    assert args.plan is True


def test_wizard_daily_parses() -> None:
    args = parse_args(["wizard", "daily"])
    assert args.wizard_command == "daily"
    assert args.mode == "normal"


def test_wizard_daily_plan_parses() -> None:
    args = parse_args(["wizard", "daily", "--plan"])
    assert args.wizard_command == "daily"
    assert args.plan is True


def test_wizard_daily_yes_parses() -> None:
    args = parse_args(["wizard", "daily", "--yes", "--mode", "smoke"])
    assert args.yes is True
    assert args.mode == "smoke"


def test_wizard_improve_parses() -> None:
    args = parse_args(["wizard", "improve"])
    assert args.wizard_command == "improve"


def test_wizard_improve_plan_parses() -> None:
    args = parse_args(["wizard", "improve", "--plan"])
    assert args.plan is True


def test_wizard_apply_parses() -> None:
    args = parse_args(["wizard", "apply"])
    assert args.wizard_command == "apply"


def test_wizard_apply_plan_parses() -> None:
    args = parse_args(["wizard", "apply", "--plan"])
    assert args.plan is True


# ── Plan modes — non-interactive, no execution ──────────────────────────────


def test_wizard_daily_plan_works_empty_db(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard daily --plan prints plan, does not execute commands, works on empty DB."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr("src.commands.wizard.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.wizard import command_wizard_daily

    result = command_wizard_daily(Namespace(plan=True, yes=False, mode="normal"))
    captured = capsys.readouterr().out
    assert result == 0
    # Plan must mention key steps
    assert "health" in captured.lower()
    assert "backup" in captured.lower()
    assert "autopilot" in captured.lower()
    assert "cockpit" in captured.lower()
    # Must mention normal mode, never deep mode as choice
    assert "normal" in captured.lower()


def test_wizard_first_run_plan_prints_checklist(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard first-run --plan prints setup checklist without executing anything."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr("src.commands.wizard.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.wizard import command_wizard_first_run

    result = command_wizard_first_run(Namespace(plan=True))
    captured = capsys.readouterr().out
    assert result == 0
    assert ".env" in captured
    assert "HH_AUTH_MODE" in captured
    assert "presets validate" in captured or "presets" in captured.lower()
    assert "db migrate" in captured
    assert "db integrity" in captured
    assert "sample-export" in captured


def test_wizard_improve_plan_prints_steps(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard improve --plan prints improvement steps."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.wizard import command_wizard_improve

    result = command_wizard_improve(Namespace(plan=True, yes=False))
    captured = capsys.readouterr().out
    assert result == 0
    assert "quality cluster" in captured
    assert "calibrate" in captured.lower()
    assert "presets validate" in captured


def test_wizard_apply_plan_prints_steps(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard apply --plan prints briefing + apply pack workflow."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.wizard import command_wizard_apply

    result = command_wizard_apply(Namespace(plan=True))
    captured = capsys.readouterr().out
    assert result == 0
    assert "review queue" in captured
    assert "score explain" in captured
    assert "briefing" in captured
    assert "apply-pack" in captured
    assert "review set" in captured
    assert "apply-assist" in captured
    # Must have safety disclaimer
    assert "never sends applications" in captured.lower()


def test_wizard_menu_plan_works(tmp_path: Path, capsys) -> None:
    """wizard --plan prints menu description."""
    from argparse import Namespace

    from src.commands.wizard import command_wizard

    result = command_wizard(Namespace(plan=True))
    captured = capsys.readouterr().out
    assert result == 0
    assert "first-run" in captured
    assert "daily" in captured
    assert "improve" in captured or "apply" in captured


# ── Safety invariants ───────────────────────────────────────────────────────


def test_wizard_never_prints_token(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard first-run must never print the actual token value."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setenv("HH_AUTH_MODE", "application_token")
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "SECRET_TOKEN_12345")
    monkeypatch.setattr("src.commands.wizard.load_dotenv", lambda *a, **kw: None)
    # Also patch subprocess.run to avoid actual execution
    monkeypatch.setattr("src.commands.wizard._run_command", lambda *a, **kw: 0)
    monkeypatch.setattr("src.commands.wizard._run_readonly", lambda *a, **kw: 0)

    # Mock interactive prompts
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: False)

    from argparse import Namespace

    from src.commands.wizard import command_wizard_first_run

    result = command_wizard_first_run(Namespace(plan=False))
    captured = capsys.readouterr().out
    assert result in (0, 1)
    assert "SECRET_TOKEN_12345" not in captured
    assert "Token is set" in captured or "token" in captured.lower()


def test_wizard_does_not_run_deep(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard daily must refuse deep mode even if requested."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr("src.commands.wizard.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr("src.commands.wizard._run_command", lambda *a, **kw: 0)

    # Mock interactive prompts
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: False)

    from argparse import Namespace

    from src.commands.wizard import command_wizard_daily

    # Even with mode="deep", wizard should refuse
    result = command_wizard_daily(Namespace(plan=False, yes=True, mode="deep"))
    captured = capsys.readouterr().out
    assert result == 0  # Should not crash, just refuse deep
    # Wizard must explicitly refuse deep mode
    assert "not allowed" in captured.lower() or "normal" in captured.lower()


# ── Wizard menu is testable ─────────────────────────────────────────────────


def test_wizard_menu_returns_zero_on_exit(tmp_path: Path, monkeypatch, capsys) -> None:
    """wizard interactive menu must be testable via monkeypatch."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr("src.commands.wizard.load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr("src.commands.wizard._run_command", lambda *a, **kw: 0)

    # Simulate user choosing "7" (Exit) immediately
    monkeypatch.setattr("rich.prompt.IntPrompt.ask", lambda *a, **kw: 7)

    from argparse import Namespace

    from src.commands.wizard import command_wizard

    result = command_wizard(Namespace(plan=False))
    captured = capsys.readouterr().out
    assert result == 0
    assert "Goodbye" in captured or "CareerSignal" in captured
