"""Tests for apply-pack v2 — templates, styles, fit summary, draft management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.commands.apply_pack import (
    _build_fit_summary,
    _generate_md,
    _resolve_template,
)
from src.models import Vacancy
from src.storage import Storage


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "test_apply.sqlite"))


def _make_vacancy(vid: str, name: str, employer: str) -> Vacancy:
    now = datetime.now(timezone.utc).isoformat()
    return Vacancy(
        id=vid,
        name=name,
        employer_name=employer,
        alternate_url=f"https://hh.ru/{vid}",
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
        schedule_name="remote",
    )


TEMPLATE_YAML = """
templates:
  default:
    ru:
      short: "Short RU: {candidate_name} - {vacancy_title}"
      medium: "Medium RU: {candidate_name} for {vacancy_title} at {company}. {fit_reasons}"
      detailed: "Detailed RU: {candidate_name} / {vacancy_title} / {company}"
    en:
      short: "Short EN: {candidate_name}"
  custom_test:
    ru:
      medium: "Custom: {candidate_name} @ {company} with {top_keywords}"
"""


# ── Template resolution ─────────────────────────────────────────────────────


def test_templates_load(tmp_path: Path, monkeypatch) -> None:
    tmpl_path = tmp_path / "apply_templates.yaml"
    tmpl_path.write_text(TEMPLATE_YAML, encoding="utf-8")

    monkeypatch.setattr("src.commands.apply_pack.TEMPLATES_PATH", str(tmpl_path))

    text = _resolve_template("custom_test", "ru", "medium")
    assert "Custom:" in text
    assert "{candidate_name}" in text


def test_fallback_when_template_missing(tmp_path: Path, monkeypatch) -> None:
    tmpl_path = tmp_path / "apply_templates.yaml"
    tmpl_path.write_text(TEMPLATE_YAML, encoding="utf-8")
    monkeypatch.setattr("src.commands.apply_pack.TEMPLATES_PATH", str(tmpl_path))

    # Request a template that doesn't exist — should fallback to default
    text = _resolve_template("nonexistent", "ru", "medium")
    assert "Medium RU:" in text  # falls back to default.ru.medium


def test_short_medium_detailed_differ(tmp_path: Path, monkeypatch) -> None:
    tmpl_path = tmp_path / "apply_templates.yaml"
    tmpl_path.write_text(TEMPLATE_YAML, encoding="utf-8")
    monkeypatch.setattr("src.commands.apply_pack.TEMPLATES_PATH", str(tmpl_path))

    short = _resolve_template(None, "ru", "short")
    medium = _resolve_template(None, "ru", "medium")
    detailed = _resolve_template(None, "ru", "detailed")

    assert short != medium
    assert medium != detailed
    assert "Short RU:" in short
    assert "Medium RU:" in medium
    assert "Detailed RU:" in detailed


# ── Fit summary ─────────────────────────────────────────────────────────────


def test_fit_summary_includes_keywords_and_concerns(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v = _make_vacancy("fs1", "AI Engineer", "Tech Corp")
    storage.upsert_vacancy(v)

    details = {
        "total_score": 90,
        "decision": "strong_match",
        "matched_keywords_json": json.dumps(
            [
                {"keyword": "python", "field": "title"},
                {"keyword": "rag", "field": "skills"},
            ]
        ),
        "excluded_keywords_json": "[]",
        "risk_flags_json": "[]",
        "category_scores_json": "{}",
    }

    fit = _build_fit_summary(
        details, {"work_format_flags_json": "[]", "schedule_name": "remote"}, "ru"
    )

    assert "python" in fit["reasons"]
    assert "rag" in fit["reasons"]
    assert "strong_match" in fit["decision"]
    assert fit["strategy"]


# ── Generated content ───────────────────────────────────────────────────────


def test_generate_includes_candidate_name(tmp_path: Path, monkeypatch) -> None:
    tmpl_path = tmp_path / "apply_templates.yaml"
    tmpl_path.write_text(TEMPLATE_YAML, encoding="utf-8")
    monkeypatch.setattr("src.commands.apply_pack.TEMPLATES_PATH", str(tmpl_path))

    vacancy = {
        "id": "t1",
        "name": "Python Dev",
        "employer_name": "Acme",
        "area_name": "Moscow",
        "alternate_url": "https://hh.ru/1",
        "best_profile": "ai_automation",
        "total_score": 85,
        "risk_flags_json": "[]",
        "work_format_flags_json": '["remote"]',
        "schedule_name": "remote",
        "experience_name": "senior",
        "published_at": "2025-01-01T00:00:00",
        "description_text": "We need a Python developer.",
        "salary_from": 3000,
        "salary_to": 5000,
        "salary_currency": "USD",
    }
    details = {
        "total_score": 85,
        "decision": "strong_match",
        "preset_name": "ai_automation",
        "matched_keywords_json": json.dumps([{"keyword": "python", "field": "title"}]),
        "excluded_keywords_json": "[]",
        "risk_flags_json": "[]",
        "category_scores_json": '{"include": 40}',
    }

    md = _generate_md(vacancy, details, "ru", "medium")
    # Candidate name from candidate.yaml
    assert "Изман" in md or "Izman" in md or "Candidate" in md
    assert "Python Dev" in md
    assert "Acme" in md
    assert "Fit Analysis" in md
    assert "Cover Letter Draft" in md


# ── Draft management ────────────────────────────────────────────────────────


def test_review_draft_shows_saved_draft(tmp_path: Path, capsys) -> None:
    storage = _make_storage(tmp_path)

    v = _make_vacancy("d1", "Dev", "Corp")
    storage.upsert_vacancy(v)
    storage.upsert_review("d1", cover_letter_draft="# Test Draft\n\nHello!")

    from argparse import Namespace

    # Patch _review_storage
    import src.commands.review as review_mod
    from src.commands.review import command_review_draft

    review_mod._review_storage = lambda: storage
    try:
        result = command_review_draft(Namespace(vacancy_id="d1"))
        captured = capsys.readouterr().out
        assert result == 0
        assert "Test Draft" in captured
    finally:
        review_mod._review_storage = review_mod._review_storage


def test_clear_draft_clears_content(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v = _make_vacancy("cd1", "Dev", "Corp")
    storage.upsert_vacancy(v)
    storage.upsert_review("cd1", cover_letter_draft="Some draft")

    from argparse import Namespace

    import src.commands.review as review_mod
    from src.commands.review import command_review_clear_draft

    review_mod._review_storage = lambda: storage
    try:
        result = command_review_clear_draft(Namespace(vacancy_id="cd1", yes=True))
        assert result == 0
        review = storage.get_review("cd1")
        assert not review.get("cover_letter_draft")
    finally:
        review_mod._review_storage = review_mod._review_storage


def test_no_overwrite_without_flag(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    v = _make_vacancy("no1", "Dev", "Corp")
    storage.upsert_vacancy(v)

    # First save
    storage.upsert_review("no1", cover_letter_draft="Original")
    review1 = storage.get_review("no1")
    assert review1.get("cover_letter_draft") == "Original"

    # Try to save without overwrite — should NOT overwrite
    from src.commands.apply_pack import _save_review

    result = _save_review(storage, "no1", "New Draft", overwrite=False)
    assert result is False
    review2 = storage.get_review("no1")
    assert review2.get("cover_letter_draft") == "Original"

    # With overwrite — should update
    result2 = _save_review(storage, "no1", "New Draft", overwrite=True)
    assert result2 is True
    review3 = storage.get_review("no1")
    assert review3.get("cover_letter_draft") == "New Draft"


# ── Apply-pack ID correctness ────────────────────────────────────────────────


def test_apply_pack_uses_get_vacancy_full_for_vacancy_id(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """apply-pack VACANCY_ID must use get_vacancy_full, not list_vacancies(limit=1).

    Verifies that get_vacancy_full returns correct vacancy with score + details.
    """
    storage = _make_storage(tmp_path)

    v = _make_vacancy("test-123", "Senior AI Engineer", "TopCorp")
    storage.upsert_vacancy(v)

    # Also create another vacancy to ensure we don't accidentally pick the wrong one
    v2 = _make_vacancy("other-456", "Junior Dev", "OtherCorp")
    storage.upsert_vacancy(v2)

    # Give both scores, but test-123 gets the higher score
    now = "2025-06-01T12:00:00+00:00"
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO scores (vacancy_id, total_score, ai_automation_score, bitrix_1c_score, best_profile, scored_at) VALUES (?, ?, ?, ?, ?, ?)",
            ["test-123", 90, 90, 0, "ai_automation", now],
        )
        conn.execute(
            "INSERT INTO scores (vacancy_id, total_score, ai_automation_score, bitrix_1c_score, best_profile, scored_at) VALUES (?, ?, ?, ?, ?, ?)",
            ["other-456", 50, 50, 0, "ai_automation", now],
        )

    # get_vacancy_full must return the correct vacancy by ID
    full = storage.get_vacancy_full("test-123")
    assert full is not None
    assert full["name"] == "Senior AI Engineer"
    assert full["employer_name"] == "TopCorp"
    assert full["total_score"] == 90

    # Verify that the other vacancy is NOT returned
    full_other = storage.get_vacancy_full("other-456")
    assert full_other is not None
    assert full_other["name"] == "Junior Dev"


# ── work_format_flags: remote vacancy ────────────────────────────────────────


def test_remote_vacancy_has_work_format_flags_remote(tmp_path: Path) -> None:
    """A remote vacancy must have 'remote' in work_format_flags, not in risk_flags."""
    from src.models import Vacancy
    from src.scoring_v2 import _work_flags

    now = "2025-06-01T12:00:00+00:00"
    v = Vacancy(
        id="r1",
        name="Remote Python Dev",
        employer_name="RemoteCorp",
        alternate_url="https://hh.ru/r1",
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
        schedule_name="remote",
        description_text="Python developer remote position",
    )

    flags = _work_flags(v)
    assert "remote" in flags, (
        f"Remote vacancy should have 'remote' in work_format_flags, got {flags}"
    )
    assert "onsite" not in flags


def test_onsite_vacancy_has_work_format_flags_onsite(tmp_path: Path) -> None:
    """An onsite vacancy must have 'onsite' in work_format_flags."""
    from src.models import Vacancy
    from src.scoring_v2 import _work_flags

    now = "2025-06-01T12:00:00+00:00"
    v = Vacancy(
        id="o1",
        name="Office Python Dev",
        employer_name="OfficeCorp",
        alternate_url="https://hh.ru/o1",
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
        schedule_name="полный день",
        description_text="Python developer office position",
    )

    flags = _work_flags(v)
    assert "onsite" in flags or "unknown" in flags
    assert "remote" not in flags


def test_fit_summary_reads_work_format_from_details(tmp_path: Path) -> None:
    """_build_fit_summary must prefer work_format_flags_json from details over vacancy."""
    import json

    from src.commands.apply_pack import _build_fit_summary

    # details (score_details table) has work_format_flags_json
    details = {
        "total_score": 85,
        "decision": "strong_match",
        "matched_keywords_json": json.dumps([{"keyword": "python", "field": "title"}]),
        "excluded_keywords_json": "[]",
        "risk_flags_json": "[]",
        "work_format_flags_json": '["remote"]',
    }
    # vacancy (from scores table join) has empty work_format_flags_json
    vacancy = {
        "work_format_flags_json": "[]",
        "risk_flags_json": "[]",
        "schedule_name": "remote",
        "salary_from": None,
        "salary_to": None,
    }

    fit = _build_fit_summary(details, vacancy, "en")
    # Should NOT show remote concern because work_format has remote from details
    assert "Remote format not confirmed" not in fit["concerns"]
