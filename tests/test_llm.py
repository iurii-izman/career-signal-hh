"""Tests for LLM prompt framework."""

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


# ── CLI contracts ────────────────────────────────────────────────────────────


def test_llm_status_parses() -> None:
    args = parse_args(["llm", "status"])
    assert args.llm_command == "status"


def test_llm_prompt_apply_pack_parses() -> None:
    args = parse_args(["llm", "prompt", "apply-pack", "12345", "--yes"])
    assert args.prompt_command == "apply-pack"
    assert args.vacancy_id == "12345"
    assert args.yes is True


def test_llm_prompt_score_review_parses() -> None:
    args = parse_args(["llm", "prompt", "score-review", "67890"])
    assert args.prompt_command == "score-review"


def test_llm_prompt_preset_improve_parses() -> None:
    args = parse_args(["llm", "prompt", "preset-improve", "ai_rag_remote"])
    assert args.prompt_command == "preset-improve"
    assert args.preset_name == "ai_rag_remote"


def test_llm_export_prompts_parses() -> None:
    args = parse_args(["llm", "export-prompts", "--top", "10"])
    assert args.llm_command == "export-prompts"
    assert args.top == 10


# ── status ───────────────────────────────────────────────────────────────────


def test_llm_status_works(tmp_path: Path, capsys) -> None:
    """llm status must print config and not crash."""
    from argparse import Namespace

    from src.commands.llm import command_llm_status

    result = command_llm_status(Namespace())
    captured = capsys.readouterr().out
    assert result == 0
    assert "LLM Configuration" in captured
    assert "manual" in captured
    assert "Privacy" in captured or "privacy" in captured.lower()


# ── Prompt generation ────────────────────────────────────────────────────────


def test_apply_pack_prompt_generates_file(tmp_path: Path, monkeypatch) -> None:
    """apply-pack prompt must create a .md file."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: load_fixture_yaml("search_presets_valid.yaml"),
    )

    preset_data = load_fixture_yaml("search_presets_valid.yaml")
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from argparse import Namespace

    from src.commands.llm import command_llm_prompt_apply_pack

    result = command_llm_prompt_apply_pack(Namespace(vacancy_id="12345678", yes=True))
    assert result == 0

    prompt_file = Path("exports/llm_prompts/apply_pack_12345678.md")
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "Cover Letter Improvement" in content
    assert "PRIVACY NOTICE" in content


def test_score_review_prompt_generates_file(tmp_path: Path, monkeypatch) -> None:
    """score-review prompt must create a .md file."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: load_fixture_yaml("search_presets_valid.yaml"),
    )

    preset_data = load_fixture_yaml("search_presets_valid.yaml")
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from argparse import Namespace

    from src.commands.llm import command_llm_prompt_score_review

    result = command_llm_prompt_score_review(Namespace(vacancy_id="12345678", yes=True))
    assert result == 0

    prompt_file = Path("exports/llm_prompts/score_review_12345678.md")
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "Score Review" in content


def test_preset_improve_prompt_generates_file(tmp_path: Path, monkeypatch) -> None:
    """preset-improve prompt must create a .md file."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: load_fixture_yaml("search_presets_valid.yaml"),
    )

    from argparse import Namespace

    from src.commands.llm import command_llm_prompt_preset_improve

    result = command_llm_prompt_preset_improve(Namespace(preset_name="ai_rag_test", yes=True))
    assert result == 0

    prompt_file = Path("exports/llm_prompts/preset_improve_ai_rag_test.md")
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "Preset Improvement" in content
    assert "ai_rag_test" in content


# ── Safety ───────────────────────────────────────────────────────────────────


def test_prompt_excludes_token(tmp_path: Path, monkeypatch) -> None:
    """Generated prompts must never include HH_APP_ACCESS_TOKEN."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "SECRET_TOKEN_ABC123")
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: load_fixture_yaml("search_presets_valid.yaml"),
    )

    preset_data = load_fixture_yaml("search_presets_valid.yaml")
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from src.llm_prompts import generate_apply_pack_prompt

    prompt = generate_apply_pack_prompt("12345678")
    assert "SECRET_TOKEN_ABC123" not in prompt
    assert ".env" not in prompt.lower() or "HH_AUTH_MODE" not in prompt


def test_description_truncation_works() -> None:
    """Long descriptions must be truncated per config."""
    from src.llm_prompts import _truncate_desc

    long_text = "x" * 5000
    result = _truncate_desc(long_text, {"max_description_chars": 100})
    assert len(result) <= 103  # 100 + "…" overhead


def test_prompt_no_network_calls(tmp_path: Path, monkeypatch) -> None:
    """LLM commands must make zero network calls."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.llm import command_llm_status

    result = command_llm_status(Namespace())
    assert result == 0
    # No network — works offline
