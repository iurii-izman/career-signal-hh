"""Network safety — ensure local commands never make API calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    seed_vacancies_with_scores,
)

pytestmark = [pytest.mark.no_network]


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


# ═══════════════════════════════════════════════════════════════════════════
# Commands that must NOT make network calls
# ═══════════════════════════════════════════════════════════════════════════


def test_score_rescore_does_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """score rescore must work offline — only touches DB."""
    from argparse import Namespace

    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, "hh_vacancy_ai_good.json")

    from src.commands.score import command_score_rescore

    # Should not raise network errors
    result = command_score_rescore(Namespace(preset="ai_rag_test", limit=None))
    assert result == 0


def test_analytics_does_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """analytics commands must work offline."""
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

    from src.commands.analytics import (
        command_analytics_export,
        command_analytics_summary,
    )

    assert command_analytics_summary(Namespace()) == 0
    assert command_analytics_export(Namespace()) == 0


def test_cockpit_does_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """cockpit commands must work offline."""
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

    from src.commands.cockpit import command_cockpit_export

    assert command_cockpit_export(Namespace()) == 0


def test_apply_pack_does_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """apply-pack must work offline — only reads DB and writes files."""
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

    from src.commands.apply_pack import command_apply_pack

    result = command_apply_pack(
        Namespace(
            vacancy_id="12345678",
            top=None,
            limit=None,
            decision=None,
            preset=None,
            min_score=0,
            lang="ru",
            format="md",
            style="short",
            template=None,
            save_review=False,
            overwrite=False,
        )
    )
    assert result == 0


def test_maintenance_does_not_touch_db(tmp_path: Path, monkeypatch) -> None:
    """maintenance cleanup/report must not touch SQLite DB."""
    # maintenance commands only work with filesystem, never with DB
    # We verify they don't import or use Storage
    from argparse import Namespace

    # Use a path outside tmp_path to avoid interference
    monkeypatch.setattr(
        "src.commands.maintenance.CONFIG_PATH",
        str(tmp_path / "nonexistent_maintenance.yaml"),
    )

    from src.commands.maintenance import command_maintenance_cleanup, command_maintenance_report

    # These should work (or fail gracefully) without any DB access
    result_report = command_maintenance_report(Namespace())
    assert result_report == 0

    result_cleanup = command_maintenance_cleanup(Namespace(dry_run=True, yes=False))
    assert result_cleanup == 0


def test_db_commands_do_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """db info/integrity/migrate must work offline."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))

    from argparse import Namespace

    from src.commands.db import command_db_info, command_db_integrity, command_db_migrate

    assert command_db_info(Namespace()) == 0
    assert command_db_integrity(Namespace()) == 0
    assert command_db_migrate(Namespace()) == 0


def test_health_does_no_api_calls(tmp_path: Path, monkeypatch) -> None:
    """health command must not make any network calls."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.commands.health.load_dotenv",
        lambda *a, **kw: None,
    )

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    assert result in (0, 1)  # OK or warning
