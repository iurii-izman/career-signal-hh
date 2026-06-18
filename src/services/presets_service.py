"""Preset management service — CRUD, validation, backup, calibration."""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..search_presets import load_search_presets, validate_preset
from ..storage import Storage

PRESETS_PATH = "config/search_presets.yaml"
BACKUPS_DIR = Path("config/backups")
SUGGESTIONS_PATH = "data/calibration_suggestions.json"


def _get_storage() -> Storage:
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


# ── Backup ─────────────────────────────────────────────────────────


def _backup() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"search_presets_{ts}.yaml"
    try:
        if Path(PRESETS_PATH).exists():
            shutil.copy2(PRESETS_PATH, dst)
    except OSError:
        pass
    return dst


# ── Read ───────────────────────────────────────────────────────────


def list_all_presets() -> list[dict[str, Any]]:
    """Return all presets (enabled and disabled) with performance data."""
    data = load_search_presets()
    presets_data = data.get("presets", {})

    # Load performance from DB
    perf = _get_preset_performance()

    result = []
    for name, preset in presets_data.items():
        if not isinstance(preset, dict):
            continue
        p = {
            "_name": name,
            "enabled": preset.get("enabled", True),
            "description": preset.get("description", ""),
            "search_terms": preset.get("search_terms", []),
            "include": preset.get("include", {}),
            "exclude": preset.get("exclude", {}),
            "boost": preset.get("boost", {}),
            "penalties": preset.get("penalties", {}),
            "remote_only": preset.get("filters", {}).get("remote_only", False)
            or preset.get("remote_only", False),
            "areas": preset.get("filters", {}).get("areas", []) or preset.get("areas", []),
            "schedule": preset.get("filters", {}).get("schedule", []) or preset.get("schedule", []),
            "experience": preset.get("filters", {}).get("experience", [])
            or preset.get("experience", []),
            "decision_thresholds": preset.get("decision_thresholds"),
            "salary_as_bonus": preset.get("salary_as_bonus"),
        }
        # Merge performance
        pname_lower = name.lower()
        for pf in perf:
            if pf["preset"].lower() == pname_lower:
                p["_performance"] = pf
                break
        result.append(p)

    result.sort(key=lambda p: (not p["enabled"], p["_name"]))
    return result


def get_preset_raw(name: str) -> dict[str, Any] | None:
    """Return raw preset data (without defaults merged)."""
    data = load_search_presets()
    presets = data.get("presets", {})
    return presets.get(name)


def get_preset_merged(name: str) -> dict[str, Any] | None:
    """Return preset with defaults merged."""
    from ..search_presets import get_preset

    return get_preset(name)


# ── Write ──────────────────────────────────────────────────────────


