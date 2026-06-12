from __future__ import annotations

import argparse
import importlib
import logging
import os
import random
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .exporter_csv import export_csv, export_jsonl
from .exporter_html import export_html
from .hh_client import (
    HHAPIError,
    HHAuthorizationRequired,
    HHClient,
    HHConfigurationError,
)
from .models import Vacancy
from .scoring import score_vacancy
from .search_profiles import load_scoring_rules, load_search_profiles
from .storage import REVIEW_STATUSES, Storage
from .utils import json_loads, salary_to_str

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


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


def command_auth_check(_: argparse.Namespace) -> int:
    load_dotenv()
    client = HHClient()
    token_present = bool(client.app_access_token)
    console.print(f"HH_AUTH_MODE: [bold]{client.auth_mode}[/bold]")
    console.print(
        "HH_APP_ACCESS_TOKEN: "
        + ("[green]указан[/green]" if token_present else "[yellow]не указан[/yellow]")
    )
    console.print(f"HH_USER_AGENT: {client.user_agent}")

    table = Table(title="Проверка доступа HH API")
    table.add_column("Проверка")
    table.add_column("Результат")
    table.add_column("Status")
    table.add_column("Объяснение")
    checks = [
        ("GET /me", client.get_me),
        (
            "GET /vacancies",
            lambda: client.search_vacancies("python", per_page=1),
        ),
    ]
    failed = False
    for label, operation in checks:
        try:
            operation()
            table.add_row(label, "[green]OK[/green]", "200", "Доступ разрешён")
        except NotImplementedError as exc:
            failed = True
            table.add_row(label, "[red]FAIL[/red]", "-", str(exc))
        except HHAPIError as exc:
            failed = True
            status = str(exc.status_code) if exc.status_code is not None else "-"
            explanation = str(exc)
            body = _short_body(exc.body)
            if body and body not in explanation:
                explanation = f"{explanation}\nBody: {body}"
            table.add_row(label, "[red]FAIL[/red]", status, explanation)
        except Exception as exc:
            failed = True
            table.add_row(label, "[red]FAIL[/red]", "-", f"Ошибка соединения: {exc}")
    console.print(table)
    return 1 if failed else 0


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
            content = load_search_profiles(filename) if "search_profiles" in filename else load_scoring_rules(filename)
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

    table = Table(title="CareerSignal HH Doctor")
    table.add_column("CHECK")
    table.add_column("STATUS")
    table.add_column("DETAILS")
    for row in rows:
        table.add_row(*row)
    console.print(table)
    return 1 if any("[red]FAIL" in status for _, status, _ in rows) else 0


def command_profiles(_: argparse.Namespace) -> int:
    try:
        profiles = load_search_profiles()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        console.print(f"[red]Не удалось прочитать профили: {exc}[/red]")
        return 1
    table = Table(title="Поисковые профили")
    for column in [
        "Profile", "Enabled", "Queries", "Areas", "Schedules", "Experience", "Preview",
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


def _sample_vacancies() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    samples = [
        ("sample-ai-llm", "LLM / RAG Automation Engineer", "Signal AI", "Python, FastAPI, LangChain, RAG, API integrations and n8n automation.", ["Python", "RAG", "LangChain"], "Удаленная работа", 2500, 4000, "USD", "ai_automation"),
        ("sample-ai-integration", "Systems Integration Engineer", "Flow Systems", "Webhooks, PostgreSQL, Docker and CRM/ERP integrations.", ["API", "PostgreSQL", "Docker"], "Удаленная работа", 180000, 260000, "RUR", "ai_automation"),
        ("sample-ai-pm", "Technical Project Manager AI", "Automation Lab", "Technical specifications and business process automation for GenAI products.", ["GenAI", "Automation"], "Гибрид", None, None, None, "ai_automation"),
        ("sample-bitrix", "Архитектор CRM Битрикс24", "CRM Practice", "Битрикс24, смарт-процессы, роботы, триггеры и права доступа.", ["Битрикс24", "CRM"], "Удаленная работа", 150000, 220000, "RUR", "bitrix_1c"),
        ("sample-1c", "Системный аналитик 1С / CRM", "Business Stack", "Интеграции с 1С, BPMN, AS-IS, TO-BE и техническое задание.", ["1С", "BPMN"], "Гибрид", 2000, 3000, "USD", "bitrix_1c"),
        ("sample-low", "Менеджер по продажам", "Sales Only", "Холодные звонки и выполнение плана продаж.", [], "Полный день", None, None, None, "bitrix_1c"),
    ]
    result: list[dict[str, Any]] = []
    for vacancy_id, name, employer, description, skills, schedule, salary_from, salary_to, currency, profile in samples:
        result.append({
            "id": vacancy_id,
            "name": name,
            "employer": {"id": f"employer-{vacancy_id}", "name": employer},
            "area": {"name": "Demo region"},
            "alternate_url": f"https://hh.ru/vacancy/{vacancy_id}",
            "published_at": now,
            "created_at": now,
            "archived": False,
            "salary": {"from": salary_from, "to": salary_to, "currency": currency} if salary_from is not None or salary_to is not None else None,
            "schedule": {"name": schedule},
            "employment": {"name": "Полная занятость"},
            "experience": {"name": "От 3 до 6 лет"},
            "description": f"<p>{description}</p>",
            "key_skills": [{"name": skill} for skill in skills],
            "_source_profile": profile,
        })
    return result


def command_sample_export(_: argparse.Namespace) -> int:
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    rules = load_scoring_rules()
    for item in _sample_vacancies():
        source_profile = item.pop("_source_profile")
        vacancy = Vacancy.from_hh(item, source_profile)
        storage.upsert_vacancy(vacancy)
        storage.upsert_score(score_vacancy(vacancy, rules))
    storage.set_review_status("sample-ai-llm", "interesting")
    storage.set_review_status("sample-ai-pm", "maybe")
    storage.set_review_status("sample-low", "rejected")
    storage.mark_applied("sample-bitrix", date.today().isoformat())
    rows = storage.list_vacancies()
    export_html(rows, "exports/vacancies_report.html")
    export_csv(rows, "exports/vacancies.csv")
    export_jsonl(rows, "exports/vacancies.jsonl")
    console.print(
        f"[green]Добавлено mock-вакансий: 6. Экспортировано записей: {len(rows)}.[/green]"
    )
    console.print("HTML: exports/vacancies_report.html")
    return 0


def _review_storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def _normalize_review_date(value: str) -> str:
    if value.strip().lower() == "today":
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(
            f"Некорректная дата {value!r}. Используйте today или YYYY-MM-DD."
        ) from exc


def command_review_list(args: argparse.Namespace) -> int:
    storage = _review_storage()
    try:
        rows = storage.list_reviewed_vacancies(
            status=args.status,
            min_score=args.min_score,
            limit=args.limit,
            profile=args.profile,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    table = Table(title="Manual vacancy review")
    for column in [
        "Status", "Score", "Profile", "Employer", "Title", "Area", "Updated", "URL",
    ]:
        table.add_column(column)
    for row in rows:
        table.add_row(
            row.get("review_status") or "new",
            str(row.get("total_score") or 0),
            row.get("best_profile") or "",
            row.get("employer_name") or "",
            row.get("name") or "",
            row.get("area_name") or "",
            (row.get("review_updated_at") or "")[:19],
            row.get("alternate_url") or "",
        )
    console.print(table)
    return 0


def command_review_set(args: argparse.Namespace) -> int:
    try:
        review = _review_storage().set_review_status(args.vacancy_id, args.status)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: status={review['status']}[/green]"
    )
    return 0


def command_review_note(args: argparse.Namespace) -> int:
    try:
        _review_storage().set_review_note(args.vacancy_id, args.note)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(f"[green]{args.vacancy_id}: заметка сохранена[/green]")
    return 0


def command_review_apply(args: argparse.Namespace) -> int:
    try:
        applied_at = _normalize_review_date(args.date)
        _review_storage().mark_applied(args.vacancy_id, applied_at)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: status=applied, applied_at={applied_at}[/green]"
    )
    return 0


