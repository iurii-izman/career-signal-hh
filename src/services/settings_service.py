"""Settings service — safe .env editing, candidate profile, health checks."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from ..utils import mask_secret

ENV_PATH = ".env"
CANDIDATE_PATH = "config/candidate.yaml"
BACKUPS_DIR = Path("config/backups")

# .env keys we manage
SAFE_ENV_KEYS = [
    "HH_AUTH_MODE",
    "HH_USER_AGENT",
    "HH_DELAY_MIN_SECONDS",
    "HH_DELAY_MAX_SECONDS",
    "HH_COOLDOWN_ON_429_SECONDS",
    "HH_STOP_ON_429",
    "HH_DETAIL_REFRESH_DAYS",
    "DB_PATH",
]
TOKEN_KEYS = ["HH_APP_ACCESS_TOKEN", "HH_USER_ACCESS_TOKEN"]


def _backup_env() -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUPS_DIR / f"env_{ts}"
    try:
        if Path(ENV_PATH).exists():
            shutil.copy2(ENV_PATH, dst)
    except OSError:
        pass
    return dst


# ═══════════════════════════════════════════════════════════════════════
# Read settings
# ═══════════════════════════════════════════════════════════════════════


def get_settings() -> dict[str, Any]:
    """Return all settings, never exposing full token."""
    load_dotenv()
    masked_tokens = {key: mask_secret(os.getenv(key, "")) for key in TOKEN_KEYS}
    from .app_service import get_operator_state

    return {
        "env": {
            "HH_AUTH_MODE": os.getenv("HH_AUTH_MODE", "none"),
            **masked_tokens,
            "HH_USER_AGENT": os.getenv("HH_USER_AGENT", "CareerSignalHH/0.1"),
            "DB_PATH": os.getenv("DB_PATH", "data/vacancies.sqlite"),
            "HH_DELAY_MIN_SECONDS": os.getenv("HH_DELAY_MIN_SECONDS", "0.7"),
            "HH_DELAY_MAX_SECONDS": os.getenv("HH_DELAY_MAX_SECONDS", "1.5"),
            "HH_COOLDOWN_ON_429_SECONDS": os.getenv("HH_COOLDOWN_ON_429_SECONDS", "120"),
            "HH_STOP_ON_429": os.getenv("HH_STOP_ON_429", "true"),
            "HH_DETAIL_REFRESH_DAYS": os.getenv("HH_DETAIL_REFRESH_DAYS", "7"),
        },
        "candidate": _load_candidate(),
        "search_modes": _load_search_modes(),
        "health": _get_health_snapshot(),
        "operator": get_operator_state(),
    }


def _load_candidate() -> dict[str, Any]:
    try:
        if Path(CANDIDATE_PATH).exists():
            return yaml.safe_load(Path(CANDIDATE_PATH).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        pass
    return {
        "candidate": {
            "name_ru": "",
            "name_en": "",
            "location": "",
            "availability": "",
            "links": {"github": "", "linkedin": ""},
            "profiles": {"default": {"summary_ru": "", "summary_en": ""}},
        }
    }


def _load_search_modes() -> dict[str, Any]:
    from ..config import SEARCH_MODES

    return {
        k: {
            "max_pages": v.get("max_pages"),
            "per_page": v.get("per_page"),
            "max_requests_per_run": v.get("max_requests_per_run"),
            "max_detail_fetches_per_run": v.get("max_detail_fetches_per_run"),
        }
        for k, v in SEARCH_MODES.items()
    }


def _get_health_snapshot() -> dict[str, Any]:
    """Quick health status without running full check."""
    load_dotenv()
    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")
    db_exists = Path(db_path).exists()
    db_size = Path(db_path).stat().st_size if db_exists else 0
    presets_exists = Path("config/search_presets.yaml").exists()
    backup_age = _file_age_hours("backups/vacancies_*.sqlite")
    return {
        "db_exists": db_exists,
        "db_size_bytes": db_size,
        "presets_exists": presets_exists,
        "latest_backup_hours": backup_age,
    }


# ═══════════════════════════════════════════════════════════════════════
# Write .env
# ═══════════════════════════════════════════════════════════════════════


def save_env_settings(updates: dict[str, str]) -> dict[str, Any]:
    """Save env settings. Token is only updated if a new value is provided."""
    errors = []
    safe_updates = {}

    for key, value in updates.items():
        if key in TOKEN_KEYS:
            # Token: only save if non-empty string provided
            if value and value.strip():
                safe_updates[key] = value.strip()
            continue
        if key in SAFE_ENV_KEYS:
            safe_updates[key] = str(value).strip()
        else:
            errors.append(f"Unknown or protected key: {key}")

    if errors:
        return {"ok": False, "message": "; ".join(errors), "errors": errors}

    # Validate
    if "DB_PATH" in safe_updates:
        p = safe_updates["DB_PATH"]
        if "/" in p or "\\" in p:
            # Allow path separators but warn
            pass

    # Backup
    _backup_env()

    # Read existing .env
    lines = _read_env_lines()

    # Update lines
    for key, value in safe_updates.items():
        _upsert_env_line(lines, key, value)

    # Write
    _write_env_lines(lines)

    return {
        "ok": True,
        "message": (
            f"Saved {len(safe_updates)} setting(s). "
            f"Tokens {'updated' if any(k in safe_updates for k in TOKEN_KEYS) else 'unchanged'}."
        ),
        "errors": [],
    }


def _read_env_lines() -> list[tuple[str | None, str, str | None]]:
    """Return list of (key, line, comment) tuples from .env file."""
    result: list[tuple[str | None, str, str | None]] = []
    if not Path(ENV_PATH).exists():
        return result
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n\r")
            # Capture comment
            comment = None
            if "#" in line:
                idx = line.index("#")
                comment = line[idx:]
                line = line[:idx].rstrip()
            # Parse key=value
            if "=" in line:
                key, value = line.split("=", 1)
                result.append((key.strip(), value.strip(), comment))
            else:
                result.append((None, line, comment))
    return result


def _upsert_env_line(lines: list[tuple[str | None, str, str | None]], key: str, value: str) -> None:
    for i, (k, v, comment) in enumerate(lines):
        if k == key:
            lines[i] = (key, value, comment)
            return
    # Not found, append
    lines.append((key, value, None))


def _write_env_lines(lines: list[tuple[str | None, str, str | None]]) -> None:
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        for key, value, comment in lines:
            if key is not None:
                line = f"{key}={value}"
                if comment:
                    line += f"  {comment}"
            else:
                line = value
                if comment:
                    line += f"  {comment}"
            f.write(line + "\n")


# ═══════════════════════════════════════════════════════════════════════
# Candidate profile
# ═══════════════════════════════════════════════════════════════════════


def save_candidate_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Save candidate.yaml from form data."""
    try:
        Path(CANDIDATE_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(CANDIDATE_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        return {"ok": True, "message": "Candidate profile saved", "errors": []}
    except (OSError, yaml.YAMLError) as exc:
        return {"ok": False, "message": str(exc), "errors": [str(exc)]}


# ═══════════════════════════════════════════════════════════════════════
# Test auth
# ═══════════════════════════════════════════════════════════════════════


def test_auth() -> dict[str, Any]:
    """Test HH API auth status."""
    load_dotenv()
    try:
        from ..hh_client import HHClient

        client = HHClient()
        status = {
            "auth_mode": client.auth_mode,
            "token_present": bool(client.app_access_token),
            "user_agent": client.user_agent,
        }
        try:
            client.get_me()
            status["get_me"] = "OK"
        except Exception as exc:
            status["get_me"] = str(exc)[:100]
        return {"ok": True, "data": status}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _file_age_hours(glob_pattern: str) -> int | None:
    best_mtime: float | None = None
    for path in Path().glob(glob_pattern):
        if path.is_file():
            mt = path.stat().st_mtime
            if best_mtime is None or mt > best_mtime:
                best_mtime = mt
    if best_mtime is None:
        return None
    return int((datetime.now().timestamp() - best_mtime) / 3600)
