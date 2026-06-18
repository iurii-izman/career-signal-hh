from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from src import config
from src.commands import search as search_cmds
from src.hh_client import HHBudgetExceeded, HHClient
from src.models import Vacancy
from src.services import search_runner
from src.storage import Storage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_console(monkeypatch: pytest.MonkeyPatch) -> Console:
    output = Console(record=True, width=160)
    monkeypatch.setattr(search_cmds, "console", output)
    monkeypatch.setattr(search_runner, "console", output)
    return output


def _make_minimal_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create minimal search_profiles.yaml and switch CWD."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.delenv("HH_APP_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("DB_PATH", "data/test.sqlite")
    monkeypatch.setenv("HH_DELAY_MIN_SECONDS", "0")
    monkeypatch.setenv("HH_DELAY_MAX_SECONDS", "0")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    profiles_path = config_dir / "search_profiles.yaml"

    profiles_path.write_text(
        """
profiles:
  ai_automation:
    enabled: true
    queries: [python, automation]
    areas: [1]
    params: {}
  bitrix_1c:
    enabled: true
    queries: [bitrix]
    areas: [2]
    params: {}
""".strip(),
        encoding="utf-8",
    )
    return profiles_path


def _make_scoring_rules(tmp_path: Path) -> Path:
    rules_path = tmp_path / "config" / "scoring_rules.yaml"
    rules_path.write_text(
        """
profiles:
  ai_automation:
    keywords:
      python: 20
      automation: 15
  bitrix_1c:
    keywords:
      bitrix: 20
risks:
  sales_only:
    keywords: ["менеджер по продажам"]
    penalty: 35
""".strip(),
        encoding="utf-8",
    )
    return rules_path


# ---------------------------------------------------------------------------
# Search mode config tests
# ---------------------------------------------------------------------------


def test_smoke_mode_sets_small_limits() -> None:
    """Smoke mode should have small budget, single profile, small pages."""
    preset = config.SEARCH_MODES["smoke"]
    assert preset["max_pages"] == 1
    assert preset["per_page"] == 10
    assert preset["max_requests_per_run"] == 50
    assert preset["max_detail_fetches_per_run"] == 25
    assert preset["single_profile"] is True
    assert preset["confirm"] is False


def test_normal_mode_sets_medium_limits() -> None:
    """Normal mode should have medium budget."""
    preset = config.SEARCH_MODES["normal"]
    assert preset["max_pages"] == 2
    assert preset["per_page"] == 25
    assert preset["max_requests_per_run"] == 250
    assert preset["max_detail_fetches_per_run"] == 150
    assert preset["single_profile"] is False
    assert preset["confirm"] is False


def test_deep_mode_requires_confirmation() -> None:
    """Deep mode should require confirmation and have large budget."""
    preset = config.SEARCH_MODES["deep"]
    assert preset["max_pages"] == 3
    assert preset["per_page"] == 50
    assert preset["max_requests_per_run"] == 800
    assert preset["max_detail_fetches_per_run"] == 500
    assert preset["confirm"] is True


def test_mode_overrides() -> None:
    """CLI overrides should take precedence over mode defaults."""
    args = Namespace(
        mode="normal",
        max_pages=5,
        per_page=100,
        force_details=False,
        verbose=False,
        yes=False,
        adhoc=False,
        preset=None,
        include=None,
        exclude=None,
        remote_only=None,
    )
    config = search_cmds._resolve_search_config(args)
    assert config["max_pages"] == 5  # overridden
    assert config["per_page"] == 100  # overridden
    assert config["max_requests_per_run"] == 250  # from mode
    assert config["max_detail_fetches_per_run"] == 150  # from mode


# ---------------------------------------------------------------------------
# Request budget tests
# ---------------------------------------------------------------------------


def test_budget_stops_requests() -> None:
    """HHClient should raise HHBudgetExceeded when total budget exhausted."""
    client = HHClient(auth_mode="none")
    client.set_budget(max_requests=2, max_details=10)

    assert client.can_request("search")
    client._record_request("search")
    assert client.can_request("search")
    client._record_request("search")
    # Now at 2/2 — should be exhausted
    assert not client.can_request("search")

    with pytest.raises(HHBudgetExceeded):
        client._request("/nonexistent", request_type="search")


