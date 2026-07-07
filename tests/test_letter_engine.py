from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from src.commands.apply_pack import _load_candidate_text, _resolve_template, command_apply_pack
from src.letter_engine import build_cover_letter, validate_cover_letter
from src.utils import json_dumps
from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    make_vacancy_from_fixture,
    seed_vacancies_with_scores,
)


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


def test_build_cover_letter_passes_for_ai_vacancy(tmp_path: Path, monkeypatch) -> None:
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    preset = _load_preset()["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    vacancy = storage.get_vacancy_full("12345678")
    details = storage.get_score_details("12345678")
    assert vacancy is not None
    assert details is not None

    result = build_cover_letter(
        vacancy,
        details,
        lang="ru",
        style="medium",
        template=_resolve_template("ai_rag_remote", "ru", "medium"),
        candidate_name=_load_candidate_text("ru", "name", "ai_rag_remote"),
        candidate_summary=_load_candidate_text("ru", "summary", "ai_rag_remote"),
        location=_load_candidate_text("ru", "location", "ai_rag_remote"),
        availability=_load_candidate_text("ru", "availability", "ai_rag_remote"),
        github=_load_candidate_text("ru", "github", "ai_rag_remote"),
        linkedin=_load_candidate_text("ru", "linkedin", "ai_rag_remote"),
    )

    assert result["validation"]["ok"] is True
    assert "SmartTech AI Lab" in result["text"]
    assert "AI Automation Engineer" in result["text"]
    assert "AI Lead Intake" in result["text"]


def test_build_cover_letter_passes_for_bitrix_vacancy_without_ai_case() -> None:
    vacancy_model = make_vacancy_from_fixture("hh_vacancy_bitrix_good.json")
    vacancy = vacancy_model.model_dump()
    vacancy["key_skills_json"] = json_dumps(vacancy_model.key_skills)
    details = {
        "decision": "strong_match",
        "total_score": 88,
        "matched_keywords_json": json_dumps(
            [
                {"keyword": "Битрикс24", "field": "title"},
                {"keyword": "CRM", "field": "skills"},
                {"keyword": "1С", "field": "skills"},
            ]
        ),
    }

    result = build_cover_letter(
        vacancy,
        details,
        lang="ru",
        style="medium",
        template=_resolve_template("bitrix24_crm_remote", "ru", "medium"),
        candidate_name=_load_candidate_text("ru", "name", "bitrix24_crm_remote"),
        candidate_summary=_load_candidate_text("ru", "summary", "bitrix24_crm_remote"),
        location=_load_candidate_text("ru", "location", "bitrix24_crm_remote"),
        availability=_load_candidate_text("ru", "availability", "bitrix24_crm_remote"),
        github=_load_candidate_text("ru", "github", "bitrix24_crm_remote"),
        linkedin=_load_candidate_text("ru", "linkedin", "bitrix24_crm_remote"),
    )

    assert result["validation"]["ok"] is True
    assert "БизнесАвтоматика" in result["text"]
    assert "AI Lead Intake" not in result["text"]


def test_validate_cover_letter_rejects_generic_markdown_draft() -> None:
    vacancy = {
        "name": "AI Automation Engineer",
        "employer_name": "Acme AI",
    }
    details = {
        "matched_keywords_json": '[{"keyword":"Python"},{"keyword":"RAG"}]',
    }
    text = (
        "Hello!\n\n"
        "My profile:\n"
        "- Python\n\n"
        "Looking forward to discussing further.\n"
        "Best regards,\nCandidate"
    )

    result = validate_cover_letter(
        text,
        vacancy,
        details,
        lang="en",
        style="medium",
        role_family="ai",
        vacancy_keywords=["Python", "RAG"],
        ai_case_required=False,
    )

    assert result["ok"] is False
    assert "contains_generic_phrase" in result["reasons"]
    assert "contains_markdown_artifacts" in result["reasons"]


def test_apply_pack_rejects_weak_letter_before_export(tmp_path: Path, monkeypatch) -> None:
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )
    monkeypatch.chdir(tmp_path)

    preset = _load_preset()["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    monkeypatch.setattr(
        "src.commands.apply_pack.build_cover_letter",
        lambda *a, **kw: {
            "text": "Hello!\n\nMy profile:\n- Python\n\nLooking forward to discussing further.",
            "validation": {
                "ok": False,
                "reasons": ["contains_generic_phrase", "contains_markdown_artifacts"],
                "metrics": {"word_count": 11, "anchor_hits": []},
            },
            "meta": {},
        },
    )

    result = command_apply_pack(
        Namespace(
            vacancy_id="12345678",
            top=None,
            limit=None,
            decision=None,
            preset=None,
            min_score=0,
            lang="en",
            format="both",
            style="medium",
            template=None,
            save_review=True,
            overwrite=False,
            diagnostics=True,
        )
    )

    assert result == 1
    assert not list((tmp_path / "exports" / "apply_packs").glob("12345678*.md"))
    assert not list((tmp_path / "exports" / "apply_packs").glob("12345678*.html"))
    assert not storage.get_review("12345678").get("cover_letter_draft")
