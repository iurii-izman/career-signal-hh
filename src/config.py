from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from .hh_client import HHClient
from .search_profiles import load_scoring_rules
from .storage import Storage

# ---------------------------------------------------------------------------
# Search mode presets
# ---------------------------------------------------------------------------

SEARCH_MODES: dict[str, dict[str, Any]] = {
    "smoke": {
        "max_pages": 1,
        "per_page": 10,
        "max_requests_per_run": 50,
        "max_detail_fetches_per_run": 25,
        "single_profile": True,
        "confirm": False,
    },
    "normal": {
        "max_pages": 2,
        "per_page": 25,
        "max_requests_per_run": 250,
        "max_detail_fetches_per_run": 150,
        "single_profile": False,
        "confirm": False,
    },
    "deep": {
        "max_pages": 3,
        "per_page": 50,
        "max_requests_per_run": 800,
        "max_detail_fetches_per_run": 500,
        "single_profile": False,
        "confirm": True,
    },
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _services() -> tuple[Storage, HHClient, dict[str, Any]]:
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    client = HHClient()
    return storage, client, load_scoring_rules()


def _short_body(value: Any) -> str:
    if value is None:
        return ""
    import json

    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 240 else text[:237] + "..."
