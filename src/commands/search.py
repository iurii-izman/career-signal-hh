from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from typing import Any

import yaml
from rich.console import Console
from rich.prompt import Confirm

from ..config import SEARCH_MODES, _services
from ..hh_client import (
    HHAPIError,
    HHAuthorizationRequired,
    HHBudgetExceeded,
    HHClient,
    HHConfigurationError,
)
from ..models import Vacancy
from ..scoring import score_vacancy
from ..search_profiles import load_search_profiles
from ..services.search_runner import print_run_estimate, print_run_summary

console = Console()


def _resolve_search_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge mode defaults with explicit CLI overrides."""
    mode = args.mode or "normal"
    if mode not in SEARCH_MODES:
        console.print(
            f"[yellow]Неизвестный режим {mode!r}, используется normal.[/yellow]"
        )
        mode = "normal"
    preset = SEARCH_MODES[mode].copy()

    if args.max_pages is not None:
        preset["max_pages"] = args.max_pages
    if args.per_page is not None:
        preset["per_page"] = args.per_page

    return preset


def command_search(args: argparse.Namespace) -> int:
    try:
        profiles = load_search_profiles()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        console.print(f"[red]Не удалось прочитать поисковые профили: {exc}[/red]")
        return 2

    search_config = _resolve_search_config(args)
    search_config["_mode_name"] = args.mode or "normal"
    search_config["_force_details"] = args.force_details
    verbose = args.verbose

    if args.profile:
        selected = {args.profile: profiles.get(args.profile)}
    elif search_config.get("single_profile"):
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

    selected = {
        name: value
        for name, value in selected.items()
        if value and value.get("enabled", True)
    }

    if not selected:
        console.print("[red]Подходящие профили не найдены.[/red]")
        return 2

    if args.dry_run:
        client = HHClient()
        print_run_estimate(selected, search_config, client)
        console.print(
            "\n[bold green]Dry-run complete. No API requests were made.[/bold green]"
        )
        return 0

    storage, client, rules = _services()

    client.set_budget(
        max_requests=search_config["max_requests_per_run"],
        max_details=search_config["max_detail_fetches_per_run"],
    )

    est_search = print_run_estimate(selected, search_config, client)

    if search_config.get("confirm") and not args.yes:
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

    try:
        detail_refresh_days = int(os.getenv("HH_DETAIL_REFRESH_DAYS", "7"))
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
    exit_code = 0
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
                        if not client.can_request("search"):
                            console.print(
                                "[yellow]Request budget reached. "
                                "Partial results were saved.[/yellow]"
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
                                "[yellow]Request budget reached. "
                                "Partial results were saved.[/yellow]"
                            )
                            run_counters["skipped_by_budget"] += 1
                            stop_all = True
                            break

                        items = result.get("items") or []
                        counters["found_count"] += len(items)
                        if verbose:
                            console.print(f"  page {page + 1}: {len(items)} items")

                        for summary in items:
                            vacancy_id = str(summary.get("id", ""))
                            if not vacancy_id or vacancy_id in seen_this_run:
                                continue
                            seen_this_run.add(vacancy_id)

                            try:
                                if storage.detail_needed(
                                    vacancy_id,
                                    force=force_details,
                                    refresh_days=detail_refresh_days,
                                ):
                                    if not client.can_request("detail"):
                                        if not run_counters["skipped_by_budget"]:
                                            console.print(
                                                "[yellow]Detail request budget reached. "
                                                "Saving remaining vacancies without details.[/yellow]"
                                            )
                                        run_counters["skipped_by_budget"] += 1
                                        if storage.vacancy_exists(vacancy_id):
                                            storage.touch_vacancy(vacancy_id)
                                            counters["updated_count"] += 1
                                        else:
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
                                    if verbose:
                                        console.print(
                                            f"    detail: {vacancy.name[:60]}"
                                        )
                                else:
                                    run_counters["skipped_existing_details"] += 1
                                    storage.touch_vacancy(vacancy_id)
                                    counters["updated_count"] += 1
                                    counters["loaded_count"] += 1
                                    if verbose:
                                        console.print(
                                            f"    skip: {summary.get('name', '')[:60]}"
                                        )
                                    continue

                                is_new = storage.upsert_vacancy(vacancy)
                                storage.upsert_score(score_vacancy(vacancy, rules))
                                counters["loaded_count"] += 1
                                counters[
                                    "new_count" if is_new else "updated_count"
                                ] += 1

                            except HHBudgetExceeded:
                                console.print(
                                    "[yellow]Request budget reached. "
                                    "Partial results were saved.[/yellow]"
                                )
                                run_counters["skipped_by_budget"] += 1
                                stop_all = True
                                break
                            except (HHAPIError, ValueError) as exc:
                                logging.warning(
                                    "Вакансия %s пропущена: %s", vacancy_id, exc
                                )

                        if page + 1 >= int(result.get("pages", 0)) or not items:
                            break

                except HHConfigurationError as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    console.print(f"[red]Поиск остановлен: {exc}[/red]")
                    exit_code = 2
                    stop_all = True
                except HHAuthorizationRequired as exc:
                    error = str(exc)
                    logging.error("%s", exc)
                    console.print(
                        "[yellow]Поиск остановлен: HH API сейчас требует "
                        "авторизацию приложения для доступа к вакансиям.[/yellow]"
                    )
                    exit_code = 3
                    stop_all = True
                except NotImplementedError as exc:
                    logging.error("%s", exc)
                    console.print(f"[red]Поиск остановлен: {exc}[/red]")
                    exit_code = 4
                    stop_all = True
                except HHAPIError as exc:
                    error = str(exc)
                    logging.error("%s / %s / %s: %s", profile_name, query, area, exc)
                    if "429" in str(exc) or "rate limit" in str(exc).lower():
                        console.print(
                            "[yellow]Search stopped due to HH API rate limit (429). "
                            "Partial results were saved.[/yellow]"
                        )
                        stop_all = True

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
                    f"{profile_name}: {query} / {area}: "
                    f"{counters['loaded_count']} загружено"
                )

    print_run_summary(
        run_started, search_config, client, profiles_processed, run_counters
    )

    return exit_code
