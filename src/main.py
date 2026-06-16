from __future__ import annotations

import argparse
import importlib
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
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
    HHBudgetExceeded,
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
# Helpers
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


def _resolve_search_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge mode defaults with explicit CLI overrides."""
    mode = args.mode or "normal"
    if mode not in SEARCH_MODES:
        console.print(
            f"[yellow]Неизвестный режим {mode!r}, используется normal.[/yellow]"
        )
        mode = "normal"
    preset = SEARCH_MODES[mode].copy()

    # CLI overrides take precedence over mode defaults
    if args.max_pages is not None:
        preset["max_pages"] = args.max_pages
    if args.per_page is not None:
        preset["per_page"] = args.per_page

    return preset


def _should_fetch_detail(
    vacancy_id: str,
    storage: Storage,
    force_details: bool,
    detail_refresh_days: int | None,
) -> bool:
    """Decide whether a detail fetch is needed for the given vacancy_id.

    Returns True if detail should be fetched.
    """
    if force_details:
        return True

    with storage.connect() as connection:
        row = connection.execute(
            "SELECT description_text, last_seen_at FROM vacancies WHERE id = ?",
            (vacancy_id,),
        ).fetchone()

    if row is None:
        # New vacancy — always fetch
        return True

    desc = row["description_text"] or ""
    if not desc.strip():
        # Existing but empty description — fetch
        return True

    # Description exists. Check if it's older than refresh threshold.
    if detail_refresh_days is not None and detail_refresh_days > 0:
        last_seen = row["last_seen_at"]
        if last_seen:
            try:
                last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return False
            cutoff = datetime.now(timezone.utc) - timedelta(days=detail_refresh_days)
            if last_dt < cutoff:
                return True

    return False


def _print_run_estimate(
    selected: dict[str, Any],
    search_config: dict[str, Any],
    client: HHClient,
) -> int:
    """Print the run estimate table and return estimated total search requests."""
    total_queries = 0
    profile_names: list[str] = []
    query_list: list[str] = []
    for name, config in selected.items():
        profile_names.append(name)
        queries = config.get("queries", [])
        areas = [str(a) for a in (config.get("areas") or [None])]
        total_queries += len(queries) * len(areas)
        query_list.extend(f"{name}: {q} (area={a})" for q in queries for a in areas)

    max_pages = search_config["max_pages"]
    per_page = search_config["per_page"]
    est_search = total_queries * max_pages

    table = Table(title="Search Run Estimate")
    table.add_column("Parameter", style="bold")
    table.add_column("Value")

    table.add_row("Mode", search_config.get("_mode_name", "normal"))
    table.add_row("Auth mode", client.auth_mode)
    table.add_row("Profiles", ", ".join(profile_names))
    table.add_row("Total query × area combos", str(total_queries))
    table.add_row("Max pages per combo", str(max_pages))
    table.add_row("Per page", str(per_page))
    table.add_row(
        "Est. search requests",
        f"[yellow]{est_search}[/yellow] (profiles × queries × areas × pages)",
    )
    table.add_row(
        "Max requests per run (total budget)",
        str(search_config["max_requests_per_run"]),
    )
    table.add_row(
        "Max detail fetches per run",
        str(search_config["max_detail_fetches_per_run"]),
    )
    table.add_row(
        "Rate limiting",
        f"delay {client.delay_min}–{client.delay_max}s, "
        f"stop_on_429={client.stop_on_429}",
    )
    table.add_row(
        "Detail refresh",
        f"{os.getenv('HH_DETAIL_REFRESH_DAYS', '7')} days"
        if not search_config.get("_force_details")
        else "force (all details will be refreshed)",
    )

    console.print(table)

    if query_list:
        detail_table = Table(title="Query × Area Combinations")
        detail_table.add_column("#")
        detail_table.add_column("Profile / Query / Area")
        for i, line in enumerate(query_list[:30], 1):
            detail_table.add_row(str(i), line)
        if len(query_list) > 30:
            detail_table.add_row("...", f"and {len(query_list) - 30} more")
        console.print(detail_table)

    return est_search


def _print_run_summary(
    started: datetime,
    search_config: dict[str, Any],
    client: HHClient,
    profiles_processed: int,
    counters: dict[str, int],
) -> None:
    """Print the final run summary."""
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    budget = client.budget_summary()
    table = Table(title="Search Run Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    table.add_row("Mode", search_config.get("_mode_name", "normal"))
    table.add_row("Profiles processed", str(profiles_processed))
    table.add_row("Search requests made", str(client.stats_search_requests))
    table.add_row("Detail requests made", str(client.stats_detail_requests))
    table.add_row("New vacancies", str(counters.get("new_count", 0)))
    table.add_row("Updated vacancies", str(counters.get("updated_count", 0)))
    table.add_row(
        "Skipped (existing details)",
        str(counters.get("skipped_existing_details", 0)),
    )
    table.add_row(
        "Skipped by budget",
        str(counters.get("skipped_by_budget", 0)),
    )
    table.add_row("429 count", str(client.stats_429))
    table.add_row("Errors count", str(client.stats_errors))
    table.add_row(
        "Elapsed time",
        f"{elapsed:.1f}s" if elapsed < 120 else f"{elapsed / 60:.1f} min",
    )
    table.add_row(
        "Budget used",
        f"total={budget['total']}/{budget['max_requests']}, "
        f"detail={budget['detail']}/{budget['max_details']}",
    )

    console.print(table)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


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

    # Show rate limiting config
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


def _sample_vacancies() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    samples = [
        (
            "sample-ai-llm",
            "LLM / RAG Automation Engineer",
            "Signal AI",
            "Python, FastAPI, LangChain, RAG, API integrations and n8n automation.",
            ["Python", "RAG", "LangChain"],
            "Удаленная работа",
            2500,
            4000,
            "USD",
            "ai_automation",
        ),
        (
            "sample-ai-integration",
            "Systems Integration Engineer",
            "Flow Systems",
            "Webhooks, PostgreSQL, Docker and CRM/ERP integrations.",
            ["API", "PostgreSQL", "Docker"],
            "Удаленная работа",
            180000,
            260000,
            "RUR",
            "ai_automation",
        ),
        (
            "sample-ai-pm",
            "Technical Project Manager AI",
            "Automation Lab",
            "Technical specifications and business process automation for GenAI products.",
            ["GenAI", "Automation"],
            "Гибрид",
            None,
            None,
            None,
            "ai_automation",
        ),
        (
            "sample-bitrix",
            "Архитектор CRM Битрикс24",
            "CRM Practice",
            "Битрикс24, смарт-процессы, роботы, триггеры и права доступа.",
            ["Битрикс24", "CRM"],
            "Удаленная работа",
            150000,
            220000,
            "RUR",
            "bitrix_1c",
        ),
        (
            "sample-1c",
            "Системный аналитик 1С / CRM",
            "Business Stack",
            "Интеграции с 1С, BPMN, AS-IS, TO-BE и техническое задание.",
            ["1С", "BPMN"],
            "Гибрид",
            2000,
            3000,
            "USD",
            "bitrix_1c",
        ),
        (
            "sample-low",
            "Менеджер по продажам",
            "Sales Only",
            "Холодные звонки и выполнение плана продаж.",
            [],
            "Полный день",
            None,
            None,
            None,
            "bitrix_1c",
        ),
    ]
    result: list[dict[str, Any]] = []
    for (
        vacancy_id,
        name,
        employer,
        description,
        skills,
        schedule,
        salary_from,
        salary_to,
        currency,
        profile,
    ) in samples:
        result.append(
            {
                "id": vacancy_id,
                "name": name,
                "employer": {"id": f"employer-{vacancy_id}", "name": employer},
                "area": {"name": "Demo region"},
                "alternate_url": f"https://hh.ru/vacancy/{vacancy_id}",
                "published_at": now,
                "created_at": now,
                "archived": False,
                "salary": (
                    {"from": salary_from, "to": salary_to, "currency": currency}
                    if salary_from is not None or salary_to is not None
                    else None
                ),
                "schedule": {"name": schedule},
                "employment": {"name": "Полная занятость"},
                "experience": {"name": "От 3 до 6 лет"},
                "description": f"<p>{description}</p>",
                "key_skills": [{"name": skill} for skill in skills],
                "_source_profile": profile,
            }
        )
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
        "Status",
        "Score",
        "Profile",
        "Employer",
        "Title",
        "Area",
        "Updated",
        "URL",
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
    console.print(f"[green]{args.vacancy_id}: status={review['status']}[/green]")
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
        _review_storage().set_next_action(args.vacancy_id, args.action, next_action_at)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: следующее действие сохранено "
        f"на {next_action_at}[/green]"
    )
    return 0


# ---------------------------------------------------------------------------
# Search command
# ---------------------------------------------------------------------------


def command_search(args: argparse.Namespace) -> int:
    load_dotenv()

    try:
        profiles = load_search_profiles()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        console.print(f"[red]Не удалось прочитать поисковые профили: {exc}[/red]")
        return 2

    # Resolve search mode and config
    search_config = _resolve_search_config(args)
    search_config["_mode_name"] = args.mode or "normal"
    search_config["_force_details"] = args.force_details

    # Select profiles
    if args.profile:
        selected = {args.profile: profiles.get(args.profile)}
    elif search_config.get("single_profile"):
        # Smoke mode: pick the first enabled profile
        first_enabled = next(
            (n for n, c in profiles.items() if c and c.get("enabled", True)),
            None,
        )
        if first_enabled:
            selected = {first_enabled: profiles[first_enabled]}
        else:
            selected = {}
    else:
        selected = profiles

    # Filter enabled
    selected = {
        name: value
        for name, value in selected.items()
        if value and value.get("enabled", True)
    }

    if not selected:
        console.print("[red]Подходящие профили не найдены.[/red]")
        return 2

    # --- dry-run: show estimate and exit ---
    if args.dry_run:
        # Create a temp client just to show auth mode and rate limiting config
        client = HHClient()
        _print_run_estimate(selected, search_config, client)
        console.print(
            "\n[bold green]Dry-run complete. No API requests were made.[/bold green]"
        )
        return 0

    # --- real run: initialize services ---
    storage, client, rules = _services()

    # Set up budget
    client.set_budget(
        max_requests=search_config["max_requests_per_run"],
        max_details=search_config["max_detail_fetches_per_run"],
    )

    # Print estimate before starting
    est_search = _print_run_estimate(selected, search_config, client)

    # --- confirmation for deep mode ---
    if search_config.get("confirm") and not args.yes:
        from rich.prompt import Confirm

        console.print(
            f"\n[yellow]This may perform up to {est_search} search API requests "
            f"plus up to {search_config['max_detail_fetches_per_run']} detail requests.[/yellow]"
        )
        try:
            if not Confirm.ask("Continue?", default=False):
                console.print("[yellow]Отменено.[/yellow]")
                return 0
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Отменено.[/yellow]")
            return 0

    # Detail refresh threshold from env
    detail_refresh_days_str = os.getenv("HH_DETAIL_REFRESH_DAYS", "7")
    try:
        detail_refresh_days = int(detail_refresh_days_str)
    except ValueError:
        detail_refresh_days = 7

    max_pages = search_config["max_pages"]
    per_page = search_config["per_page"]
    force_details = search_config.get("_force_details", False)

    seen_this_run: set[str] = set()
    profiles_processed = 0
    run_counters: dict[str, int] = {
        "new_count": 0,
        "updated_count": 0,
        "skipped_existing_details": 0,
        "skipped_by_budget": 0,
    }
    run_started = datetime.now(timezone.utc)

    stop_all = False

    for profile_name, config in selected.items():
        if stop_all:
            break
        profiles_processed += 1
        for query in config.get("queries", []):
            if stop_all:
                break
            for area in config.get("areas", [None]):
                if stop_all:
                    break
                started = datetime.now(timezone.utc).isoformat()
                counters = {
                    "found_count": 0,
                    "loaded_count": 0,
                    "new_count": 0,
                    "updated_count": 0,
                }
                error: str | None = None

                try:
                    for page in range(max_pages):
                        # Check total request budget before search call
                        if not client.can_request("search"):
                            console.print(
                                "[yellow]Request budget reached. Partial results were saved.[/yellow]"
                            )
                            run_counters["skipped_by_budget"] += 1
                            stop_all = True
                            break

                        try:
                            result = client.search_vacancies(
                                query, area, page, per_page, config.get("params")
                            )
                        except HHBudgetExceeded:
                            console.print(
                                "[yellow]Request budget reached. Partial results were saved.[/yellow]"
                            )
                            run_counters["skipped_by_budget"] += 1
                            stop_all = True
                            break

                        items = result.get("items") or []
                        counters["found_count"] += len(items)

                        for summary in items:
                            vacancy_id = str(summary.get("id", ""))
                            if not vacancy_id or vacancy_id in seen_this_run:
                                continue
                            seen_this_run.add(vacancy_id)

                            # Smart detail fetch decision
                            try:
                                if _should_fetch_detail(
                                    vacancy_id,
                                    storage,
                                    force_details,
                                    detail_refresh_days,
                                ):
                                    # Check detail budget
                                    if not client.can_request("detail"):
                                        console.print(
                                            "[yellow]Detail request budget reached. "
                                            "Saving remaining vacancies without details.[/yellow]"
                                        )
                                        run_counters["skipped_by_budget"] += 1
                                        if storage.vacancy_exists(vacancy_id):
                                            # Existing — just touch, don't overwrite good data
                                            storage.touch_vacancy(vacancy_id)
                                            counters["updated_count"] += 1
                                        else:
                                            # New vacancy — save basic data from search summary
                                            vacancy = Vacancy.from_hh(
                                                summary, profile_name
                                            )
                                            is_new = storage.upsert_vacancy(vacancy)
                                            storage.upsert_score(
                                                score_vacancy(vacancy, rules)
                                            )
                                            counters[
                                                "new_count"
                                                if is_new
                                                else "updated_count"
                                            ] += 1
                                        counters["loaded_count"] += 1
                                        continue

                                    detail = client.get_vacancy(vacancy_id)
                                    vacancy = Vacancy.from_hh(detail, profile_name)
                                else:
                                    # Detail already exists — skip fetch, just touch last_seen_at
                                    run_counters["skipped_existing_details"] += 1
                                    storage.touch_vacancy(vacancy_id)
                                    counters["updated_count"] += 1
                                    counters["loaded_count"] += 1
                                    continue

                                is_new = storage.upsert_vacancy(vacancy)
                                storage.upsert_score(score_vacancy(vacancy, rules))
                                counters["loaded_count"] += 1
                                counters[
                                    "new_count" if is_new else "updated_count"
                                ] += 1

                            except HHBudgetExceeded:
                                console.print(
                                    "[yellow]Request budget reached. Partial results were saved.[/yellow]"
                                )
                                run_counters["skipped_by_budget"] += 1
                                stop_all = True
                                break
                            except (HHAPIError, ValueError) as exc:
                                logging.warning(
                                    "Вакансия %s пропущена: %s", vacancy_id, exc
                                )

                        # Stop pagination if we've reached the last page
                        if page + 1 >= int(result.get("pages", 0)) or not items:
                            break

                except HHConfigurationError as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    storage.add_search_run(
                        {
                            "started_at": started,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "profile_name": profile_name,
                            "query": query,
                            "area_id": str(area) if area is not None else None,
                            **counters,
                            "error": error,
                        }
                    )
                    console.print(f"[red]Поиск остановлен: {exc}[/red]")
                    return 2
                except HHAuthorizationRequired as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    storage.add_search_run(
                        {
                            "started_at": started,
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "profile_name": profile_name,
                            "query": query,
                            "area_id": str(area) if area is not None else None,
                            **counters,
                            "error": error,
                        }
                    )
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
                    # Check if it's a 429 stop
                    if "429" in str(exc) or "rate limit" in str(exc).lower():
                        console.print(
                            "[yellow]Search stopped due to HH API rate limit (429). "
                            "Partial results were saved.[/yellow]"
                        )
                        stop_all = True

                # Accumulate run counters
                for key in ("new_count", "updated_count"):
                    run_counters[key] += counters[key]

                storage.add_search_run(
                    {
                        "started_at": started,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "profile_name": profile_name,
                        "query": query,
                        "area_id": str(area) if area is not None else None,
                        **counters,
                        "error": error,
                    }
                )
                console.print(
                    f"{profile_name}: {query} / {area}: {counters['loaded_count']} загружено"
                )

    # --- run summary ---
    _print_run_summary(
        run_started, search_config, client, profiles_processed, run_counters
    )

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="career-signal-hh")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    search = sub.add_parser("search")
    search.add_argument(
        "--mode",
        choices=["smoke", "normal", "deep"],
        default=None,
        help="Search mode: smoke (small, fast), normal (daily), deep (full). "
        "Default: normal.",
    )
    search.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max pages for the selected mode.",
    )
    search.add_argument(
        "--per-page",
        type=int,
        default=None,
        help="Override per-page for the selected mode.",
    )
    search.add_argument("--profile", help="Limit search to a single profile.")
    search.add_argument(
        "--dry-run", action="store_true", help="Show estimate without API calls."
    )
    search.add_argument(
        "--force-details",
        action="store_true",
        help="Force refresh vacancy details even if already cached.",
    )
    search.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (e.g. for deep mode).",
    )
    search.set_defaults(func=command_search)

    # --- export ---
    export = sub.add_parser("export")
    export.add_argument("--min-score", type=int, default=0)
    export.add_argument("--profile", choices=["ai_automation", "bitrix_1c"])
    export.add_argument("--days", type=int)
    export.set_defaults(func=command_export)

    # --- top ---
    sub.add_parser("top").set_defaults(func=command_top)

    # --- stats ---
    sub.add_parser("stats").set_defaults(func=command_stats)

    # --- auth-check ---
    sub.add_parser("auth-check").set_defaults(func=command_auth_check)

    # --- doctor ---
    sub.add_parser("doctor").set_defaults(func=command_doctor)

    # --- profiles ---
    sub.add_parser("profiles").set_defaults(func=command_profiles)

    # --- sample-export ---
    sub.add_parser("sample-export").set_defaults(func=command_sample_export)

    # --- review ---
    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_list = review_sub.add_parser("list")
    review_list.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    review_list.add_argument("--min-score", type=int, default=0)
    review_list.add_argument("--limit", type=int, default=30)
    review_list.add_argument("--profile", choices=["ai_automation", "bitrix_1c"])
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
