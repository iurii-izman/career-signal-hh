from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from ..config import _services
from ..utils import json_loads, salary_to_str

console = Console()


def command_stats(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    stats = storage.stats()
    console.print(
        f"Всего: {stats['total']} | Новых 24ч: {stats['new_24h']} | "
        f"Средний score: {stats['avg_score'] or 0:.1f}"
    )
    console.print(f"Remote: {stats['remote']} | С зарплатой: {stats['with_salary']}")
    for label, key in [
        ("Профили", "profiles"),
        ("Работодатели", "employers"),
        ("Регионы", "areas"),
    ]:
        console.print(f"\n[bold]{label}[/bold]")
        for item in stats[key]:
            console.print(f"  {item['name'] or 'Не указано'}: {item['count']}")
    return 0


def command_top(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    table = Table(title="Top вакансий")
    for column in [
        "Score",
        "Profile",
        "Company",
        "Title",
        "Area",
        "Salary",
        "Format",
        "Published",
        "URL",
    ]:
        table.add_column(column)
    for row in storage.list_vacancies(limit=20):
        work = ", ".join(json_loads(row.get("work_format_flags_json"), []))
        table.add_row(
            str(row.get("total_score") or 0),
            row.get("best_profile") or "",
            row.get("employer_name") or "",
            row.get("name") or "",
            row.get("area_name") or "",
            salary_to_str(
                row.get("salary_from"),
                row.get("salary_to"),
                row.get("salary_currency"),
            ),
            work,
            (row.get("published_at") or "")[:10],
            row.get("alternate_url") or "",
        )
    console.print(table)
    return 0
