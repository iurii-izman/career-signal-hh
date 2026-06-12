from __future__ import annotations

import argparse
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .exporter_csv import export_csv, export_jsonl
from .exporter_html import export_html
from .hh_client import HHAPIError, HHClient
from .models import Vacancy
from .scoring import score_vacancy
from .search_profiles import load_scoring_rules, load_search_profiles
from .storage import Storage
from .utils import json_loads, salary_to_str

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _services() -> tuple[Storage, HHClient, dict[str, Any]]:
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    client = HHClient(os.getenv("HH_USER_AGENT", "CareerSignalHH/0.1"))
    return storage, client, load_scoring_rules()


def command_search(args: argparse.Namespace) -> int:
    profiles = load_search_profiles()
    selected = {args.profile: profiles.get(args.profile)} if args.profile else profiles
    selected = {name: value for name, value in selected.items() if value and value.get("enabled", True)}
    if not selected:
        console.print("[red]Подходящие профили не найдены.[/red]")
        return 2
    if args.dry_run:
        for name, config in selected.items():
            for query in config.get("queries", []):
                for area in config.get("areas", [None]):
                    console.print(name, query, f"area={area}", config.get("params", {}))
        return 0
    storage, client, rules = _services()
    delay_min = float(os.getenv("REQUEST_DELAY_MIN", "0.3"))
    delay_max = float(os.getenv("REQUEST_DELAY_MAX", "0.7"))
    seen_this_run: set[str] = set()
    for profile_name, config in selected.items():
        for query in config.get("queries", []):
            for area in config.get("areas", [None]):
                started = datetime.now(timezone.utc).isoformat()
                counters = {"found_count": 0, "loaded_count": 0, "new_count": 0, "updated_count": 0}
                error: str | None = None
                try:
                    for page in range(args.max_pages):
                        result = client.search_vacancies(
                            query, area, page, args.per_page, config.get("params")
                        )
                        items = result.get("items") or []
                        counters["found_count"] += len(items)
                        for summary in items:
                            vacancy_id = str(summary.get("id", ""))
                            if not vacancy_id or vacancy_id in seen_this_run:
                                continue
                            seen_this_run.add(vacancy_id)
                            try:
                                detail = client.get_vacancy(vacancy_id)
                                vacancy = Vacancy.from_hh(detail, profile_name)
                                is_new = storage.upsert_vacancy(vacancy)
                                storage.upsert_score(score_vacancy(vacancy, rules))
                                counters["loaded_count"] += 1
                                counters["new_count" if is_new else "updated_count"] += 1
                            except (HHAPIError, ValueError) as exc:
                                logging.warning("Вакансия %s пропущена: %s", vacancy_id, exc)
                            time.sleep(random.uniform(delay_min, delay_max))
                        if page + 1 >= int(result.get("pages", 0)) or not items:
                            break
                        time.sleep(random.uniform(delay_min, delay_max))
                except HHAPIError as exc:
                    error = str(exc)
                    logging.error("%s / %s / %s: %s", profile_name, query, area, exc)
                storage.add_search_run({
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "profile_name": profile_name, "query": query,
                    "area_id": str(area) if area is not None else None,
                    **counters, "error": error,
                })
                console.print(f"{profile_name}: {query} / {area}: {counters['loaded_count']} загружено")
    return 0


def command_export(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    rows = storage.list_vacancies(args.min_score, args.profile, args.days)
    export_html(rows, "exports/vacancies_report.html")
    export_csv(rows, "exports/vacancies.csv")
    export_jsonl(rows, "exports/vacancies.jsonl")
    console.print(f"[green]Экспортировано вакансий: {len(rows)}[/green]")
    return 0


def command_top(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    table = Table(title="Top вакансий")
    for column in ["Score", "Profile", "Company", "Title", "Area", "Salary", "Format", "Published", "URL"]:
        table.add_column(column)
    for row in storage.list_vacancies(limit=20):
        work = ", ".join(json_loads(row.get("work_format_flags_json"), []))
        table.add_row(
            str(row.get("total_score") or 0), row.get("best_profile") or "",
            row.get("employer_name") or "", row.get("name") or "",
            row.get("area_name") or "", salary_to_str(row.get("salary_from"), row.get("salary_to"), row.get("salary_currency")),
            work, (row.get("published_at") or "")[:10], row.get("alternate_url") or "",
        )
    console.print(table)
    return 0


def command_stats(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    stats = storage.stats()
    console.print(f"Всего: {stats['total']} | Новых 24ч: {stats['new_24h']} | Средний score: {stats['avg_score'] or 0:.1f}")
    console.print(f"Remote: {stats['remote']} | С зарплатой: {stats['with_salary']}")
    for label, key in [("Профили", "profiles"), ("Работодатели", "employers"), ("Регионы", "areas")]:
        console.print(f"\n[bold]{label}[/bold]")
        for item in stats[key]:
            console.print(f"  {item['name'] or 'Не указано'}: {item['count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="career-signal-hh")
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search")
    search.add_argument("--max-pages", type=int, default=3)
    search.add_argument("--per-page", type=int, default=50)
    search.add_argument("--profile")
    search.add_argument("--dry-run", action="store_true")
    search.set_defaults(func=command_search)
    export = sub.add_parser("export")
    export.add_argument("--min-score", type=int, default=0)
    export.add_argument("--profile", choices=["ai_automation", "bitrix_1c"])
    export.add_argument("--days", type=int)
    export.set_defaults(func=command_export)
    sub.add_parser("top").set_defaults(func=command_top)
    sub.add_parser("stats").set_defaults(func=command_stats)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