def test_budget_stops_detail_requests() -> None:
    """Detail budget should be independent from total budget."""
    client = HHClient(auth_mode="none")
    client.set_budget(max_requests=100, max_details=2)

    assert client.can_request("detail")
    client._record_request("detail")
    assert client.can_request("detail")
    client._record_request("detail")
    # Detail budget exhausted
    assert not client.can_request("detail")
    # Total budget still available
    assert client.can_request("search")


def test_budget_summary() -> None:
    """budget_summary should reflect current state."""
    client = HHClient(auth_mode="none")
    client.set_budget(max_requests=50, max_details=25)
    client._record_request("search")
    client._record_request("detail")

    summary = client.budget_summary()
    assert summary["total"] == 2
    assert summary["search"] == 1
    assert summary["detail"] == 1
    assert summary["max_requests"] == 50
    assert summary["max_details"] == 25


def test_budget_none_allows_all() -> None:
    """When budget is not set, everything is allowed."""
    client = HHClient(auth_mode="none")
    assert client.budget is None
    assert client.can_request("search")
    assert client.can_request("detail")

    # _record_request should be a no-op when budget is None
    client._record_request("search")
    assert client.stats_search_requests == 0  # not incremented without budget


# ---------------------------------------------------------------------------
# Smart detail fetching tests
# ---------------------------------------------------------------------------


def test_new_vacancy_fetches_detail(tmp_path: Path) -> None:
    """A vacancy not in DB should always trigger a detail fetch."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    assert storage.detail_needed("nonexistent-id") is True


def test_existing_vacancy_with_description_skips_detail(tmp_path: Path) -> None:
    """A vacancy with non-empty description_text should skip detail."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="v1",
            name="Test",
            description_text="Some description text",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    assert storage.detail_needed("v1") is False


def test_existing_vacancy_without_description_fetches_detail(tmp_path: Path) -> None:
    """A vacancy with empty description_text should fetch detail."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="v2",
            name="Test",
            description_text="",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    assert storage.detail_needed("v2") is True


def test_stale_vacancy_refreshes_detail(tmp_path: Path) -> None:
    """A vacancy older than refresh threshold should fetch detail."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    stale = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="v3",
            name="Test",
            description_text="Old description",
            raw_json="{}",
            first_seen_at=stale,
            last_seen_at=stale,
        )
    )
    assert storage.detail_needed("v3", refresh_days=7) is True


def test_recent_vacancy_skips_detail(tmp_path: Path) -> None:
    """A recently seen vacancy should skip detail when within threshold."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="v4",
            name="Test",
            description_text="Recent description",
            raw_json="{}",
            first_seen_at=recent,
            last_seen_at=recent,
        )
    )
    assert storage.detail_needed("v4", refresh_days=7) is False


def test_force_details_overrides_cache(tmp_path: Path) -> None:
    """--force-details should always return True regardless of cache state."""
    storage = Storage(str(tmp_path / "test.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="v5",
            name="Test",
            description_text="Cached description",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    assert storage.detail_needed("v5", force=True, refresh_days=7) is True


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


def test_dry_run_does_not_make_api_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run should show estimate and exit without making API calls."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    _make_scoring_rules(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/dryrun.sqlite")
    output = _record_console(monkeypatch)

    # Patch HHClient to fail if any API call is made
    original_init = HHClient.__init__

    def no_api_init(self, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        # Override _request to fail
        self._orig_request = self._request

        def fail_request(*a: Any, **kw: Any) -> Any:
            raise RuntimeError("API call was made during dry-run!")

        self._request = fail_request

    monkeypatch.setattr(HHClient, "__init__", no_api_init)

    result = search_cmds.command_search(
        Namespace(
            mode="normal",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=True,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    rendered = output.export_text()
    assert result == 0
    assert "Dry-run complete" in rendered
    assert "Search Run Estimate" in rendered
    assert "python" in rendered
    assert "automation" in rendered


def test_dry_run_smoke_shows_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke dry-run should show single profile info."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    output = _record_console(monkeypatch)

    result = search_cmds.command_search(
        Namespace(
            mode="smoke",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=True,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    rendered = output.export_text()
    assert result == 0
    # Smoke mode uses single profile
    assert "ai_automation" in rendered
    assert "Dry-run complete" in rendered
    assert "No API requests were made" in rendered


# ---------------------------------------------------------------------------
# 429 handling tests
# ---------------------------------------------------------------------------


def test_stop_on_429_is_configurable() -> None:
    """stop_on_429 should read from HH_STOP_ON_429 env."""
    client = HHClient(auth_mode="none")
    assert client.stop_on_429 is True  # default

    # Test env override
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HH_STOP_ON_429", "false")
        client2 = HHClient(auth_mode="none")
        assert client2.stop_on_429 is False

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HH_STOP_ON_429", "true")
        client3 = HHClient(auth_mode="none")
        assert client3.stop_on_429 is True


def test_rate_limit_delays_are_configurable() -> None:
    """Delay settings should read from environment."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HH_DELAY_MIN_SECONDS", "0.3")
        mp.setenv("HH_DELAY_MAX_SECONDS", "0.8")
        mp.setenv("HH_COOLDOWN_ON_429_SECONDS", "60")
        client = HHClient(auth_mode="none")
        assert client.delay_min == 0.3
        assert client.delay_max == 0.8
        assert client.cooldown_429 == 60.0


