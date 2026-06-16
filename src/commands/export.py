from __future__ import annotations

import argparse

from rich.console import Console

from ..config import _services
from ..exporter_csv import export_csv, export_jsonl
from ..exporter_html import export_html

console = Console()


def command_export(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    # --preset is an alias for --profile
    profile = args.preset or args.profile
    rows = storage.list_vacancies(args.min_score, profile, args.days)
    export_html(rows, "exports/vacancies_report.html")
    export_csv(rows, "exports/vacancies.csv")
    export_jsonl(rows, "exports/vacancies.jsonl")
    console.print(f"[green]Экспортировано вакансий: {len(rows)}[/green]")
    return 0
