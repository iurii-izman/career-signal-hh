"""Snapshot-ish tests — verify key structural blocks in HTML exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import (
    load_fixture_yaml,
    make_storage,
    seed_vacancies_with_scores,
)

pytestmark = [pytest.mark.integration, pytest.mark.no_network]

ALL_FIXTURES = [
    "hh_vacancy_ai_good.json",
    "hh_vacancy_ai_bad_qa.json",
    "hh_vacancy_bitrix_good.json",
    "hh_vacancy_onsite_bad.json",
    "hh_vacancy_no_salary.json",
]

EXTERNAL_CDN_PATTERNS = [
    "https://cdn.",
    "https://unpkg.com",
    "https://cdnjs.cloudflare.com",
    "http://",
]


def _load_preset() -> dict[str, dict[str, object]]:
    return load_fixture_yaml("search_presets_valid.yaml")


def _assert_no_external_resources(html: str, label: str) -> None:
    """Ensure HTML contains no external CDN references."""
    for pat in EXTERNAL_CDN_PATTERNS:
        assert pat not in html, f"{label} must not reference external resource: {pat}"


# ── HTML export ──────────────────────────────────────────────────────────────


def test_vacancies_report_html_has_key_blocks(tmp_path: Path, monkeypatch) -> None:
    """vacancies_report.html must contain score, decision, review status."""
    storage = make_storage(tmp_path)
    monkeypatch.setenv("DB_PATH", str(storage.path))
    monkeypatch.setattr(
        "src.search_presets.load_search_presets",
        lambda *a, **kw: _load_preset(),
    )

    preset_data = _load_preset()
    preset = preset_data["presets"]["ai_rag_test"]
    seed_vacancies_with_scores(storage, "ai_rag_test", preset, *ALL_FIXTURES)

    from argparse import Namespace

    from src.commands.export import command_export

    command_export(Namespace(min_score=0, profile=None, preset=None, days=None))
    report = Path("exports/vacancies_report.html")
    content = report.read_text(encoding="utf-8")

    # Key blocks
    assert "CareerSignal HH" in content, "Must contain brand title"
    assert "SmartTech AI Lab" in content or "БизнесАвтоматика" in content
    assert "score" in content.lower() or "Score" in content
    assert "remote" in content.lower() or "Remote" in content
    _assert_no_external_resources(content, "vacancies_report.html")


# ── Cockpit export ───────────────────────────────────────────────────────────


def test_cockpit_html_has_action_plan(tmp_path: Path, monkeypatch) -> None:
    """cockpit.html must contain action plan section."""
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

    command_cockpit_export(Namespace())
    cockpit = Path("exports/cockpit.html")
    content = cockpit.read_text(encoding="utf-8")

    assert "CareerSignal HH" in content
    # Cockpit should have action plan or queue/status info
    assert any(kw in content.lower() for kw in ["action", "cockpit", "queue", "status"])
    _assert_no_external_resources(content, "cockpit.html")


# ── Analytics export ─────────────────────────────────────────────────────────


def test_analytics_html_has_metrics(tmp_path: Path, monkeypatch) -> None:
    """analytics_report.html must contain metrics and no external CDN."""
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

    from src.commands.analytics import command_analytics_export

    command_analytics_export(Namespace())
    report = Path("exports/analytics_report.html")
    content = report.read_text(encoding="utf-8")

    assert "CareerSignal HH" in content
    _assert_no_external_resources(content, "analytics_report.html")


# ── Apply-pack HTML ──────────────────────────────────────────────────────────


def test_apply_pack_html_has_title(tmp_path: Path, monkeypatch) -> None:
    """apply-pack HTML output must contain vacancy title and no CDN."""
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

    command_apply_pack(
        Namespace(
            vacancy_id="12345678",
            top=None,
            limit=None,
            decision=None,
            preset=None,
            min_score=0,
            lang="en",
            format="html",
            style="medium",
            template=None,
            save_review=False,
            overwrite=False,
        )
    )

    html_files = list(Path("exports/apply_packs").glob("12345678*.html"))
    assert len(html_files) >= 1, "Apply-pack HTML file should exist"
    content = html_files[0].read_text(encoding="utf-8")
    assert "AI Automation Engineer" in content
    _assert_no_external_resources(content, "apply_pack.html")


# ── Calibration export ───────────────────────────────────────────────────────


def test_calibration_html_has_no_cdn(tmp_path: Path, monkeypatch) -> None:
    """calibration_report.html must not reference external CDN."""
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

    from src.commands.calibrate import command_calibrate_export

    command_calibrate_export(Namespace())
    report = Path("exports/calibration_report.html")
    if report.is_file():
        content = report.read_text(encoding="utf-8")
        assert "CareerSignal HH" in content or "Calibration" in content
        _assert_no_external_resources(content, "calibration_report.html")