def command_review_next(args: argparse.Namespace) -> int:
    try:
        next_action_at = _normalize_review_date(args.date)
        _review_storage().set_next_action(
            args.vacancy_id, args.action, next_action_at
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: следующее действие сохранено "
        f"на {next_action_at}[/green]"
    )
    return 0


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
                except HHConfigurationError as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    storage.add_search_run({
                        "started_at": started,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "profile_name": profile_name, "query": query,
                        "area_id": str(area) if area is not None else None,
                        **counters, "error": error,
                    })
                    console.print(f"[red]Поиск остановлен: {exc}[/red]")
                    return 2
                except HHAuthorizationRequired as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    storage.add_search_run({
                        "started_at": started,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "profile_name": profile_name, "query": query,
                        "area_id": str(area) if area is not None else None,
                        **counters, "error": error,
                    })
                    console.print(
                        "[yellow]Поиск остановлен: HH API сейчас требует "
                        "авторизацию приложения для доступа к вакансиям.[/yellow]"
                    )
                    return 3
                except NotImplementedError as exc:
                    logging.error("%s", exc)
                    console.print(f"[red]Поиск остановлен: {exc}[/red]")
                    return 4
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
    sub.add_parser("auth-check").set_defaults(func=command_auth_check)
    sub.add_parser("doctor").set_defaults(func=command_doctor)
    sub.add_parser("profiles").set_defaults(func=command_profiles)
    sub.add_parser("sample-export").set_defaults(func=command_sample_export)
    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_list = review_sub.add_parser("list")
    review_list.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    review_list.add_argument("--min-score", type=int, default=0)
    review_list.add_argument("--limit", type=int, default=30)
    review_list.add_argument(
        "--profile", choices=["ai_automation", "bitrix_1c"]
    )
    review_list.set_defaults(func=command_review_list)
    review_set = review_sub.add_parser("set")
    review_set.add_argument("vacancy_id")
    review_set.add_argument("--status", required=True, choices=sorted(REVIEW_STATUSES))
    review_set.set_defaults(func=command_review_set)
    review_note = review_sub.add_parser("note")
    review_note.add_argument("vacancy_id")
    review_note.add_argument("--note", required=True)
    review_note.set_defaults(func=command_review_note)
    review_apply = review_sub.add_parser("apply")
    review_apply.add_argument("vacancy_id")
    review_apply.add_argument("--date", default="today")
    review_apply.set_defaults(func=command_review_apply)
    review_next = review_sub.add_parser("next")
    review_next.add_argument("vacancy_id")
    review_next.add_argument("--action", required=True)
    review_next.add_argument("--date", required=True)
    review_next.set_defaults(func=command_review_next)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
