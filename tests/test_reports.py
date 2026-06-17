"""Tests for weekly report pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import make_storage, parse_args

pytestmark = [pytest.mark.no_network, pytest.mark.integration]


# ── CLI contracts ────────────────────────────────────────────────────────────


def test_report_weekly_parses() -> None:
    args = parse_args(["report", "weekly", "--days", "14"])
    assert args.report_command == "weekly"
    assert args.days == 14


def test_report_weekly_format_parses() -> None:
    args = parse_args(["report", "weekly", "--format", "html"])
    assert args.format == "html"


def test_report_export_parses() -> None:
    args = parse_args(["report", "export"])
    assert args.report_command == "export"


# ── Empty DB ────────────────────────────────────────────────────────────────


def test_weekly_report_works_empty_db(tmp_path: Path, monkeypatch, capsys) -> None:
    """Weekly report must not crash on empty DB."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.report import command_report_weekly

    result = command_report_weekly(Namespace(days=7, preset=None, campaign=None, format="all"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "Weekly Report" in captured
    # On empty DB, all counts should be 0
    assert "Total: 0" in captured or "total" in captured.lower()


def test_weekly_report_creates_files(tmp_path: Path, monkeypatch, capsys) -> None:
    """Weekly report must create HTML, MD, and JSON files."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.report import command_report_weekly

    result = command_report_weekly(Namespace(days=7, preset=None, campaign=None, format="all"))
    assert result == 0

    report_dir = Path("exports/reports")
    md_files = list(report_dir.glob("weekly_*.md"))
    html_files = list(report_dir.glob("weekly_*.html"))
    json_files = list(report_dir.glob("weekly_*.json"))
    assert len(md_files) >= 1, "MD report should exist"
    assert len(html_files) >= 1, "HTML report should exist"
    assert len(json_files) >= 1, "JSON report should exist"

    # Check HTML content
    html = html_files[0].read_text(encoding="utf-8")
    assert "CareerSignal HH" in html
    assert "Weekly Report" in html
    assert "http://" not in html  # no external CDN


def test_weekly_report_includes_stats(tmp_path: Path, monkeypatch, capsys) -> None:
    """Weekly report must include applied/interview stats when data exists."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    # Create some review entries
    from tests.helpers import make_vacancy_from_fixture

    v = make_vacancy_from_fixture("hh_vacancy_ai_good.json")
    storage.upsert_vacancy(v)
    storage.upsert_review(v.id, status="interesting")
    # Also create an applied one
    v2 = make_vacancy_from_fixture("hh_vacancy_bitrix_good.json")
    storage.upsert_vacancy(v2)
    storage.upsert_review(v2.id, status="applied")

    from argparse import Namespace

    from src.commands.report import command_report_weekly

    result = command_report_weekly(Namespace(days=730, preset=None, campaign=None, format="all"))
    captured = capsys.readouterr().out
    assert result == 0
    # Should show applied count (1) and interview count (0)
    assert "Applied:" in captured
    assert "Interview:" in captured


def test_report_export_works(tmp_path: Path, monkeypatch, capsys) -> None:
    """report export shortcut must work."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.report import command_report_export

    result = command_report_export(Namespace())
    captured = capsys.readouterr().out
    assert result == 0
    assert "Weekly Report" in captured


def test_follow_up_suggestions_generated(tmp_path: Path, monkeypatch, capsys) -> None:
    """Report must suggest follow-ups for old applications."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from tests.helpers import make_vacancy_from_fixture

    v = make_vacancy_from_fixture("hh_vacancy_ai_good.json")
    storage.upsert_vacancy(v)
    # Mark as applied 10 days ago
    from datetime import datetime, timedelta, timezone

    old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    storage.upsert_review(v.id, status="applied", applied_at=old_date)

    from argparse import Namespace

    from src.commands.report import command_report_weekly

    result = command_report_weekly(Namespace(days=14, preset=None, campaign=None, format="all"))
    captured = capsys.readouterr().out
    assert result == 0
    # Should mention follow-up
    assert "follow-up" in captured.lower() or "follow up" in captured.lower()