# ---------------------------------------------------------------------------
# Search mode smoke should select single profile
# ---------------------------------------------------------------------------


def test_smoke_mode_selects_single_enabled_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In smoke mode without --profile, pick the first enabled profile."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    monkeypatch.setenv("DB_PATH", "data/test.sqlite")
    output = _record_console(monkeypatch)

    # Simulate dry-run for smoke mode
    result = search_cmds.command_search(
        Namespace(
            mode="smoke",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=True,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    rendered = output.export_text()
    assert result == 0
    # Only one profile should appear
    assert "ai_automation" in rendered
    # bitrix_1c should NOT appear (smoke uses one profile)
    assert "bitrix_1c" not in rendered


# ---------------------------------------------------------------------------
# Integration: search with minimal budget and fake API
# ---------------------------------------------------------------------------


class _FakeSearchResponse:
    """Mimics HHClient search responses for testing budget enforcement."""

    def __init__(self) -> None:
        self.search_calls = 0
        self.detail_calls = 0
        self.should_429 = False

    def search_vacancies(
        self,
        text: str,
        area: str | int | None = None,
        page: int = 0,
        per_page: int = 50,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.search_calls += 1
        if self.should_429:
            from src.hh_client import HHAPIError

            raise HHAPIError(
                "Rate limit",
                status_code=429,
                path="/vacancies",
            )
        # Return one vacancy per search
        return {
            "items": [
                {
                    "id": f"fake-{self.search_calls}",
                    "name": f"Fake Vacancy {self.search_calls}",
                    "area": {"name": "Test"},
                    "alternate_url": f"https://hh.ru/vacancy/{self.search_calls}",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "snippet": {},
                }
            ],
            "pages": 1,
            "page": 0,
        }

    def get_vacancy(self, vacancy_id: str) -> dict[str, Any]:
        self.detail_calls += 1
        return {
            "id": vacancy_id,
            "name": f"Detail {vacancy_id}",
            "area": {"name": "Test"},
            "alternate_url": f"https://hh.ru/vacancy/{vacancy_id}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "description": "<p>Full description text</p>",
            "key_skills": [],
            "snippet": {},
        }


def test_budget_stops_full_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tight budget should stop the run after exhausting requests."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    _make_scoring_rules(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/budget_stop.sqlite")
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.setenv("HH_AUTH_MODE", "none")
    monkeypatch.setenv("HH_DELAY_MIN_SECONDS", "0")
    monkeypatch.setenv("HH_DELAY_MAX_SECONDS", "0")
    output = _record_console(monkeypatch)

    fake_api = _FakeSearchResponse()

    original_init = HHClient.__init__

    def fake_init(self: HHClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.search_vacancies = fake_api.search_vacancies  # type: ignore[method-assign]
        self.get_vacancy = fake_api.get_vacancy  # type: ignore[method-assign]

    monkeypatch.setattr(HHClient, "__init__", fake_init)

    result = search_cmds.command_search(
        Namespace(
            mode="smoke",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=False,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    output.export_text()
    # Should not crash
    assert result == 0
    # Budget should have been used
    assert fake_api.search_calls > 0


def test_429_stops_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When HH_STOP_ON_429=true, a 429 should stop the run cleanly."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    _make_scoring_rules(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/429_stop.sqlite")
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.setenv("HH_AUTH_MODE", "none")
    monkeypatch.setenv("HH_DELAY_MIN_SECONDS", "0")
    monkeypatch.setenv("HH_DELAY_MAX_SECONDS", "0")
    monkeypatch.setenv("HH_STOP_ON_429", "true")
    output = _record_console(monkeypatch)

    fake_api = _FakeSearchResponse()
    fake_api.should_429 = True

    original_init = HHClient.__init__

    def fake_init(self: HHClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.search_vacancies = fake_api.search_vacancies  # type: ignore[method-assign]
        self.get_vacancy = fake_api.get_vacancy  # type: ignore[method-assign]

    monkeypatch.setattr(HHClient, "__init__", fake_init)

    result = search_cmds.command_search(
        Namespace(
            mode="smoke",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=False,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    rendered = output.export_text()
    # Should stop gracefully
    assert result == 0
    assert "429" in rendered or "rate limit" in rendered.lower()


def test_force_details_does_not_ignore_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--force-details should still respect the detail budget."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    _make_scoring_rules(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/force_budget.sqlite")
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.setenv("HH_AUTH_MODE", "none")
    monkeypatch.setenv("HH_DELAY_MIN_SECONDS", "0")
    monkeypatch.setenv("HH_DELAY_MAX_SECONDS", "0")
    output = _record_console(monkeypatch)

    fake_api = _FakeSearchResponse()

    original_init = HHClient.__init__

    def fake_init(self: HHClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.search_vacancies = fake_api.search_vacancies  # type: ignore[method-assign]
        self.get_vacancy = fake_api.get_vacancy  # type: ignore[method-assign]

    monkeypatch.setattr(HHClient, "__init__", fake_init)

    result = search_cmds.command_search(
        Namespace(
            mode="smoke",  # smoke has max_details=25
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=False,
            force_details=True,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    output.export_text()
    assert result == 0
    # With force_details, detail calls should be made but within budget
    # Smoke mode max_details=25, max_requests=50
    assert fake_api.detail_calls <= 25


# ---------------------------------------------------------------------------
# Description preservation tests (regression for skip-detail overwrite bug)
# ---------------------------------------------------------------------------


def test_touch_vacancy_preserves_description(tmp_path: Path) -> None:
    """touch_vacancy should update last_seen_at without touching description_text."""
    storage = Storage(str(tmp_path / "touch.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    original_desc = "Original description that must be preserved"
    storage.upsert_vacancy(
        Vacancy(
            id="v-touch",
            name="Test",
            description_text=original_desc,
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    assert storage.touch_vacancy("v-touch") is True
    desc = storage.get_vacancy_description("v-touch")
    assert desc == original_desc
    assert storage.touch_vacancy("nonexistent") is False


def test_skip_detail_preserves_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a vacancy already has a description, skip-detail should preserve it."""
    _make_minimal_profiles(tmp_path, monkeypatch)
    _make_scoring_rules(tmp_path)
    monkeypatch.setenv("DB_PATH", "data/skip_desc.sqlite")
    monkeypatch.delenv("HH_AUTH_MODE", raising=False)
    monkeypatch.setenv("HH_AUTH_MODE", "none")
    monkeypatch.setenv("HH_DELAY_MIN_SECONDS", "0")
    monkeypatch.setenv("HH_DELAY_MAX_SECONDS", "0")
    monkeypatch.setenv("HH_DETAIL_REFRESH_DAYS", "30")

    storage = Storage("data/skip_desc.sqlite")
    now = datetime.now(timezone.utc).isoformat()
    original_desc = "Preserved description"
    storage.upsert_vacancy(
        Vacancy(
            id="fake-1",
            name="Existing Vacancy",
            description_text=original_desc,
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    _record_console(monkeypatch)
    fake_api = _FakeSearchResponse()

    original_init = HHClient.__init__

    def fake_init(self: HHClient, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.search_vacancies = fake_api.search_vacancies
        self.get_vacancy = fake_api.get_vacancy

    monkeypatch.setattr(HHClient, "__init__", fake_init)

    result = search_cmds.command_search(
        Namespace(
            mode="smoke",
            max_pages=None,
            per_page=None,
            profile=None,
            dry_run=False,
            force_details=False,
            verbose=False,
            yes=False,
            adhoc=False,
            preset=None,
            include=None,
            exclude=None,
            remote_only=None,
        )
    )

    assert result == 0
    storage2 = Storage("data/skip_desc.sqlite")
    desc = storage2.get_vacancy_description("fake-1")
    assert desc == original_desc, (
        f"Description was overwritten! Expected '{original_desc}', got '{desc}'"
    )


# ---------------------------------------------------------------------------
# Scoring v2 correctness tests
# ---------------------------------------------------------------------------


def test_score_by_preset_uses_preset_name_as_best_profile() -> None:
    """Preset-scored vacancy should have best_profile = preset name."""
    from src.scoring_v2 import score_by_preset

    vacancy = Vacancy(
        id="test-preset",
        name="LLM Engineer",
        description_text="Python FastAPI LangChain RAG",
        raw_json="{}",
        first_seen_at=datetime.now(timezone.utc).isoformat(),
        last_seen_at=datetime.now(timezone.utc).isoformat(),
    )
    preset = {
        "_name": "ai_rag_remote",
        "include": {"any": ["python", "rag", "llm"]},
        "boost": {},
        "penalties": {},
        "remote_only": False,
    }
    result = score_by_preset(vacancy, preset)
    assert result.best_profile == "ai_rag_remote"
    assert result.total_score >= 30  # 3 any matches × 15


def test_exclude_checks_full_text_not_just_title_and_desc() -> None:
    """Exclude.any should match against full vacancy text (including skills)."""
    from src.scoring_v2 import score_by_preset

    vacancy = Vacancy(
        id="test-excl",
        name="Senior Developer",
        description_text="Building great products",
        key_skills=["Python", "gambling"],
        raw_json="{}",
        first_seen_at=datetime.now(timezone.utc).isoformat(),
        last_seen_at=datetime.now(timezone.utc).isoformat(),
    )
    preset = {
        "_name": "test",
        "include": {"any": ["python"]},
        "exclude": {"any": ["gambling"]},
        "boost": {},
        "penalties": {},
        "remote_only": False,
    }
    result = score_by_preset(vacancy, preset)
    # Should have exclude penalty because "gambling" is in skills
    assert "exclude_match" in result.risk_flags
    assert result.total_score < 15  # 15 base - 30 exclude = -15 → clipped to 0


def test_score_by_preset_adhoc_mode() -> None:
    """Adhoc preset should score with mode='adhoc'."""
    from src.scoring_v2 import score_by_preset
    from src.search_presets import create_adhoc_preset

    vacancy = Vacancy(
        id="test-adhoc",
        name="Python Developer",
        description_text="FastAPI backend",
        schedule_name="remote",
        raw_json="{}",
        first_seen_at=datetime.now(timezone.utc).isoformat(),
        last_seen_at=datetime.now(timezone.utc).isoformat(),
    )
    preset = create_adhoc_preset(["Python", "FastAPI"], ["QA"])
    result = score_by_preset(vacancy, preset)
    assert result.best_profile == "adhoc"
    assert result.total_score >= 15  # at least one include match


def test_touch_vacancy_returns_false_for_unknown_id(tmp_path: Path) -> None:
    """touch_vacancy should return False when vacancy doesn't exist."""
    storage = Storage(str(tmp_path / "touch2.sqlite"))
    assert storage.touch_vacancy("no-such-id") is False


def test_get_vacancy_description_returns_none_for_unknown(tmp_path: Path) -> None:
    """get_vacancy_description should return None for unknown vacancy."""
    storage = Storage(str(tmp_path / "desc2.sqlite"))
    assert storage.get_vacancy_description("no-such-id") is None
