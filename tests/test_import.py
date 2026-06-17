"""Tests for manual vacancy import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import make_storage, parse_args

pytestmark = [pytest.mark.no_network, pytest.mark.integration]


# ═══════════════════════════════════════════════════════════════════════════
# CLI parsing
# ═══════════════════════════════════════════════════════════════════════════


def test_import_vacancy_parses() -> None:
    args = parse_args(
        [
            "import",
            "vacancy",
            "--title",
            "Python Dev",
            "--company",
            "Acme",
            "--url",
            "https://example.com/job/1",
            "--preset",
            "ai_rag_remote",
        ]
    )
    assert args.import_command == "vacancy"
    assert args.title == "Python Dev"
    assert args.preset == "ai_rag_remote"


def test_import_csv_parses() -> None:
    args = parse_args(["import", "csv", "vacancies.csv"])
    assert args.import_command == "csv"
    assert args.path == "vacancies.csv"


def test_import_jsonl_parses() -> None:
    args = parse_args(["import", "jsonl", "data.jsonl"])
    assert args.import_command == "jsonl"


def test_import_text_file_parses() -> None:
    args = parse_args(["import", "text-file", "vacancies.txt"])
    assert args.import_command == "text-file"


# ═══════════════════════════════════════════════════════════════════════════
# Single vacancy import
# ═══════════════════════════════════════════════════════════════════════════


def test_manual_vacancy_creates_record(tmp_path: Path, monkeypatch, capsys) -> None:
    """Importing a manual vacancy must create a DB record."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_vacancy

    result = command_import_vacancy(
        Namespace(
            title="Senior Python Dev",
            company="Acme Corp",
            url="https://linkedin.com/jobs/view/12345",
            area="Remote",
            description="Looking for a senior Python developer",
            salary_from=200000,
            salary_to=300000,
            currency="RUR",
            schedule="remote",
            preset="ai_rag_remote",
            notes="Found on LinkedIn",
        )
    )
    captured = capsys.readouterr().out
    assert result == 0
    assert "Imported" in captured or "Updated" in captured

    # Verify DB record
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT * FROM vacancies WHERE alternate_url = ?",
            ("https://linkedin.com/jobs/view/12345",),
        ).fetchone()
    assert row is not None
    assert row["name"] == "Senior Python Dev"
    assert row["employer_name"] == "Acme Corp"
    assert row["salary_from"] == 200000
    assert row["schedule_name"] == "remote"

    # Check that review note was saved
    review = storage.get_review(row["id"])
    assert review.get("user_notes") == "Found on LinkedIn"


def test_same_url_imports_idempotently(tmp_path: Path, monkeypatch) -> None:
    """Importing the same URL twice must update, not duplicate."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_vacancy

    # First import
    command_import_vacancy(
        Namespace(
            title="Dev 1",
            company="Corp",
            url="https://example.com/job/42",
            area="",
            description="",
            salary_from=None,
            salary_to=None,
            currency="",
            schedule="",
            preset=None,
            notes="",
        )
    )

    # Second import — same URL, different title
    command_import_vacancy(
        Namespace(
            title="Dev 1 Updated",
            company="Corp Updated",
            url="https://example.com/job/42",
            area="",
            description="",
            salary_from=None,
            salary_to=None,
            currency="",
            schedule="",
            preset=None,
            notes="Updated notes",
        )
    )

    # Should be only ONE vacancy with this URL
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM vacancies WHERE alternate_url = ?",
            ("https://example.com/job/42",),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Dev 1 Updated"
    assert rows[0]["employer_name"] == "Corp Updated"

    # Review note should be updated
    review = storage.get_review(rows[0]["id"])
    assert review.get("user_notes") == "Updated notes"


# ═══════════════════════════════════════════════════════════════════════════
# CSV import
# ═══════════════════════════════════════════════════════════════════════════


def test_csv_import_works(tmp_path: Path, monkeypatch) -> None:
    """CSV import must create multiple vacancies."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "title,company,url,area,description,preset,notes\n"
        "AI Engineer,SmartTech,https://ex.com/1,Remote,AI role,ai_rag_remote,Good fit\n"
        "CRM Analyst,BitrixCo,https://ex.com/2,Moscow,CRM role,bitrix24_crm_remote,\n",
        encoding="utf-8",
    )

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_csv

    result = command_import_csv(Namespace(path=str(csv_path)))
    assert result == 0

    # Both should exist
    v1 = storage.find_by_url("https://ex.com/1")
    v2 = storage.find_by_url("https://ex.com/2")
    assert v1 is not None
    assert v2 is not None

    # First one should have scoring + notes
    details = storage.get_score_details(v1)
    assert details is not None
    review = storage.get_review(v1)
    assert review.get("user_notes") == "Good fit"


def test_csv_import_skips_invalid(tmp_path: Path, monkeypatch) -> None:
    """CSV rows missing required fields must be skipped."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    csv_path = tmp_path / "bad.csv"
    csv_path.write_text(
        "title,company,url\n"
        ",,https://ex.com/1\n"  # missing title
        "Good,Corp,https://ex.com/2\n",
        encoding="utf-8",
    )

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_csv

    result = command_import_csv(Namespace(path=str(csv_path)))
    assert result == 1  # 1 error (skipped row)

    # Only the valid one should exist
    assert storage.find_by_url("https://ex.com/2") is not None


# ═══════════════════════════════════════════════════════════════════════════
# JSONL import
# ═══════════════════════════════════════════════════════════════════════════


def test_jsonl_import_works(tmp_path: Path, monkeypatch) -> None:
    """JSONL import must work."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    jsonl_path = tmp_path / "test.jsonl"
    jsonl_path.write_text(
        json.dumps(
            {
                "title": "Dev 1",
                "company": "C1",
                "url": "https://ex.com/j1",
                "preset": "ai_rag_remote",
            }
        )
        + "\n"
        + json.dumps({"title": "Dev 2", "company": "C2", "url": "https://ex.com/j2"})
        + "\n",
        encoding="utf-8",
    )

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_jsonl

    result = command_import_jsonl(Namespace(path=str(jsonl_path)))
    assert result == 0

    assert storage.find_by_url("https://ex.com/j1") is not None
    assert storage.find_by_url("https://ex.com/j2") is not None


# ═══════════════════════════════════════════════════════════════════════════
# Text file import
# ═══════════════════════════════════════════════════════════════════════════


def test_text_file_import_works(tmp_path: Path, monkeypatch) -> None:
    """Text file import with pipe-delimited format must work."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    txt_path = tmp_path / "test.txt"
    txt_path.write_text(
        "# Comments are skipped\n"
        "Senior Dev | Acme | https://ex.com/t1 | Remote | Python AI role\n"
        "CRM Lead | BitrixCo | https://ex.com/t2\n",
        encoding="utf-8",
    )

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_text_file

    result = command_import_text_file(Namespace(path=str(txt_path)))
    assert result == 0

    assert storage.find_by_url("https://ex.com/t1") is not None
    assert storage.find_by_url("https://ex.com/t2") is not None


def test_text_file_skips_invalid_lines(tmp_path: Path, monkeypatch) -> None:
    """Text file with insufficient fields must skip those lines."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    txt_path = tmp_path / "bad.txt"
    txt_path.write_text(
        "Only Two Fields | Missing URL\nGood | Corp | https://ex.com/g1\n",
        encoding="utf-8",
    )

    from argparse import Namespace

    from src.commands.import_vacancy import command_import_text_file

    result = command_import_text_file(Namespace(path=str(txt_path)))
    assert result == 1  # one error

    assert storage.find_by_url("https://ex.com/g1") is not None
