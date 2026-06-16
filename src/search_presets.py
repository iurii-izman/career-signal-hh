from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_search_presets(
    path: str | Path = "config/search_presets.yaml",
) -> dict[str, Any]:
    """Load search presets from YAML file.

    Returns dict with 'defaults' and 'presets' keys.
    Returns empty structure if file is missing.
    """
    try:
        data = load_yaml(path)
    except (OSError, yaml.YAMLError):
        return {"defaults": {}, "presets": {}}
    if not isinstance(data, dict):
        return {"defaults": {}, "presets": {}}
    return data


def merge_defaults(defaults: dict[str, Any], preset: dict[str, Any]) -> dict[str, Any]:
    """Merge global defaults into a preset. Preset values take precedence."""
    merged = deepcopy(defaults)
    # Remove non-filter keys from defaults that shouldn't cascade
    merged.pop("decision_thresholds", None)
    merged.pop("language_priority", None)
    merged.pop("salary_as_bonus", None)

    # Merge filters: preset.filters override defaults
    preset_filters = preset.get("filters", {})
    for key in ("remote_only", "areas", "schedule", "experience"):
        if key in preset_filters:
            merged[key] = preset_filters[key]

    # Copy top-level preset keys
    for key in (
        "enabled",
        "description",
        "search_terms",
        "include",
        "exclude",
        "boost",
        "penalties",
        "salary_as_bonus",
    ):
        if key in preset:
            merged[key] = preset[key]

    merged["_name"] = preset.get("_name", "")
    merged["_source"] = "preset"
    return merged


def validate_preset(preset: dict[str, Any]) -> list[str]:
    """Validate a preset structure. Returns list of error messages (empty = valid)."""
    errors: list[str] = []
    name = preset.get("_name", "unknown")

    if not preset.get("search_terms"):
        errors.append(f"Preset '{name}': search_terms is empty or missing")

    if "include" in preset:
        inc = preset["include"]
        if not isinstance(inc, dict):
            errors.append(
                f"Preset '{name}': include must be a dict with any/all/title keys"
            )
        else:
            has_any = inc.get("any") or inc.get("title")
            has_all = inc.get("all")
            if not has_any and not has_all:
                errors.append(f"Preset '{name}': include has no any/all/title entries")

    return errors


def list_presets(
    path: str | Path = "config/search_presets.yaml",
) -> list[dict[str, Any]]:
    """Return all enabled presets with defaults merged."""
    data = load_search_presets(path)
    defaults = data.get("defaults", {})
    presets = data.get("presets", {})
    result: list[dict[str, Any]] = []
    for name, preset in presets.items():
        if not isinstance(preset, dict):
            continue
        if not preset.get("enabled", True):
            continue
        merged = merge_defaults(defaults, preset)
        merged["_name"] = name
        result.append(merged)
    return result


def get_preset(
    name: str, path: str | Path = "config/search_presets.yaml"
) -> dict[str, Any] | None:
    """Return a single preset with defaults merged, or None if not found."""
    data = load_search_presets(path)
    defaults = data.get("defaults", {})
    presets = data.get("presets", {})
    preset = presets.get(name)
    if not preset or not isinstance(preset, dict):
        return None
    merged = merge_defaults(defaults, preset)
    merged["_name"] = name
    return merged


def create_adhoc_preset(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    *,
    remote_only: bool = True,
) -> dict[str, Any]:
    """Create a temporary in-memory preset for ad-hoc search."""
    include = include or []
    exclude = exclude or []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"adhoc_{timestamp}"

    return {
        "_name": name,
        "_source": "adhoc",
        "enabled": True,
        "description": f"Ad-hoc search ({len(include)} include, {len(exclude)} exclude)",
        "search_terms": include[:],
        "filters": {
            "remote_only": remote_only,
            "areas": [],
            "schedule": ["remote"] if remote_only else [],
            "experience": [],
        },
        "include": {"any": include[:], "all": []},
        "exclude": {"any": exclude[:]},
        "remote_only": remote_only,
        "areas": [],
        "schedule": ["remote"] if remote_only else [],
        "experience": [],
        "boost": {},
        "penalties": {},
    }
