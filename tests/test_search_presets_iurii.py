from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.scoring_v2 import compute_score_details
from tests.helpers import make_vacancy_from_fixture

pytestmark = [pytest.mark.no_network]


def _load_presets() -> dict:
    return yaml.safe_load(Path("config/search_presets.yaml").read_text(encoding="utf-8")) or {}


def test_required_iurii_presets_exist() -> None:
    presets = _load_presets()["presets"]

    for name in (
        "crm_systems_analyst_remote",
        "bitrix24_crm_remote",
        "integration_analyst_remote",
        "one_c_integration_analyst_remote",
        "no_code_automation_remote",
        "ai_rag_remote",
    ):
        assert name in presets


def test_crm_preset_contains_target_role_terms_and_noise_excludes() -> None:
    preset = _load_presets()["presets"]["crm_systems_analyst_remote"]

    terms = set(preset["search_terms"])
    assert "системный аналитик CRM" in terms
    assert "business systems analyst CRM" in terms

    title_terms = set(preset["include"]["title"])
    assert {"системный аналитик", "integration analyst"}.issubset(title_terms)

    excluded_title = set(preset["exclude"]["title"])
    assert {"sales manager", "project manager", "python developer"}.issubset(excluded_title)


def test_ai_preset_no_longer_targets_generic_rag_engineer_market() -> None:
    preset = _load_presets()["presets"]["ai_rag_remote"]

    terms = set(preset["search_terms"])
    assert "RAG Engineer" not in terms
    assert "LLM Engineer" not in terms
    assert "AI automation analyst" in terms
    assert "CRM AI automation" in terms


def test_bitrix_vacancy_scores_high_for_crm_focused_presets() -> None:
    preset = _load_presets()["presets"]["crm_systems_analyst_remote"]
    vacancy = make_vacancy_from_fixture("hh_vacancy_bitrix_good.json")

    details = compute_score_details(vacancy, {**preset, "_name": "crm_systems_analyst_remote"})
    assert details.total_score >= 70
    assert details.decision in {"strong_match", "queue", "review_later"}


def test_sales_or_pm_noise_is_strongly_penalized_in_crm_preset() -> None:
    from src.models import Vacancy

    vacancy = Vacancy(
        id="noise-1",
        name="Project Manager / Sales Manager CRM",
        employer_name="Noise Corp",
        alternate_url="https://hh.ru/vacancy/noise-1",
        raw_json="{}",
        first_seen_at="2026-07-07T10:00:00+00:00",
        last_seen_at="2026-07-07T10:00:00+00:00",
        schedule_name="remote",
        description_text="Cold calls, account management, upsell, office visits, no analysis.",
        key_skills=["CRM", "Sales"],
    )
    preset = _load_presets()["presets"]["crm_systems_analyst_remote"]

    details = compute_score_details(vacancy, {**preset, "_name": "crm_systems_analyst_remote"})
    assert details.total_score < 50
    assert details.noise_score >= 20
