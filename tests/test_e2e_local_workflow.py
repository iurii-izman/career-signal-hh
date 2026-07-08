"""End-to-end workflow test — runs the full local pipeline without network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    seed_vacancies_with_scores,
)

# Mark all tests in this module as integration + no_network
pytestmark = [pytest.mark.integration, pytest.mark.no_network]

ALL_FIXTURES = [
    "hh_vacancy_ai_good.json",
    "hh_vacancy_ai_bad_qa.json",
    "hh_vacancy_bitrix_good.json",
    "hh_vacancy_onsite_bad.json",
    "hh_vacancy_no_salary.json",
]


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


# ═══════════════════════════════════════════════════════════════════════════
# Full local workflow
# ═══════════════════════════════════════════════════════════════════════════


def test_e2e_full_local_workflow(tmp_path: Path, monkeypatch, capsys) -> None:
    """Run the complete local pipeline: seed → score → export → briefing → pack → health."""
    storage = make_storage(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[1]
    for name in [
        "candidate.yaml",
        "apply_templates.yaml",
        "search_presets.yaml",
        "scoring_rules.yaml",
    ]:
        (config_dir / name).write_text((repo_root / "config" / name).read_text(encoding="utf-8"))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )
    monkeypatch.setattr(
        "src.commands.health.load_dotenv",
        lambda *a, **kw: None,
    )

    preset_data = _load_preset()
    ai_preset = preset_data["presets"]["ai_rag_test"]

    # ── 1. Seed 5 fixture vacancies with scores ─────────────────────────
    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", ai_preset, *ALL_FIXTURES)

    # Create review entries so queue returns them
    for v in vacs:
        storage.upsert_review(v.id, status="new")

    # ── 2. Export vacancies ─────────────────────────────────────────────
    from argparse import Namespace

    from src.commands.export import command_export

    result = command_export(Namespace(min_score=0, profile=None, preset=None, days=None))
    assert result == 0
    report = Path("exports/vacancies_report.html")
    assert report.is_file(), "HTML export should exist"
    content = report.read_text(encoding="utf-8")
    assert "CareerSignal HH" in content
    assert "remote" in content.lower() or "Remote" in content

    # ── 3. Review queue ─────────────────────────────────────────────────
    from src.commands.review import command_review_queue

    result = command_review_queue(
        Namespace(
            decision=None,
            min_score=0,
            preset=None,
            profile=None,
            status=None,
            limit=20,
            remote_only=False,
            with_salary=False,
            hide_risk=False,
            new_only=False,
            dedupe=False,
        )
    )
    captured = capsys.readouterr().out
    assert result == 0
    assert "results" in captured.lower() or "вакансий" in captured.lower()

    # ── 4. Briefing + apply-pack for top vacancy ───────────────────────
    from src.commands.apply_pack import command_apply_pack
    from src.commands.briefing import command_briefing

    # Get a vacancy ID that has a score
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT vacancy_id FROM score_details WHERE decision='strong_match' LIMIT 1"
        ).fetchone()
    if row:
        briefing_result = command_briefing(
            Namespace(
                vacancy_id=row["vacancy_id"],
                top=None,
                limit=None,
                decision=None,
                preset=None,
                status=None,
                min_score=0,
                remote_only=False,
                with_salary=False,
                hide_risk=False,
                new_only=False,
                lang="ru",
                format="md",
                save_review=True,
            )
        )
        assert briefing_result == 0
        assert list((tmp_path / "exports" / "briefings").glob(f"{row['vacancy_id']}_*.md"))
        result = command_apply_pack(
            Namespace(
                vacancy_id=row["vacancy_id"],
                top=None,
                limit=None,
                decision=None,
                preset=None,
                min_score=0,
                lang="en",
                format="md",
                style="medium",
                template=None,
                save_review=False,
                overwrite=False,
                diagnostics=False,
            )
        )
        captured2 = capsys.readouterr().out
        assert result == 0
        assert row["vacancy_id"] in captured2

    # ── 5. Analytics export ─────────────────────────────────────────────
    from src.commands.analytics import command_analytics_export

    result = command_analytics_export(Namespace())
    assert result == 0
    analytics_file = Path("exports/analytics_report.html")
    assert analytics_file.is_file(), "Analytics export should exist"

    # ── 6. Cockpit export ───────────────────────────────────────────────
    from src.commands.cockpit import command_cockpit_export

    result = command_cockpit_export(Namespace())
    assert result == 0
    cockpit_file = Path("exports/cockpit.html")
    assert cockpit_file.is_file(), "Cockpit export should exist"

    # ── 7. DB integrity ─────────────────────────────────────────────────
    from src.commands.db import command_db_integrity

    result = command_db_integrity(Namespace())
    assert result == 0

    # ── 8. Health ───────────────────────────────────────────────────────
    from src.commands.health import command_health

    result = command_health(Namespace())
    assert result == 0


# ═══════════════════════════════════════════════════════════════════════════
# Scoring correctness with fixtures
# ═══════════════════════════════════════════════════════════════════════════


def test_ai_good_scores_high(tmp_path: Path) -> None:
    """AI good vacancy must score >= 70 against ai_rag_test preset."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    assert details["total_score"] >= 70, f"Expected >=70, got {details['total_score']}"
    assert details["decision"] in ("strong_match", "queue")


def test_ai_bad_qa_scores_low(tmp_path: Path) -> None:
    """QA vacancy should score low against ai_rag_test (excluded keywords)."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_bad_qa.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    # QA should be heavily penalised
    assert details["total_score"] < 60, f"QA vacancy should score low, got {details['total_score']}"


def test_bitrix_good_scores_high(tmp_path: Path) -> None:
    """Bitrix vacancy must score well against bitrix preset."""
    storage = make_storage(tmp_path)
    # Load live preset (not fixture) for bitrix
    from src.search_presets import get_preset

    bitrix_preset = get_preset("bitrix24_crm_remote")
    if bitrix_preset is None:
        pytest.skip("bitrix24_crm_remote preset not found")

    vacs = seed_vacancies_with_scores(
        storage, "bitrix24_crm_remote", bitrix_preset, "hh_vacancy_bitrix_good.json"
    )
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    assert details["total_score"] >= 60, f"Expected >=60, got {details['total_score']}"


def test_onsite_bad_has_remote_penalty(tmp_path: Path) -> None:
    """Onsite vacancy should have remote penalty when remote_only=true."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_onsite_bad.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    # Check work_format_flags — should NOT have "remote"
    wf = json.loads(details.get("work_format_flags_json", "[]"))
    assert "remote" not in wf, f"Onsite vacancy should not have remote flag, got {wf}"


def test_no_salary_has_concern(tmp_path: Path) -> None:
    """No-salary vacancy should still score but have salary concern."""
    storage = make_storage(tmp_path)
    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]

    vacs = seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_no_salary.json")
    assert len(vacs) == 1

    details = storage.get_score_details(vacs[0].id)
    assert details is not None
    # Score should be reasonable (has LLM/RAG keywords)
    assert details["total_score"] > 0
    # salary category should be 0 since no salary
    cat = json.loads(details.get("category_scores_json", "{}"))
    assert cat.get("salary", 0) == 0
