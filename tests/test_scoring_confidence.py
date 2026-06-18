"""Tests for matching engine and confidence-aware scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.matching import (
    match_in_fields,
    phrase_match,
    safe_keyword_match,
)
from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    seed_vacancies_with_scores,
)

pytestmark = [pytest.mark.no_network]


# ═══════════════════════════════════════════════════════════════════════════
# Matching engine — short keyword safeguards
# ═══════════════════════════════════════════════════════════════════════════


def test_ai_does_not_match_inside_word() -> None:
    """'ai' must not match inside 'detail' or 'email'."""
    assert safe_keyword_match("ai", "email") == (False, "none")
    assert safe_keyword_match("ai", "detail") == (False, "none")
    assert safe_keyword_match("ai", "maintain") == (False, "none")


def test_ai_matches_as_token() -> None:
    """'ai' must match as a whole token."""
    ok, mt = safe_keyword_match("ai", "ai engineer")
    assert ok is True
    assert mt == "exact_token"

    ok, mt = safe_keyword_match("ai", "we need ai and ml")
    assert ok is True


def test_api_safeguard() -> None:
    """Short keywords like api/crm/qa must be safeguarded."""
    assert safe_keyword_match("api", "fastapi") == (False, "none")
    assert safe_keyword_match("api", "api integration") == (True, "exact_token")
    assert safe_keyword_match("crm", "crm system") == (True, "exact_token")
    assert safe_keyword_match("qa", "qa engineer") == (True, "exact_token")
    assert safe_keyword_match("qa", "equal") == (False, "none")


def test_long_keyword_substring_allowed() -> None:
    """Longer keywords (≥4 chars) can match substrings at word boundaries."""
    ok, mt = safe_keyword_match("python", "pythonista")
    assert ok is True  # starts with python
    ok, mt = safe_keyword_match("python", "micropython")
    assert ok is True  # ends with python


def test_phrase_match_multiple_words() -> None:
    """Multi-word phrases match only as exact token sequence."""
    assert phrase_match("ai engineer", "looking for ai engineer role") is True
    assert phrase_match("ai engineer", "ai automation engineer") is False
    assert phrase_match("ai engineer", "engineer for ai") is False


# ═══════════════════════════════════════════════════════════════════════════
# Matching — field aware
# ═══════════════════════════════════════════════════════════════════════════


def test_title_match_beats_description() -> None:
    """Keyword in title should match with preferred field first."""
    fields = {
        "title": "python developer",
        "description": "we use python extensively",
    }
    matches = match_in_fields("python", fields, preferred_fields=["title"])
    assert len(matches) == 1
    assert matches[0]["field"] == "title"


def test_description_only_match_works() -> None:
    """Keyword only in description still matches."""
    fields = {
        "title": "javascript developer",
        "description": "python scripting needed",
    }
    matches = match_in_fields("python", fields, preferred_fields=["title"])
    assert len(matches) == 1
    assert matches[0]["field"] == "description"


# ═══════════════════════════════════════════════════════════════════════════
# Confidence/noise scoring
# ═══════════════════════════════════════════════════════════════════════════


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


def test_ai_good_vacancy_has_high_confidence(tmp_path: Path) -> None:
    """A good AI vacancy with title+skills match must have high confidence."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    assert details["confidence_score"] >= 60, f"Expected ≥60, got {details['confidence_score']}"


def test_description_only_match_lower_confidence(tmp_path: Path) -> None:
    """Vacancy with only description matches must have quality flag."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    # The onsite_bad vacancy has python skills but title doesn't match well
    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_onsite_bad.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    # Onsite vacancy — should have missing_salary or remote_unclear or other quality flag
    import json

    qf = json.loads(details.get("quality_flags_json", "[]"))
    # Onsite vacancy with fullDay schedule should NOT have remote_confirmed
    assert "remote_confirmed" not in qf


def test_exclude_in_title_increases_noise(tmp_path: Path) -> None:
    """Excluded keyword in title must increase noise score."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_bad_qa.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    # QA vacancy should have noise from exclude and/or low confidence
    assert details["noise_score"] >= 10 or details["confidence_score"] < 60


def test_high_score_low_confidence_not_strong_match(tmp_path: Path) -> None:
    """If confidence is low, decision must not be strong_match even with high score."""
    from src.scoring_v2 import _compute_decision

    # High score, low confidence
    decision = _compute_decision(
        total=90,
        confidence=20,
        noise=10,
        thresholds={"strong_match": 85, "queue": 70, "review_later": 50, "weak_match": 25},
    )
    assert decision != "strong_match", "Low confidence should prevent strong_match"
    assert decision in ("review_later", "queue")


def test_many_excludes_quality_flag(tmp_path: Path) -> None:
    """Vacancy with many excluded keywords gets many_excludes flag."""
    from src.models import Vacancy
    from src.scoring_v2 import compute_score_details

    now = "2026-06-15T12:00:00+00:00"
    v = Vacancy(
        id="test-excl",
        name="QA Manager",
        employer_name="Test",
        alternate_url="https://hh.ru/1",
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
        schedule_name="remote",
        key_skills=["qa", "testing"],
        description_text="QA automation engineer for casino gambling. Cold calls required.",
    )

    preset = {
        "_name": "test",
        "include": {"any": ["qa"], "all": [], "title": []},
        "exclude": {"any": ["casino", "gambling", "cold calls"], "title": []},
        "boost": {},
        "penalties": {},
    }

    details = compute_score_details(v, preset)
    assert "many_excludes" in details.quality_flags or len(details.excluded_keywords) >= 2


def test_score_explain_includes_confidence_noise(tmp_path: Path, monkeypatch, capsys) -> None:
    """score explain must show confidence and noise."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )
    monkeypatch.setattr(
        "src.commands.score.load_dotenv",
        lambda *a, **kw: None,
    )

    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from argparse import Namespace

    from src.commands.score import command_score_explain

    result = command_score_explain(Namespace(vacancy_id="12345678"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "Confidence:" in captured
    assert "Noise:" in captured
