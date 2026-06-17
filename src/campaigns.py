"""Campaign management — multi-candidate workflow support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .search_presets import get_preset

CAMPAIGNS_PATH = "config/campaigns.yaml"


def load_campaigns(path: str = CAMPAIGNS_PATH) -> dict[str, Any]:
    """Load campaigns from YAML file. Returns empty dicts if missing."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def list_enabled_campaigns(path: str = CAMPAIGNS_PATH) -> list[dict[str, Any]]:
    """Return list of enabled campaign dicts with _name key."""
    data = load_campaigns(path)
    campaigns = data.get("campaigns", {})
    result = []
    for name, cfg in campaigns.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue
        result.append({"_name": name, **cfg})
    return result


def get_campaign(name: str, path: str = CAMPAIGNS_PATH) -> dict[str, Any] | None:
    """Return a single campaign dict with _name, or None."""
    data = load_campaigns(path)
    campaigns = data.get("campaigns", {})
    cfg = campaigns.get(name)
    if not isinstance(cfg, dict):
        return None
    return {"_name": name, **cfg}


def get_campaign_presets(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    """Return resolved preset dicts for a campaign."""
    preset_names = campaign.get("presets", [])
    resolved = []
    for pname in preset_names:
        preset = get_preset(pname)
        if preset:
            resolved.append(preset)
    return resolved


def get_candidate_profile_name(campaign: dict[str, Any]) -> str:
    """Return candidate profile name for a campaign."""
    return campaign.get("candidate_profile", "default")
