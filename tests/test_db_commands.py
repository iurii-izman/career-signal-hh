from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from src.commands import db
from src.models import Vacancy
from src.storage import Storage


def _record_console(monkeypatch) -> Console:
    output = Console(record=True, width=160)
    monkeypatch.setattr(db, "console", output)
    return output


def test_db_info_on_empty_db(tmp_path: Path, monkeypatch) -> None:
    """db info should work on an empty database."""
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "empty.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    Storage(db_path)  # create tables
    output = _record_console(monkeypatch)

    result = db.command_db_info(Namespace())
    rendered = output.export_text()

    assert result == 0
    assert "Total vacancies" in rendered
    assert "0" in rendered


def test_db_info_on_populated_db(tmp_path: Path, monkeypatch) -> None:
    """db info should show correct counts."""
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "populated.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    storage = Storage(db_path)
    now = datetime.now(timezone.utc).isoformat()

    # Add a real vacancy
    storage.upsert_vacancy(
        Vacancy(
            id="real-1",
            name="Real Vacancy",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    # Add a sample vacancy
    storage.upsert_vacancy(
        Vacancy(
            id="sample-test",
            name="Sample Vacancy",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    storage.set_review_status("real-1", "interesting")

    output = _record_console(monkeypatch)
    result = db.command_db_info(Namespace())
    rendered = output.export_text()

    assert result == 0
    assert "Total vacancies" in rendered
    assert "2" in rendered
    assert "Sample vacancies" in rendered
    assert "1" in rendered
    assert "Total reviews" in rendered


def test_db_purge_samples_removes_data(tmp_path: Path, monkeypatch) -> None:
    """db purge-samples should remove sample-* vacancies, scores, and reviews."""
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "purge.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    storage = Storage(db_path)
    now = datetime.now(timezone.utc).isoformat()

    storage.upsert_vacancy(
        Vacancy(
            id="real-1",
            name="Real",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    storage.upsert_vacancy(
        Vacancy(
            id="sample-1",
            name="Sample 1",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    storage.upsert_vacancy(
        Vacancy(
            id="sample-2",
            name="Sample 2",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    storage.set_review_status("sample-1", "interesting")

    output = _record_console(monkeypatch)
    result = db.command_db_purge_samples(Namespace(yes=True))
    rendered = output.export_text()

    assert result == 0
    assert "Удалено" in rendered

    # Verify real vacancy still exists, samples are gone
    assert storage.vacancy_exists("real-1")
    assert not storage.vacancy_exists("sample-1")
    assert not storage.vacancy_exists("sample-2")


def test_db_purge_samples_noop_when_none(tmp_path: Path, monkeypatch) -> None:
    """db purge-samples should report no samples when none exist."""
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "no_samples.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    storage = Storage(db_path)
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="real-1",
            name="Real",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    output = _record_console(monkeypatch)
    result = db.command_db_purge_samples(Namespace(yes=True))
    rendered = output.export_text()

    assert result == 0
    assert "не найдено" in rendered.lower() or "no" in rendered.lower()


def test_db_backup_creates_file(tmp_path: Path, monkeypatch) -> None:
    """db backup should create a copy in backups/."""
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "to_backup.sqlite")
    monkeypatch.setenv("DB_PATH", db_path)
    Storage(db_path)  # create tables

    output = _record_console(monkeypatch)
    result = db.command_db_backup(Namespace())
    rendered = output.export_text()

    assert result == 0
    assert "Бэкап создан" in rendered

    # Verify backup file exists
    backups = list(Path("backups").glob("vacancies_*.sqlite"))
    assert len(backups) >= 1


def test_db_backup_fails_on_missing_db(tmp_path: Path, monkeypatch) -> None:
    """db backup should fail gracefully when DB doesn't exist."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/nonexistent.sqlite")

    output = _record_console(monkeypatch)
    result = db.command_db_backup(Namespace())
    rendered = output.export_text()

    assert result == 1
    assert "нечего бэкапить" in rendered.lower() or "не найдена" in rendered.lower()


def test_sample_export_uses_separate_db(tmp_path: Path, monkeypatch) -> None:
    """sample-export should not write to the production DB."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/prod.sqlite")
    prod_storage = Storage("data/prod.sqlite")
    now = datetime.now(timezone.utc).isoformat()
    prod_storage.upsert_vacancy(
        Vacancy(
            id="prod-1",
            name="Production",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    config = tmp_path / "config"
    config.mkdir()
    (config / "scoring_rules.yaml").write_text(
        """
profiles:
  ai_automation:
    keywords:
      python: 20
  bitrix_1c:
    keywords:
      bitrix: 20
risks:
  sales_only:
    keywords: ["менеджер по продажам"]
    penalty: 35
""".strip(),
        encoding="utf-8",
    )

    from src.commands import sample

    output = Console(record=True, width=160)
    monkeypatch.setattr(sample, "console", output)

    assert sample.command_sample_export(Namespace(db=None)) == 0

    # Production DB should still have only 1 vacancy (the prod one)
    assert prod_storage.list_vacancies()[0]["id"] == "prod-1"
    assert len(prod_storage.list_vacancies()) == 1

    # Sample DB should have 6 vacancies
    sample_storage = Storage("data/sample_vacancies.sqlite")
    assert len(sample_storage.list_vacancies()) == 6
