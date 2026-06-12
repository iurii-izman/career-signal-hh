from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.exporter_csv import export_csv, export_jsonl
from src.exporter_html import export_html
from src.models import Vacancy
from src.storage import Storage


def _storage_with_vacancy(tmp_path: Path) -> Storage:
    storage = Storage(str(tmp_path / "reviews.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="vacancy-1",
            name="Python Automation Engineer",
            employer_name="Example",
            area_name="Remote",
            alternate_url="https://hh.ru/vacancy/1",
            published_at=now,
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    return storage


def test_vacancy_without_review_is_new(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)

    assert storage.get_review("vacancy-1")["status"] == "new"
    assert storage.list_vacancies()[0]["review_status"] == "new"


def test_set_review_status_and_invalid_status(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)

    storage.set_review_status("vacancy-1", "interesting")
    assert storage.get_review("vacancy-1")["status"] == "interesting"

    with pytest.raises(ValueError, match="Недопустимый review status"):
        storage.set_review_status("vacancy-1", "unknown")


def test_note_does_not_overwrite_status(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)
    storage.set_review_status("vacancy-1", "maybe")

    storage.set_review_note("vacancy-1", "Проверить требования")

    review = storage.get_review("vacancy-1")
    assert review["status"] == "maybe"
    assert review["user_notes"] == "Проверить требования"


def test_mark_applied_sets_status_and_date(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)

    storage.mark_applied("vacancy-1", "2026-06-12")

    review = storage.get_review("vacancy-1")
    assert review["status"] == "applied"
    assert review["applied_at"] == "2026-06-12"


def test_next_action_and_vacancy_update_preserve_review(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)
    storage.set_review_status("vacancy-1", "interview")
    storage.set_next_action("vacancy-1", "Prepare questions", "2026-06-20")
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="vacancy-1",
            name="Updated title",
            archived=True,
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    review = storage.get_review("vacancy-1")
    assert review["status"] == "interview"
    assert review["next_action"] == "Prepare questions"
    assert review["next_action_at"] == "2026-06-20"


def test_exports_include_review_fields(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)
    storage.upsert_review(
        "vacancy-1",
        status="applied",
        priority=1,
        user_notes="Ручная заметка",
        applied_at="2026-06-12",
        next_action="Follow up",
        next_action_at="2026-06-20",
    )
    rows = storage.list_vacancies()
    csv_path = tmp_path / "vacancies.csv"
    jsonl_path = tmp_path / "vacancies.jsonl"
    html_path = tmp_path / "vacancies.html"

    export_csv(rows, csv_path)
    export_jsonl(rows, jsonl_path)
    export_html(rows, html_path)

    with csv_path.open(encoding="utf-8") as handle:
        csv_row = next(csv.DictReader(handle))
    json_row = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    html = html_path.read_text(encoding="utf-8")
    assert csv_row["review_status"] == "applied"
    assert csv_row["user_notes"] == "Ручная заметка"
    assert json_row["review_status"] == "applied"
    assert json_row["next_action"] == "Follow up"
    assert 'data-review="applied"' in html
    assert "Ручная заметка" in html
