from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_search_profiles(path: str | Path = "config/search_profiles.yaml") -> dict[str, Any]:
    try:
        return load_yaml(path).get("profiles", {})
    except (OSError, yaml.YAMLError):
        return {}


def load_scoring_rules(path: str | Path = "config/scoring_rules.yaml") -> dict[str, Any]:
    try:
        return load_yaml(path)
    except (OSError, yaml.YAMLError):
        return {}
