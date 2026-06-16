from __future__ import annotations

import argparse

import yaml
from rich.console import Console
from rich.table import Table

from ..search_profiles import load_search_profiles

console = Console()


def command_profiles(_: argparse.Namespace) -> int:
    try:
        profiles = load_search_profiles()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        console.print(f"[red]Не удалось прочитать профили: {exc}[/red]")
        return 1
    table = Table(title="Поисковые профили")
    for column in [
        "Profile",
        "Enabled",
        "Queries",
        "Areas",
        "Schedules",
        "Experience",
        "Preview",
    ]:
        table.add_column(column)
    for name, config in profiles.items():
        params = config.get("params") or {}
        queries = config.get("queries") or []
        table.add_row(
            name,
            "yes" if config.get("enabled", True) else "no",
            str(len(queries)),
            str(len(config.get("areas") or [])),
            ", ".join(params.get("schedule") or []) or "-",
            ", ".join(params.get("experience") or []) or "-",
            " | ".join(str(query) for query in queries[:3]) or "-",
        )
    console.print(table)
    return 0
