from __future__ import annotations

import argparse
import importlib
import os
import sqlite3
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..hh_client import HHClient
from ..search_profiles import load_scoring_rules, load_search_profiles
from ..storage import Storage

console = Console()


def command_doctor(_: argparse.Namespace) -> int:
    load_dotenv()
    rows: list[tuple[str, str, str]] = []

    def add(check: str, status: str, details: str) -> None:
        colors = {"OK": "green", "WARN": "yellow", "FAIL": "red"}
        rows.append((check, f"[{colors[status]}]{status}[/{colors[status]}]", details))

    version = sys.version_info
    version_text = f"{version.major}.{version.minor}.{version.micro}"
    add(
        "Python version",
        "OK" if version >= (3, 11) else "FAIL",
        f"{version_text} (требуется 3.11+)",
    )
    add("Working directory", "OK", str(Path.cwd()))

    for filename, required in [
        (".env", False),
        (".env.example", True),
        ("config/search_profiles.yaml", True),
        ("config/scoring_rules.yaml", True),
    ]:
        path = Path(filename)
        status = "OK" if path.is_file() else ("FAIL" if required else "WARN")
        details = str(path.resolve()) if path.exists() else "Файл не найден"
        add(filename, status, details)

    for filename in ["config/search_profiles.yaml", "config/scoring_rules.yaml"]:
        try:
            content = (
                load_search_profiles(filename)
                if "search_profiles" in filename
                else load_scoring_rules(filename)
            )
            if not isinstance(content, dict):
                raise ValueError("корневое значение должно быть mapping")
            add(f"YAML: {filename}", "OK", "Конфигурация валидна")
        except (AttributeError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            add(f"YAML: {filename}", "FAIL", str(exc))

    for dirname in ["data", "exports"]:
        path = Path(dirname)
        try:
            path.mkdir(parents=True, exist_ok=True)
            add(f"Directory: {dirname}", "OK", str(path.resolve()))
        except OSError as exc:
            add(f"Directory: {dirname}", "FAIL", str(exc))

    auth_mode = os.getenv("HH_AUTH_MODE", "none").strip().lower()
    valid_modes = {"none", "application_token", "user_oauth"}
    add(
        "HH_AUTH_MODE",
        "OK" if auth_mode in valid_modes else "FAIL",
        auth_mode,
    )
    token_present = bool(os.getenv("HH_APP_ACCESS_TOKEN", "").strip())
    if auth_mode == "application_token":
        add(
            "HH_APP_ACCESS_TOKEN",
            "OK" if token_present else "WARN",
            "Указан" if token_present else "Не указан",
        )
    else:
        add("HH_APP_ACCESS_TOKEN", "OK", "Не требуется для текущего режима")

    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")
    add("DB_PATH", "OK", db_path)
    try:
        storage = Storage(db_path)
        with storage.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        add("SQLite", "OK", f"База доступна: {Path(db_path).resolve()}")
    except (OSError, sqlite3.Error) as exc:
        add("SQLite", "FAIL", str(exc))

    modules = [
        "requests",
        "dotenv",
        "pydantic",
        "yaml",
        "rich",
        "bs4",
        "dateutil",
        "src.hh_client",
        "src.storage",
        "src.scoring",
    ]
    try:
        for module_name in modules:
            importlib.import_module(module_name)
        add("Core imports", "OK", f"{len(modules)} модулей импортированы")
    except ImportError as exc:
        add("Core imports", "FAIL", str(exc))

    client = HHClient()
    add(
        "Rate limiting",
        "OK",
        f"delay {client.delay_min}–{client.delay_max}s, "
        f"stop_on_429={client.stop_on_429}, "
        f"cooldown_429={client.cooldown_429}s",
    )
    add(
        "Detail refresh",
        "OK",
        f"{os.getenv('HH_DETAIL_REFRESH_DAYS', '7')} days",
    )

    table = Table(title="CareerSignal HH Doctor")
    table.add_column("CHECK")
    table.add_column("STATUS")
    table.add_column("DETAILS")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    return 1 if any("[red]FAIL" in status for _, status, _ in rows) else 0
