"""Tests for campaigns — multi-candidate workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.campaigns import (
    get_campaign,
    get_campaign_presets,
    get_candidate_profile_name,
    list_enabled_campaigns,
)
from tests.helpers import parse_args

pytestmark = [pytest.mark.no_network]


# ═══════════════════════════════════════════════════════════════════════════
# Campaign loading
# ═══════════════════════════════════════════════════════════════════════════


def test_list_campaigns_returns_list() -> None:
    """list_enabled_campaigns must return list, not crash without file."""
    campaigns = list_enabled_campaigns()
    assert isinstance(campaigns, list)
    # Should find our test campaigns (real config)
    names = {c["_name"] for c in campaigns}
    assert "iurii_ai" in names
    assert "iurii_bitrix" in names


def test_get_campaign_returns_dict() -> None:
    """get_campaign must return campaign dict with _name."""
    c = get_campaign("iurii_ai")
    assert c is not None
    assert c["_name"] == "iurii_ai"
    assert "presets" in c
    assert "candidate_profile" in c


def test_get_campaign_nonexistent() -> None:
    """get_campaign for nonexistent must return None."""
    assert get_campaign("nonexistent_campaign") is None


def test_candidate_profile_name() -> None:
    """get_candidate_profile_name must return the correct profile."""
    assert get_candidate_profile_name({"_name": "test", "candidate_profile": "ai"}) == "ai"
    assert get_candidate_profile_name({"_name": "test"}) == "default"


def test_campaign_presets_resolve() -> None:
    """get_campaign_presets must resolve preset names to actual presets."""
    campaign = get_campaign("iurii_ai")
    assert campaign is not None
    presets = get_campaign_presets(campaign)
    assert len(presets) >= 1
    assert any(p.get("_name") == "ai_rag_remote" for p in presets)


# ═══════════════════════════════════════════════════════════════════════════
# CLI parsing contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_campaigns_list_parses() -> None:
    args = parse_args(["campaigns", "list"])
    assert args.campaigns_command == "list"


def test_campaigns_show_parses() -> None:
    args = parse_args(["campaigns", "show", "iurii_ai"])
    assert args.campaigns_command == "show"
    assert args.name == "iurii_ai"


def test_campaigns_daily_parses() -> None:
    args = parse_args(["campaigns", "daily", "iurii_ai", "--skip-search"])
    assert args.campaigns_command == "daily"
    assert args.name == "iurii_ai"
    assert args.skip_search is True


def test_campaigns_queue_parses() -> None:
    args = parse_args(["campaigns", "queue", "iurii_bitrix"])
    assert args.campaigns_command == "queue"
    assert args.name == "iurii_bitrix"


def test_campaigns_apply_pack_parses() -> None:
    args = parse_args(["campaigns", "apply-pack", "iurii_ai", "--top", "3"])
    assert args.campaigns_command == "apply-pack"
    assert args.name == "iurii_ai"
    assert args.top == 3


# ═══════════════════════════════════════════════════════════════════════════
# Commands — dry runs
# ═══════════════════════════════════════════════════════════════════════════


def test_campaign_list_works(tmp_path: Path, monkeypatch, capsys) -> None:
    """campaigns list must not crash."""
    from argparse import Namespace

    from src.commands.campaigns import command_campaigns_list

    result = command_campaigns_list(Namespace())
    captured = capsys.readouterr().out
    assert result == 0
    assert "iurii_ai" in captured


def test_campaign_show_works(tmp_path: Path, capsys) -> None:
    """campaigns show must print details."""
    from argparse import Namespace

    from src.commands.campaigns import command_campaigns_show

    result = command_campaigns_show(Namespace(name="iurii_ai"))
    captured = capsys.readouterr().out
    assert result == 0
    assert "iurii_ai" in captured
    assert "ai_rag_remote" in captured


def test_campaign_show_nonexistent(tmp_path: Path, capsys) -> None:
    """campaigns show for missing campaign must exit 1."""
    from argparse import Namespace

    from src.commands.campaigns import command_campaigns_show

    result = command_campaigns_show(Namespace(name="no_such_campaign"))
    assert result == 1


def test_campaign_daily_skip_search_works(tmp_path: Path, monkeypatch, capsys) -> None:
    """campaigns daily --skip-search must not make API calls."""
    storage_path = tmp_path / "data" / "test.sqlite"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DB_PATH", str(storage_path))

    from argparse import Namespace

    from src.commands.campaigns import command_campaigns_daily

    result = command_campaigns_daily(
        Namespace(name="iurii_ai", skip_auth_check=True, skip_search=True)
    )
    captured = capsys.readouterr().out
    assert result == 0
    assert "Campaign" in captured or "iurii_ai" in captured


def test_existing_commands_still_work(tmp_path: Path, monkeypatch, capsys) -> None:
    """Regular commands (search --dry-run, health) must work without campaigns.yaml."""
    storage_path = tmp_path / "data" / "test.sqlite"
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DB_PATH", str(storage_path))
    monkeypatch.setattr("src.commands.health.load_dotenv", lambda *a, **kw: None)

    from argparse import Namespace

    from src.commands.health import command_health

    result = command_health(Namespace())
    assert result in (0, 1)  # OK or warning, not crash
