from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from src.briefing_core import build_briefing_artifact
from tests.helpers import load_fixture_yaml, make_storage, parse_args, seed_vacancies_with_scores

pytestmark = [pytest.mark.no_network]


def _preset_data() -> dict:
    return load_fixture_yaml("search_presets_valid.yaml")["presets"]["ai_rag_test"]


def test_briefing_single_parses() -> None:
    args = parse_args(["briefing", "12345", "--save-review"])
    assert args.vacancy_id == "12345"
    assert args.save_review is True


def test_briefing_top_parses() -> None:
    args = parse_args(["briefing", "--top", "5", "--format", "json"])
    assert args.top == 5
    assert args.format == "json"


def test_briefing_artifact_has_stable_seven_blocks(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    preset = _preset_data()
    vacancy = seed_vacancies_with_scores(
        storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json"
    )[0]
    full = storage.get_vacancy_full(vacancy.id)
    details = storage.get_score_details(vacancy.id)

    artifact = build_briefing_artifact(full or {}, details, lang="ru")
    payload = artifact["payload"]

    assert len(payload["blocks"]) == 7
    assert payload["blocks"][0]["key"] == "snapshot"
    assert payload["blocks"][-1]["key"] == "recommended_action"
    assert "decision" in payload["score"]
    assert "Briefing:" in artifact["markdown"]


def test_briefing_command_saves_report_and_files(tmp_path: Path, monkeypatch) -> None:
    storage = make_storage(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    preset = _preset_data()
    vacancy = seed_vacancies_with_scores(
        storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json"
    )[0]
    storage.upsert_review(vacancy.id, status="new")

    from src.commands.briefing import command_briefing

    result = command_briefing(
        Namespace(
            vacancy_id=vacancy.id,
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
            format="all",
            save_review=True,
        )
    )

    assert result == 0
    report = storage.get_briefing_report(vacancy.id, "ru")
    assert report is not None
    payload = json.loads(report["payload_json"])
    assert payload["vacancy_id"] == vacancy.id
    assert len(payload["blocks"]) == 7

    out_dir = tmp_path / "exports" / "briefings"
    assert list(out_dir.glob(f"{vacancy.id}_*.md"))
    assert list(out_dir.glob(f"{vacancy.id}_*.html"))
    assert list(out_dir.glob(f"{vacancy.id}_*.json"))


def test_briefing_top_creates_index(tmp_path: Path, monkeypatch) -> None:
    storage = make_storage(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    preset = _preset_data()
    vacancies = seed_vacancies_with_scores(
        storage,
        "ai_rag_test",
        preset,
        "hh_vacancy_ai_good.json",
        "hh_vacancy_no_salary.json",
    )
    for vacancy in vacancies:
        storage.upsert_review(vacancy.id, status="new")

    from src.commands.briefing import command_briefing

    result = command_briefing(
        Namespace(
            vacancy_id=None,
            top=2,
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
            format="html",
            save_review=False,
        )
    )

    assert result == 0
    index_path = tmp_path / "exports" / "briefings" / "index.html"
    assert index_path.is_file()
    html = index_path.read_text(encoding="utf-8")
    assert "Briefings (2)" in html
