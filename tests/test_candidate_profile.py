from __future__ import annotations

from pathlib import Path

import yaml


def _load_candidate() -> dict:
    return yaml.safe_load(Path("config/candidate.yaml").read_text(encoding="utf-8")) or {}


def test_candidate_profile_matches_crm_positioning() -> None:
    data = _load_candidate()
    candidate = data["candidate"]

    assert candidate["public_title_ru"] == "Системный аналитик по CRM, интеграциям и AI-автоматизации"
    assert candidate["work_format"]["remote_only"] is True
    assert "Bitrix24" in candidate["experience"]["primary_stack"]
    assert "REST API" in candidate["experience"]["primary_stack"]


def test_candidate_profile_keeps_campaign_compatibility_aliases() -> None:
    profiles = _load_candidate()["candidate"]["profiles"]

    assert "default" in profiles
    assert "ai" in profiles
    assert "bitrix" in profiles
    assert "crm_sa" in profiles
    assert "bitrix24" not in profiles
    assert "Битрикс24" in profiles["bitrix"]["summary_ru"]


def test_candidate_profile_has_cover_letter_constraints_and_ai_case() -> None:
    candidate = _load_candidate()["candidate"]

    banned = set(candidate["constraints"]["do_not_write_in_cover_letter"])
    assert {"Tiraspol", "Moldova", "citizenship"}.issubset(banned)

    ai_case = candidate["real_ai_case"]
    triggers = set(ai_case["trigger_keywords"])
    assert {"ai", "llm", "n8n", "make"}.issubset(triggers)
    assert "AI Lead Intake" in ai_case["ru"]
