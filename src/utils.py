from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from dateutil.parser import isoparse


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().replace("ё", "е")).strip()


def safe_get(data: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def parse_datetime(value: str | None) -> datetime | None:
    try:
        return isoparse(value) if value else None
    except (TypeError, ValueError):
        return None


def salary_to_str(
    salary_from: int | None, salary_to: int | None, currency: str | None
) -> str:
    if salary_from is None and salary_to is None:
        return "Не указана"
    unit = f" {currency}" if currency else ""
    if salary_from is not None and salary_to is not None:
        return f"{salary_from:,}–{salary_to:,}{unit}".replace(",", " ")
    if salary_from is not None:
        return f"от {salary_from:,}{unit}".replace(",", " ")
    return f"до {salary_to:,}{unit}".replace(",", " ")


def truncate(value: str | None, length: int = 240) -> str:
    text = value or ""
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def redact_secrets(value: str | None) -> str | None:
    """Replace known token values from text with a fixed placeholder."""
    if value is None:
        return None
    text = value
    for env_name in ("HH_APP_ACCESS_TOKEN", "HH_USER_ACCESS_TOKEN"):
        token = os.getenv(env_name, "").strip()
        if token:
            text = text.replace(token, "[REDACTED]")
    return text