def save_preset(
    name: str, preset_data: dict[str, Any], create_backup: bool = True
) -> dict[str, Any]:
    """Save a preset to YAML. Returns {ok, message, errors}."""
    # Validate name
    if not name or not name.strip():
        return {"ok": False, "message": "Preset name is required", "errors": ["Empty name"]}
    name = name.strip()

    # Validate no dangerous paths
    if "/" in name or "\\" in name:
        return {
            "ok": False,
            "message": "Preset name must not contain path separators",
            "errors": ["Invalid name"],
        }

    # Build preset structure
    preset = {
        "enabled": preset_data.get("enabled", True),
        "description": preset_data.get("description", ""),
        "search_terms": preset_data.get("search_terms", []),
        "include": preset_data.get("include", {"any": [], "all": [], "title": []}),
        "exclude": preset_data.get("exclude", {"any": [], "title": []}),
        "boost": preset_data.get("boost", {}),
        "penalties": preset_data.get("penalties", {}),
    }

    # Filters
    filters = {}
    if "remote_only" in preset_data:
        filters["remote_only"] = preset_data["remote_only"]
    if "areas" in preset_data:
        filters["areas"] = preset_data["areas"]
    if "schedule" in preset_data:
        filters["schedule"] = preset_data["schedule"]
    if "experience" in preset_data:
        filters["experience"] = preset_data["experience"]
    if filters:
        preset["filters"] = filters

    # Optional fields
    if preset_data.get("decision_thresholds"):
        preset["decision_thresholds"] = preset_data["decision_thresholds"]
    if preset_data.get("salary_as_bonus") is not None:
        preset["salary_as_bonus"] = preset_data["salary_as_bonus"]

    # Validate
    merged = {"_name": name, **preset, "_source": "preset"}
    errors = validate_preset(merged)
    # Additional validation
    terms = preset.get("search_terms", [])
    if len(terms) != len(set(terms)):
        errors.append("Duplicate search terms found")

    if errors:
        return {
            "ok": False,
            "message": f"Validation failed: {len(errors)} error(s)",
            "errors": errors,
        }

    # Load, update, backup, save
    data = load_search_presets()
    if "presets" not in data:
        data["presets"] = {}

    is_new = name not in data["presets"]
    if create_backup:
        _backup()

    data["presets"][name] = preset

    Path(PRESETS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {
        "ok": True,
        "message": f"Preset '{name}' {'created' if is_new else 'updated'}",
        "errors": [],
    }


def clone_preset(source_name: str, new_name: str) -> dict[str, Any]:
    """Clone a preset to a new name."""
    if not new_name or not new_name.strip():
        return {"ok": False, "message": "New name is required", "errors": ["Empty name"]}
    new_name = new_name.strip()

    data = load_search_presets()
    presets = data.get("presets", {})
    if source_name not in presets:
        return {"ok": False, "message": f"Source preset '{source_name}' not found", "errors": []}
    if new_name in presets:
        return {"ok": False, "message": f"Preset '{new_name}' already exists", "errors": []}

    _backup()
    presets[new_name] = copy.deepcopy(presets[source_name])
    presets[new_name]["description"] = f"Clone of {source_name}"

    Path(PRESETS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {"ok": True, "message": f"Cloned '{source_name}' → '{new_name}'", "errors": []}


def set_preset_enabled(name: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a preset."""
    data = load_search_presets()
    presets = data.get("presets", {})
    if name not in presets:
        return {"ok": False, "message": f"Preset '{name}' not found", "errors": []}

    presets[name]["enabled"] = enabled
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {
        "ok": True,
        "message": f"Preset '{name}' {'enabled' if enabled else 'disabled'}",
        "errors": [],
    }


def validate_preset_ui(name: str, preset_data: dict[str, Any]) -> dict[str, Any]:
    """Validate preset data without saving. Returns {ok, errors}."""
    if not name or not name.strip():
        return {"ok": False, "errors": ["Preset name is required"]}
    name = name.strip()

    merged = {"_name": name, **preset_data, "_source": "preset"}
    errors = validate_preset(merged)
    terms = preset_data.get("search_terms", [])
    if len(terms) != len(set(terms)):
        errors.append("Duplicate search terms found")

    return {"ok": len(errors) == 0, "errors": errors}


# ── Performance ────────────────────────────────────────────────────


def _get_preset_performance() -> list[dict[str, Any]]:
    """Get per-preset performance from DB."""
    storage = _get_storage()
    try:
        with storage.connect() as conn:
            rows = conn.execute(
                "SELECT COALESCE(sd.preset_name, s.best_profile, 'unknown') preset,"
                " COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score,"
                " SUM(CASE WHEN sd.decision='strong_match' THEN 1 ELSE 0 END) strong,"
                " SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END) applied,"
                " SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END) rejected,"
                " SUM(CASE WHEN r.status='interview' THEN 1 ELSE 0 END) interview,"
                " SUM(CASE WHEN r.status='offer' THEN 1 ELSE 0 END) offer"
                " FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id"
                " LEFT JOIN score_details sd ON sd.vacancy_id=v.id"
                " LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id"
                " GROUP BY preset ORDER BY cnt DESC"
            ).fetchall()
        return [
            {
                "preset": row[0],
                "found": row[1],
                "avg_score": round(row[2], 1),
                "strong": row[3],
                "applied": row[4],
                "rejected": row[5],
                "interview": row[6],
                "offer": row[7],
            }
            for row in rows
        ]
    except Exception:
        return []


# ── Calibration suggestions ────────────────────────────────────────


def get_calibration_suggestions(preset_name: str | None = None) -> list[dict[str, Any]]:
    """Return calibration suggestions, optionally filtered by preset."""
    try:
        suggestions = json.loads(Path(SUGGESTIONS_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if preset_name:
        suggestions = [s for s in suggestions if s.get("preset", "").lower() == preset_name.lower()]
    return suggestions


def apply_calibration_suggestion(suggestion_id: str) -> dict[str, Any]:
    """Apply a calibration suggestion to its preset."""
    try:
        suggestions = json.loads(Path(SUGGESTIONS_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "message": "No suggestions file found"}

    target = None
    for s in suggestions:
        if s.get("id") == suggestion_id or str(s.get("id")) == suggestion_id:
            target = s
            break

    if not target:
        return {"ok": False, "message": f"Suggestion {suggestion_id} not found"}

    preset_name = target.get("preset")
    typ = target.get("type", "")
    keyword = target.get("keyword") or target.get("search_term", "")

    if not preset_name or not keyword:
        return {"ok": False, "message": "Invalid suggestion: missing preset or keyword"}

    data = load_search_presets()
    presets = data.get("presets", {})
    if preset_name not in presets:
        return {"ok": False, "message": f"Preset '{preset_name}' not found"}

    _backup()

    preset = presets[preset_name]
    if typ == "include":
        preset.setdefault("include", {}).setdefault("any", [])
        if keyword not in preset["include"]["any"]:
            preset["include"]["any"].append(keyword)
    elif typ == "exclude":
        preset.setdefault("exclude", {}).setdefault("any", [])
        if keyword not in preset["exclude"]["any"]:
            preset["exclude"]["any"].append(keyword)
    elif typ in ("boost_skills", "boost_title", "boost_description"):
        field = typ.replace("boost_", "")
        weight = target.get("weight", 1)
        preset.setdefault("boost", {}).setdefault(field, {})[keyword] = weight
    elif typ in ("penalty_title", "penalty_description"):
        field = typ.replace("penalty_", "")
        weight = target.get("weight", 1)
        preset.setdefault("penalties", {}).setdefault(field, {})[keyword] = -abs(weight)
    elif typ == "remove_search_term":
        terms = preset.get("search_terms", [])
        if keyword in terms:
            terms.remove(keyword)
    elif typ == "add_search_term":
        terms = preset.get("search_terms", [])
        if keyword not in terms:
            terms.append(keyword)

    # Mark as applied
    target["status"] = "applied"

    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    Path(SUGGESTIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SUGGESTIONS_PATH).write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"ok": True, "message": f"Applied '{keyword}' as {typ} to '{preset_name}'"}


def dismiss_calibration_suggestion(suggestion_id: str) -> dict[str, Any]:
    """Dismiss a calibration suggestion."""
    try:
        suggestions = json.loads(Path(SUGGESTIONS_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "message": "No suggestions file found"}

    for s in suggestions:
        if s.get("id") == suggestion_id or str(s.get("id")) == suggestion_id:
            s["status"] = "dismissed"
            break

    Path(SUGGESTIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SUGGESTIONS_PATH).write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"ok": True, "message": f"Suggestion {suggestion_id} dismissed"}


# ── Campaigns ───────────────────────────────────────────────────────


def list_all_campaigns() -> list[dict[str, Any]]:
    """Return all campaigns with queue counts."""
    from ..campaigns import load_campaigns

    data = load_campaigns()
    campaigns = data.get("campaigns", {})

    result = []
    for name, cfg in campaigns.items():
        if not isinstance(cfg, dict):
            continue
        c = {
            "_name": name,
            "enabled": cfg.get("enabled", True),
            "presets": cfg.get("presets", []),
            "candidate_profile": cfg.get("candidate_profile", "default"),
            "min_score": cfg.get("min_score", 0),
            "default_lang": cfg.get("default_lang", "ru"),
            "apply_template": cfg.get("apply_template", "default"),
            "description": cfg.get("description", ""),
        }
        # Queue count
        c["_queue_count"] = _get_campaign_queue_count(c)
        result.append(c)

    result.sort(key=lambda c: (not c["enabled"], c["_name"]))
    return result


def get_campaign_raw(name: str) -> dict[str, Any] | None:
    """Return raw campaign data."""
    from ..campaigns import load_campaigns

    data = load_campaigns()
    campaigns = data.get("campaigns", {})
    cfg = campaigns.get(name)
    if not isinstance(cfg, dict):
        return None
    return {
        "_name": name,
        "enabled": cfg.get("enabled", True),
        "presets": cfg.get("presets", []),
        "candidate_profile": cfg.get("candidate_profile", "default"),
        "min_score": cfg.get("min_score", 0),
        "default_lang": cfg.get("default_lang", "ru"),
        "apply_template": cfg.get("apply_template", "default"),
        "description": cfg.get("description", ""),
    }


def save_campaign(name: str, campaign_data: dict[str, Any]) -> dict[str, Any]:
    """Save a campaign to YAML."""
    if not name or not name.strip():
        return {"ok": False, "message": "Campaign name is required", "errors": ["Empty name"]}
    name = name.strip()

    from ..campaigns import load_campaigns

    CAMPAIGNS_PATH = "config/campaigns.yaml"
    data = load_campaigns()
    if "campaigns" not in data:
        data["campaigns"] = {}

    is_new = name not in data["campaigns"]

    data["campaigns"][name] = {
        "enabled": campaign_data.get("enabled", True),
        "description": campaign_data.get("description", ""),
        "presets": campaign_data.get("presets", []),
        "candidate_profile": campaign_data.get("candidate_profile", "default"),
        "min_score": campaign_data.get("min_score", 70),
        "default_lang": campaign_data.get("default_lang", "ru"),
        "apply_template": campaign_data.get("apply_template"),
    }

    Path(CAMPAIGNS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(CAMPAIGNS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {
        "ok": True,
        "message": f"Campaign '{name}' {'created' if is_new else 'updated'}",
        "errors": [],
    }


def _get_campaign_queue_count(campaign: dict[str, Any]) -> int:
    """Count queue items for a campaign's presets."""
    storage = _get_storage()
    total = 0
    for preset_name in campaign.get("presets", []):
        try:
            rows = storage.list_queue(
                min_score=campaign.get("min_score", 70),
                preset=preset_name,
                new_only=True,
                limit=1000,
            )
            total += len(rows)
        except Exception:
            pass
    return total
