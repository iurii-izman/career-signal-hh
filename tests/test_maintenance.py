"""Tests for maintenance — retention report and cleanup."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.commands.maintenance import _is_protected, _scan_category

# ── Protection ──────────────────────────────────────────────────────────────


def test_dotenv_is_protected() -> None:
    assert _is_protected(Path(".env")) is True
    assert _is_protected(Path("project/.env")) is True


def test_sqlite_in_data_is_protected() -> None:
    assert _is_protected(Path("data/vacancies.sqlite")) is True
    assert _is_protected(Path("data/anything.sqlite")) is True


def test_calibration_json_is_protected() -> None:
    assert _is_protected(Path("data/calibration_suggestions.json")) is True


def test_regular_log_is_not_protected() -> None:
    assert _is_protected(Path("logs/daily_2025.log")) is False
    assert _is_protected(Path("backups/vacancies_2025.sqlite")) is False


# ── Scan ────────────────────────────────────────────────────────────────────


def test_scan_handles_empty_dir(tmp_path: Path) -> None:
    d = tmp_path / "empty_logs"
    d.mkdir()
    scan = _scan_category(str(d), "*.log", days=30, count=None)
    assert scan["total_count"] == 0
    assert scan["delete_count"] == 0


def test_scan_keeps_recent_by_days(tmp_path: Path) -> None:
    d = tmp_path / "logs"
    d.mkdir()

    recent = d / "recent.log"
    recent.write_text("recent")
    # Set mtime to 1 day ago
    recent_mtime = (datetime.now() - timedelta(days=1)).timestamp()
    os.utime(str(recent), (recent_mtime, recent_mtime))

    old = d / "old.log"
    old.write_text("old")
    old_mtime = (datetime.now() - timedelta(days=60)).timestamp()
    os.utime(str(old), (old_mtime, old_mtime))

    scan = _scan_category(str(d), "*.log", days=30, count=None)
    assert scan["total_count"] == 2
    assert scan["delete_count"] == 1
    assert old in scan["to_delete"]
    assert recent in scan["keep"]


def test_scan_respects_count(tmp_path: Path) -> None:
    d = tmp_path / "backups"
    d.mkdir()

    for i in range(5):
        f = d / f"backup_{i}.sqlite"
        f.write_text(f"backup {i}")
        mtime = (datetime.now() - timedelta(days=i)).timestamp()
        os.utime(str(f), (mtime, mtime))

    scan = _scan_category(str(d), "*.sqlite", days=None, count=3)
    assert scan["total_count"] == 5
    assert scan["keep_count"] == 3
    assert scan["delete_count"] == 2


# ── Integration: report and cleanup commands ───────────────────────────────


def test_report_works_empty(tmp_path: Path, monkeypatch, capsys) -> None:
    """maintenance report must not crash on empty dirs."""
    # Create minimal config
    config_path = tmp_path / "maintenance.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "retention": {
                    "logs": {
                        "days": 30,
                        "path": str(tmp_path / "nonexistent_logs"),
                        "pattern": "*.log",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.commands.maintenance.CONFIG_PATH", str(config_path))

    from argparse import Namespace

    from src.commands.maintenance import command_maintenance_report

    result = command_maintenance_report(Namespace())
    captured = capsys.readouterr().out
    assert result == 0
    assert "logs" in captured.lower() or "Files" in captured


def test_cleanup_dry_run_deletes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    """dry-run must not delete anything."""
    d = tmp_path / "logs"
    d.mkdir()
    old = d / "old.log"
    old.write_text("old")
    old_mtime = (datetime.now() - timedelta(days=60)).timestamp()
    os.utime(str(old), (old_mtime, old_mtime))

    config_path = tmp_path / "maintenance.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "retention": {
                    "logs": {"days": 30, "path": str(d), "pattern": "*.log"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.commands.maintenance.CONFIG_PATH", str(config_path))

    from argparse import Namespace

    from src.commands.maintenance import command_maintenance_cleanup

    result = command_maintenance_cleanup(Namespace(dry_run=True, yes=False))
    captured = capsys.readouterr().out
    assert result == 0
    assert old.exists(), "dry-run must not delete files"
    assert "DRY RUN" in captured


def test_cleanup_deletes_old_log_with_yes(tmp_path: Path, monkeypatch) -> None:
    """cleanup --yes should actually delete old files."""
    d = tmp_path / "logs"
    d.mkdir()
    old = d / "old.log"
    old.write_text("old")
    old_mtime = (datetime.now() - timedelta(days=60)).timestamp()
    os.utime(str(old), (old_mtime, old_mtime))

    recent = d / "recent.log"
    recent.write_text("recent")
    recent_mtime = (datetime.now() - timedelta(days=1)).timestamp()
    os.utime(str(recent), (recent_mtime, recent_mtime))

    config_path = tmp_path / "maintenance.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "retention": {
                    "logs": {"days": 30, "path": str(d), "pattern": "*.log"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.commands.maintenance.CONFIG_PATH", str(config_path))

    from argparse import Namespace

    from src.commands.maintenance import command_maintenance_cleanup

    result = command_maintenance_cleanup(Namespace(dry_run=False, yes=True))
    assert result == 0
    assert not old.exists(), "old log should be deleted"
    assert recent.exists(), "recent log should be kept"


def test_latest_backup_preserved(tmp_path: Path, monkeypatch) -> None:
    """Latest N backups should be kept even if old."""
    d = tmp_path / "backups"
    d.mkdir()

    for i in range(8):
        f = d / f"vacancies_{i}.sqlite"
        f.write_text(f"backup {i}")
        mtime = (datetime.now() - timedelta(days=100 + i)).timestamp()
        os.utime(str(f), (mtime, mtime))

    config_path = tmp_path / "maintenance.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "retention": {
                    "backups": {"days": 30, "count": 3, "path": str(d), "pattern": "*.sqlite"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.commands.maintenance.CONFIG_PATH", str(config_path))

    from argparse import Namespace

    from src.commands.maintenance import command_maintenance_cleanup

    result = command_maintenance_cleanup(Namespace(dry_run=False, yes=True))
    assert result == 0

    remaining = list(d.glob("*.sqlite"))
    assert len(remaining) == 3, f"Should keep 3 latest backups, got {len(remaining)}"


def test_env_and_sqlite_never_deleted(tmp_path: Path, monkeypatch) -> None:
    """Protected files must never be deleted even if old."""
    d = tmp_path / "data"
    d.mkdir()

    db = d / "test.sqlite"
    db.write_text("db")
    db_mtime = (datetime.now() - timedelta(days=365)).timestamp()
    os.utime(str(db), (db_mtime, db_mtime))

    env = tmp_path / ".env"
    env.write_text("SECRET=1")
    env_mtime = (datetime.now() - timedelta(days=365)).timestamp()
    os.utime(str(env), (env_mtime, env_mtime))

    config_path = tmp_path / "maintenance.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(
            {
                "retention": {
                    "data_test": {"days": 1, "path": str(d), "pattern": "*.sqlite"},
                    "root_test": {"days": 1, "path": str(tmp_path), "pattern": ".env"},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("src.commands.maintenance.CONFIG_PATH", str(config_path))

    from argparse import Namespace

    from src.commands.maintenance import command_maintenance_cleanup

    result = command_maintenance_cleanup(Namespace(dry_run=False, yes=True))
    assert result == 0
    assert db.exists(), "SQLite in data/ must never be deleted"
    assert env.exists(), ".env must never be deleted"
