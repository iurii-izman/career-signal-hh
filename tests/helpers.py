"""Shared test helpers — fixtures, factories, CLI runner."""

from __future__ import annotations

import json
import os
import sqlite3
from argparse import Namespace
from pathlib import Path
from typing import Any

import yaml

from src.models import Vacancy
from src.storage import Storage

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ── DB factories ─────────────────────────────────────────────────────────────


def make_storage(tmp_path: Path, db_name: str = "test.sqlite") -> Storage:
    """Return a Storage pointed at an isolated SQLite file under tmp_path."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    return Storage(str(db_dir / db_name))


def make_raw_connection(tmp_path: Path, db_name: str = "test.sqlite") -> sqlite3.Connection:
    """Return a raw sqlite3.Connection to an empty DB (no migrations)."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_dir / db_name))
    conn.row_factory = sqlite3.Row
    return conn


# ── Fixture loaders ──────────────────────────────────────────────────────────


def load_fixture_json(name: str) -> dict[str, Any]:
    """Load a JSON fixture by filename (e.g. 'hh_vacancy_ai_good.json')."""
    path = FIXTURES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_yaml(name: str) -> dict[str, Any]:
    """Load a YAML fixture by filename."""
    path = FIXTURES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ── Vacancy factories ────────────────────────────────────────────────────────


def make_vacancy_from_fixture(
    name: str,
    source_profile: str | None = None,
    source_query: str | None = None,
) -> Vacancy:
    """Build a Vacancy model from a fixture JSON file."""
    data = load_fixture_json(name)
    return Vacancy.from_hh(data, source_profile=source_profile, source_query=source_query)


def seed_vacancies(storage: Storage, *fixture_names: str) -> list[Vacancy]:
    """Insert vacancies from fixture files into storage. Returns the list."""
    vacancies: list[Vacancy] = []
    for name in fixture_names:
        v = make_vacancy_from_fixture(name)
        storage.upsert_vacancy(v)
        vacancies.append(v)
    return vacancies


def seed_vacancies_with_scores(
    storage: Storage,
    preset_name: str,
    preset: dict[str, Any],
    *fixture_names: str,
) -> list[Vacancy]:
    """Insert vacancies and compute score_details + scores for each."""
    from src.scoring_v2 import _to_score_result, compute_score_details

    vacancies: list[Vacancy] = []
    for name in fixture_names:
        v = make_vacancy_from_fixture(
            name,
            source_profile=preset_name,
            source_query=(preset.get("search_terms") or [None])[0],
        )
        storage.upsert_vacancy(v)
        details = compute_score_details(v, {**preset, "_name": preset_name})
        storage.upsert_score_details(details)
        storage.upsert_score(_to_score_result(details))
        vacancies.append(v)
    return vacancies


# ── CLI runner ───────────────────────────────────────────────────────────────


def run_cli(args: list[str], env: dict[str, str] | None = None) -> int:
    """Parse *args* as if they were CLI arguments and invoke the command.

    Returns the exit code.
    """
    from src.cli import build_parser

    parser = build_parser()
    if env:
        for k, v in env.items():
            os.environ[k] = v
    try:
        parsed = parser.parse_args(args)
        return int(parsed.func(parsed))
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1


def parse_args(args: list[str]) -> Namespace:
    """Parse CLI arguments and return the Namespace without executing."""
    from src.cli import build_parser

    parser = build_parser()
    return parser.parse_args(args)
