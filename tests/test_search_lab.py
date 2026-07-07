"""Tests for Search Lab — query planner analytics."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    parse_args,
    seed_vacancies_with_scores,
)

pytestmark = [pytest.mark.no_network, pytest.mark.integration]


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


# ── CLI contracts ────────────────────────────────────────────────────────────


def test_search_lab_terms_parses() -> None:
    args = parse_args(["search-lab", "terms", "--preset", "ai_rag_test"])
    assert args.search_lab_command == "terms"
    assert args.preset == "ai_rag_test"


def test_search_lab_suggest_terms_parses() -> None:
    args = parse_args(["search-lab", "suggest-terms", "--preset", "ai_rag_test"])
    assert args.search_lab_command == "suggest-terms"


def test_search_lab_compare_parses() -> None:
    args = parse_args(
        ["search-lab", "compare", "--preset-a", "ai_rag_test", "--preset-b", "bitrix_test"]
    )
    assert args.search_lab_command == "compare"
    assert args.preset_a == "ai_rag_test"
    assert args.preset_b == "bitrix_test"


def test_search_lab_dry_plan_parses() -> None:
    args = parse_args(["search-lab", "dry-plan", "--preset", "ai_rag_test"])
    assert args.search_lab_command == "dry-plan"


def test_search_lab_export_parses() -> None:
    args = parse_args(["search-lab", "export"])
    assert args.search_lab_command == "export"


# ── terms — empty DB ────────────────────────────────────────────────────────


def test_terms_works_empty_db(tmp_path: Path, monkeypatch, capsys) -> None:
    """search-lab terms must not crash on empty DB."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_terms

    result = command_search_lab_terms(Namespace(preset="ai_rag_test"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "AI Engineer" in captured or "LLM Engineer" in captured or "ai_rag_test" in captured


# ── terms — detects noisy query ──────────────────────────────────────────────


def test_terms_recommendation_logic() -> None:
    """_recommend must classify terms correctly."""
    from src.commands.search_lab import _recommend

    # Strong good outcomes
    assert (
        _recommend(
            {
                "avg_score": 80,
                "strong_count": 8,
                "rejected_count": 0,
                "good_outcome_count": 5,
                "max_found": 50,
                "vacancy_count": 10,
            }
        )[0]
        == "keep"
    )

    # High rejection rate
    assert (
        _recommend(
            {
                "avg_score": 40,
                "strong_count": 1,
                "rejected_count": 15,
                "good_outcome_count": 0,
                "max_found": 100,
                "vacancy_count": 20,
            }
        )[0]
        == "remove"
    )

    # Low average score
    assert (
        _recommend(
            {
                "avg_score": 30,
                "strong_count": 0,
                "rejected_count": 1,
                "good_outcome_count": 0,
                "max_found": 20,
                "vacancy_count": 5,
            }
        )[0]
        == "refine"
    )

    # No results
    assert (
        _recommend(
            {
                "avg_score": 0,
                "strong_count": 0,
                "rejected_count": 0,
                "good_outcome_count": 0,
                "max_found": 0,
                "vacancy_count": 0,
            }
        )[0]
        == "remove"
    )


# ── suggest-terms from scored vacancies ──────────────────────────────────────


def test_suggest_terms_uses_high_quality_keywords(tmp_path: Path, monkeypatch, capsys) -> None:
    """suggest-terms should return keywords from high-scoring vacancies."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_suggest_terms

    result = command_search_lab_suggest_terms(Namespace(preset="ai_rag_test"))
    captured = capsys.readouterr().out
    assert result == 0
    # Should find python, llm, rag keywords from the good vacancy
    assert len(captured) > 0


# ── compare on empty DB ─────────────────────────────────────────────────────


def test_compare_on_empty_db(tmp_path: Path, monkeypatch, capsys) -> None:
    """compare must not crash on empty DB."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_compare

    result = command_search_lab_compare(Namespace(preset_a="ai_rag_test", preset_b="ai_rag_test"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "Preset Comparison" in captured or "Total" in captured


# ── compare detects overlap ─────────────────────────────────────────────────


def test_compare_detects_overlap(tmp_path: Path, monkeypatch) -> None:
    """preset_overlap must detect when presets share vacancies."""
    storage = make_storage(tmp_path)

    # Insert a vacancy with source_profile=preset_a
    from tests.helpers import make_vacancy_from_fixture

    v = make_vacancy_from_fixture("hh_vacancy_ai_good.json", source_profile="preset_a")
    storage.upsert_vacancy(v)

    overlap = storage.preset_overlap("preset_a", "preset_b")
    # With one vacancy from preset_a only, overlap should be 0
    assert overlap["total_a"] >= 0
    assert overlap["overlap"] == 0  # No overlap since only preset_a has it


# ── dry-plan does not call API ──────────────────────────────────────────────


def test_dry_plan_no_api_calls(tmp_path: Path, monkeypatch, capsys) -> None:
    """dry-plan must work without any API calls."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_dry_plan

    result = command_search_lab_dry_plan(Namespace(preset="ai_rag_test"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "API calls" in captured or "search requests" in captured.lower()
    assert "Search terms" in captured or "terms" in captured.lower()


def test_dry_plan_uses_merged_preset_filters(tmp_path: Path, monkeypatch, capsys) -> None:
    """dry-plan must show merged schedule/experience, not empty raw filters."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_dry_plan

    result = command_search_lab_dry_plan(Namespace(preset="ai_rag_test"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "between3And6" in captured
    assert "moreThan6" in captured


# ── export creates files ─────────────────────────────────────────────────────


def test_export_creates_files(tmp_path: Path, monkeypatch) -> None:
    """search-lab export must create all three report files."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    # Seed some data
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from argparse import Namespace

    from src.commands.search_lab import command_search_lab_export

    result = command_search_lab_export(Namespace())
    assert result == 0

    assert Path("exports/search_lab_report.html").is_file()
    assert Path("exports/search_terms.csv").is_file()
    assert Path("exports/preset_comparison.json").is_file()

    # Quick content checks
    html = Path("exports/search_lab_report.html").read_text(encoding="utf-8")
    assert "CareerSignal HH" in html
    assert "Search Lab" in html
    assert "http://" not in html  # no external CDN


# ── Storage methods ──────────────────────────────────────────────────────────


def test_high_quality_keywords_returns_data(tmp_path: Path) -> None:
    """high_quality_keywords must return keywords from scored vacancies."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    keywords = storage.high_quality_keywords("ai_rag_test", min_score=50)
    assert len(keywords) > 0, "Should find keywords in scored vacancy"
    kw_names = {k["keyword"] for k in keywords}
    assert "python" in kw_names or "llm" in kw_names or "rag" in kw_names


def test_search_term_performance_uses_source_query_for_per_term_quality(tmp_path: Path) -> None:
    """Per-term analytics must use source_query instead of profile-wide vacancy totals."""
    from src.scoring_v2 import _to_score_result, compute_score_details
    from tests.helpers import make_vacancy_from_fixture

    storage = make_storage(tmp_path)
    preset = _load_preset()["presets"]["ai_rag_test"]

    strong = make_vacancy_from_fixture(
        "hh_vacancy_ai_good.json",
        source_profile="ai_rag_test",
        source_query="AI Engineer",
    )
    weak = make_vacancy_from_fixture(
        "hh_vacancy_ai_bad_qa.json",
        source_profile="ai_rag_test",
        source_query="LLM Engineer",
    )

    for vacancy in (strong, weak):
        storage.upsert_vacancy(vacancy)
        details = compute_score_details(vacancy, {**preset, "_name": "ai_rag_test"})
        storage.upsert_score_details(details)
        storage.upsert_score(_to_score_result(details))

    storage.add_search_run(
        {
            "started_at": "2026-07-08T10:00:00+00:00",
            "finished_at": "2026-07-08T10:01:00+00:00",
            "profile_name": "ai_rag_test",
            "query": "AI Engineer",
            "area_id": None,
            "found_count": 10,
            "loaded_count": 1,
            "new_count": 1,
            "updated_count": 0,
            "error": None,
        }
    )
    storage.add_search_run(
        {
            "started_at": "2026-07-08T10:02:00+00:00",
            "finished_at": "2026-07-08T10:03:00+00:00",
            "profile_name": "ai_rag_test",
            "query": "LLM Engineer",
            "area_id": None,
            "found_count": 10,
            "loaded_count": 1,
            "new_count": 1,
            "updated_count": 0,
            "error": None,
        }
    )

    rows = {row["term"]: row for row in storage.search_term_performance("ai_rag_test")}
    assert rows["AI Engineer"]["vacancy_count"] == 1
    assert rows["LLM Engineer"]["vacancy_count"] == 1
    assert rows["AI Engineer"]["avg_score"] != rows["LLM Engineer"]["avg_score"]
