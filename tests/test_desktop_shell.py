"""Tests for desktop shell preparation — scripts, shortcut, docs."""

from __future__ import annotations

from pathlib import Path

# ── Launcher scripts exist ──────────────────────────────────────────────


def test_start_ui_ps1_exists() -> None:
    assert (Path("scripts") / "start_ui.ps1").is_file(), "start_ui.ps1 missing"


def test_start_ui_sh_exists() -> None:
    assert (Path("scripts") / "start_ui.sh").is_file(), "start_ui.sh missing"


def test_start_app_ps1_exists() -> None:
    assert (Path("scripts") / "start_app.ps1").is_file(), "start_app.ps1 missing"


def test_start_app_cmd_exists() -> None:
    assert (Path("scripts") / "start_app.cmd").is_file(), "start_app.cmd missing"


def test_shortcut_script_exists() -> None:
    assert (Path("scripts") / "Create-CareerSignalShortcut.ps1").is_file(), (
        "Create-CareerSignalShortcut.ps1 missing"
    )


# ── No token in scripts ─────────────────────────────────────────────────


def test_no_token_in_start_ui_ps1() -> None:
    content = (Path("scripts") / "start_ui.ps1").read_text(encoding="utf-8")
    assert "HH_APP_ACCESS_TOKEN" not in content
    assert "TOKEN" not in content.upper()


def test_no_token_in_start_ui_sh() -> None:
    content = (Path("scripts") / "start_ui.sh").read_text(encoding="utf-8")
    assert "HH_APP_ACCESS_TOKEN" not in content
    assert "TOKEN" not in content.upper()


def test_no_token_in_start_app_ps1() -> None:
    content = (Path("scripts") / "start_app.ps1").read_text(encoding="utf-8")
    assert "HH_APP_ACCESS_TOKEN" not in content
    assert "TOKEN=" not in content.upper()


def test_no_token_in_shortcut_script() -> None:
    content = (Path("scripts") / "Create-CareerSignalShortcut.ps1").read_text(encoding="utf-8")
    assert "HH_APP_ACCESS_TOKEN" not in content
    assert "TOKEN" not in content.upper()


# ── UI shortcut command ─────────────────────────────────────────────────


def test_ui_shortcut_command_does_not_fail() -> None:
    """python -m src.main ui --shortcut should exit 0."""
    import argparse

    from src.commands.ui import command_ui

    args = argparse.Namespace(
        host="127.0.0.1",
        port=8765,
        open_browser=False,
        allow_lan=False,
        debug=False,
        shortcut=True,
        app_mode=False,
    )
    rc = command_ui(args)
    assert rc == 0


def test_ui_app_mode_command_does_not_fail() -> None:
    """python -m src.main ui --app-mode should exit 0."""
    import argparse

    from src.commands.ui import command_ui

    args = argparse.Namespace(
        host="127.0.0.1",
        port=8765,
        open_browser=False,
        allow_lan=False,
        debug=False,
        shortcut=False,
        app_mode=True,
    )
    rc = command_ui(args)
    assert rc == 0


# ── Docs exist ──────────────────────────────────────────────────────────


def test_desktop_ui_plan_exists() -> None:
    assert (Path("docs") / "DESKTOP_UI_PLAN.md").is_file(), "DESKTOP_UI_PLAN.md missing"


# ── UI command help ─────────────────────────────────────────────────────


def test_ui_help_shows_shortcut_flag(capsys) -> None:
    import sys

    sys.argv = ["src.main", "ui", "--help"]
    try:
        from src.main import main

        main()
    except SystemExit:
        pass
    captured = capsys.readouterr().out
    assert "--shortcut" in captured
    assert "--app-mode" in captured


# ── Status file written (mock) ──────────────────────────────────────────


def test_ui_status_file_written(monkeypatch, tmp_path: Path) -> None:
    """_write_ui_status should create data/ui_status.json."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Patch cwd so Path("data") resolves to tmp_path/data
    monkeypatch.chdir(tmp_path)

    from src.commands.ui import _write_ui_status

    _write_ui_status("127.0.0.1", 8765)

    status_file = data_dir / "ui_status.json"
    assert status_file.exists()

    import json

    data = json.loads(status_file.read_text(encoding="utf-8"))
    assert data["port"] == 8765
    assert data["host"] == "127.0.0.1"
    assert data["version"] == "0.7.0"
    assert data["state"] == "unknown"
    assert data["url"] == "http://127.0.0.1:8765"
    assert "server_started_at" in data


def test_build_ui_url_normalizes_wildcard_host() -> None:
    from src.commands.ui import _build_ui_url

    assert _build_ui_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert _build_ui_url("::1", 8765) == "http://[::1]:8765"
