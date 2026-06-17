"""Tests for cockpit v2 — daily action center."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import Vacancy
from src.storage import Storage


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "test_cockpit.sqlite"))


def _make_vacancy(vid: str, name: str, employer: str) -> Vacancy:
    now = datetime.now(timezone.utc).isoformat()
    return Vacancy(
        id=vid,
        name=name,
        employer_name=employer,
        alternate_url=f"https://hh.ru/{vid}",
        raw_json="{}",
        first_seen_at=now,
        last_seen_at=now,
    )


def _add_search_run(storage, profile: str, query: str, hours_ago: int = 1) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO search_runs (profile_name, query, found_count, loaded_count, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (profile, query, 10, 8, ts),
        )
        conn.commit()


# ── Action plan tests ──────────────────────────────────────────────────────


def test_action_plan_recommends_autopilot_when_no_search(tmp_path: Path) -> None:
    """Empty DB with no search runs should recommend autopilot."""
    storage = _make_storage(tmp_path)

    from src.commands.cockpit import _action_cards

    cards = _action_cards(storage)
    titles = [c["title"] for c in cards]
    assert any("search" in t.lower() for t in titles), (
        f"Expected search-related action, got: {titles}"
    )


def test_action_plan_recommends_review_when_queue_exists(tmp_path: Path) -> None:
    """Having strong matches should trigger review next-best."""
    storage = _make_storage(tmp_path)

    v = _make_vacancy("rev1", "Senior Dev", "Acme")
    storage.upsert_vacancy(v)

    from src.models import ScoreResult

    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_score(
        ScoreResult(
            vacancy_id="rev1",
            total_score=90,
            ai_automation_score=45,
            bitrix_1c_score=45,
            best_profile="ai_automation",
            scored_at=now,
        )
    )

    # Add score_details with strong_match decision
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO score_details (vacancy_id, preset_name, total_score, decision, "
            "category_scores_json, matched_keywords_json, excluded_keywords_json, "
            "risk_flags_json, explanation_json, scored_at) "
            "VALUES (?, ?, ?, ?, '{}', '[]', '[]', '[]', '{}', ?)",
            ("rev1", "test", 90, "strong_match", now),
        )
        conn.commit()

    # Add a fresh search so autopilot action isn't triggered
    _add_search_run(storage, "test", "query", 1)

    from src.commands.cockpit import _action_cards

    cards = _action_cards(storage)
    titles = [c["title"] for c in cards]

    # Should have a strong match / review action
    found = any("strong" in t.lower() or "review" in t.lower() for t in titles)
    assert found, f"Expected strong match related action, got actions: {titles}"


def test_action_plan_mentions_backup_when_stale(tmp_path: Path, monkeypatch) -> None:
    """Without recent backup, should recommend db backup."""
    storage = _make_storage(tmp_path)

    _add_search_run(storage, "test", "query", 1)

    # Redirect Path so backup check looks at tmp_path
    original_path = Path

    def _patched_path(p):
        if str(p) == "backups":
            return tmp_path / "backups"
        if str(p).startswith("data/calibration"):
            return tmp_path / "data" / "calibration_suggestions.json"
        return original_path(p)

    monkeypatch.setattr("src.commands.cockpit.Path", _patched_path)

    from src.commands.cockpit import _action_cards

    cards = _action_cards(storage)
    titles = [c["title"] for c in cards]

    # Should have backup action (no backups exist)
    found = any("backup" in t.lower() for t in titles)
    assert found, f"Expected backup action, got: {titles}"


# ── Queue tests ─────────────────────────────────────────────────────────────


def test_queue_renders_without_errors(tmp_path: Path) -> None:
    """_render_queue must not crash on empty or minimal DB."""
    storage = _make_storage(tmp_path)

    from src.commands.cockpit import _render_queue

    html = _render_queue(storage)
    assert isinstance(html, str)
    assert len(html) > 0


# ── Files status tests ──────────────────────────────────────────────────────


def test_files_status_detects_missing_reports() -> None:
    """_render_files_status should list all files, even when missing."""
    from src.commands.cockpit import _render_files_status

    html = _render_files_status()
    assert "Vacancies Report" in html
    assert "Analytics Report" in html
    assert "not generated" in html or "○" in html


# ── Run history tests ───────────────────────────────────────────────────────


def test_run_history_includes_latest_runs(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    _add_search_run(storage, "ai_automation", "python developer", 0)
    _add_search_run(storage, "ai_automation", "LLM engineer", 2)

    from src.commands.cockpit import _render_run_history

    html = _render_run_history(storage)
    assert "python developer" in html
    assert "LLM engineer" in html


def test_run_history_handles_empty_db(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)

    from src.commands.cockpit import _render_run_history

    html = _render_run_history(storage)
    assert isinstance(html, str)
    assert len(html) > 0


# ── Full export test ────────────────────────────────────────────────────────


def test_cockpit_export_works_empty_db(tmp_path: Path, monkeypatch) -> None:
    """cockpit export must not crash on empty DB."""
    storage = _make_storage(tmp_path)

    # Redirect Path("exports/...") to tmp_path/exports
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    original_path = Path

    def _patched_path(p):
        s = str(p)
        if s.startswith("exports"):
            return export_dir / s.replace("exports/", "").replace("exports\\", "")
        if s == "backups":
            return tmp_path / "backups"
        return original_path(p)

    monkeypatch.setattr("src.commands.cockpit.Path", _patched_path)

    # Mock _storage to return our test storage
    monkeypatch.setattr("src.commands.cockpit._storage", lambda: storage)

    from argparse import Namespace

    from src.commands.cockpit import command_cockpit_export

    result = command_cockpit_export(Namespace())
    assert result == 0

    cockpit_html = export_dir / "cockpit.html"
    assert cockpit_html.exists(), f"Cockpit HTML not created at {cockpit_html}"

    content = cockpit_html.read_text(encoding="utf-8")
    assert "CareerSignal HH Cockpit" in content
    assert "Today's Action Plan" in content
    assert "Today's Queue" in content
    assert "Generated Files" in content
    assert "Latest Search Runs" in content


# ── No external resources ───────────────────────────────────────────────────


def test_cockpit_has_no_external_resources(tmp_path: Path, monkeypatch) -> None:
    """The generated HTML must not reference external CDNs or scripts."""
    storage = _make_storage(tmp_path)

    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    original_path = Path

    def _patched_path(p):
        s = str(p)
        if s.startswith("exports"):
            return export_dir / s.replace("exports/", "").replace("exports\\", "")
        if s == "backups":
            return tmp_path / "backups"
        return original_path(p)

    monkeypatch.setattr("src.commands.cockpit.Path", _patched_path)
    monkeypatch.setattr("src.commands.cockpit._storage", lambda: storage)

    from argparse import Namespace

    from src.commands.cockpit import command_cockpit_export

    command_cockpit_export(Namespace())

    content = (export_dir / "cockpit.html").read_text(encoding="utf-8")
    # No external CDNs
    assert "cdn." not in content.lower()
    # No external scripts
    assert "<script src=" not in content.lower()
    # No external stylesheets
    assert '<link rel="stylesheet"' not in content.lower()
    # All styles inline
    assert "<style>" in content
