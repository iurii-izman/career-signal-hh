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
from ..scoring_v2 import score_by_preset
from ..search_presets import create_adhoc_preset, get_preset, list_presets
from ..search_profiles import load_search_profiles
from ..services.search_runner import print_run_estimate, print_run_summary

console = Console()


def _resolve_search_config(args: argparse.Namespace) -> dict[str, Any]:
    mode = args.mode or "normal"
    if mode not in SEARCH_MODES:
        console.print(
            f"[yellow]Неизвестный режим {mode!r}, используется normal.[/yellow]"
        )
        mode = "normal"
    cfg = SEARCH_MODES[mode].copy()
    if args.max_pages is not None:
        cfg["max_pages"] = args.max_pages
    if args.per_page is not None:
        cfg["per_page"] = args.per_page
    return cfg


def _build_preset_search_units(preset: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a preset into search units. Each unit carries its own preset object."""
    search_terms = preset.get("search_terms", [])
    areas = preset.get("areas", [])
    schedule = preset.get("schedule", [])
    experience = preset.get("experience", [])

    if not areas:
        areas = [None]
    if not isinstance(areas, list):
        areas = [areas]

    params: dict[str, Any] = {}
    if schedule:
        params["schedule"] = schedule
    if experience:
        params["experience"] = experience

    source = preset["_name"]
    mode = preset.get("_source", "preset")

    units = []
    for term in search_terms:
        for area in areas:
            units.append(
                {
                    "query": term,
                    "area": area,
                    "params": params,
                    "source": source,
                    "mode": mode,
                    "preset": preset,
                }
            )
    return units


def _build_legacy_search_units(selected: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert legacy profiles into search units."""
    units = []
    for profile_name, config in selected.items():
        for query in config.get("queries", []):
            for area in config.get("areas", [None]):
                units.append(
                    {
                        "query": query,
                        "area": area,
                        "params": config.get("params"),
                        "source": profile_name,
                        "mode": "legacy",
                        "preset": None,
                    }
                )
    return units


def _build_estimate_selected(search_units: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a 'selected' dict compatible with print_run_estimate."""
    by_source: dict[str, dict[str, Any]] = {}
    for unit in search_units:
        src = unit["source"]
        if src not in by_source:
            by_source[src] = {"queries": [], "areas": [], "params": unit.get("params")}
        by_source[src]["queries"].append(unit["query"])
        area_display = unit["area"] if unit["area"] is not None else "all"
        by_source[src]["areas"].append(area_display)
    for src in by_source:
        by_source[src]["queries"] = list(dict.fromkeys(by_source[src]["queries"]))
        by_source[src]["areas"] = list(dict.fromkeys(by_source[src]["areas"]))
    return by_source


def command_search(args: argparse.Namespace) -> int:
    search_config = _resolve_search_config(args)
    search_config["_mode_name"] = args.mode or "normal"
    search_config["_force_details"] = args.force_details
    verbose = args.verbose

    search_units: list[dict[str, Any]] = []
    rules = None  # legacy scoring rules, loaded on demand

    if args.adhoc:
        include_list = [k.strip() for k in (args.include or "").split(",") if k.strip()]
        exclude_list = [k.strip() for k in (args.exclude or "").split(",") if k.strip()]
        if not include_list:
            console.print(
                "[red]--adhoc requires --include with at least one keyword.[/red]"
            )
            return 2
        remote_only = args.remote_only if args.remote_only is not None else True
        preset = create_adhoc_preset(
            include_list, exclude_list, remote_only=remote_only
        )
        search_units = _build_preset_search_units(preset)
        search_config["_mode_name"] = f"adhoc ({preset['_name']})"

    elif args.preset:
        preset = get_preset(args.preset)
        if preset is None:
            console.print(f"[red]Preset '{args.preset}' not found.[/red]")
            return 2
        search_units = _build_preset_search_units(preset)

    elif args.profile:
        try:
            profiles = load_search_profiles()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            console.print(f"[red]Не удалось прочитать поисковые профили: {exc}[/red]")
            return 2
        selected = {args.profile: profiles.get(args.profile)}
        selected = {n: v for n, v in selected.items() if v and v.get("enabled", True)}
        if not selected:
            console.print(f"[red]Profile '{args.profile}' not found or disabled.[/red]")
            return 2
        search_units = _build_legacy_search_units(selected)

    else:
        # Default: presets first, then legacy fallback
        presets = list_presets()
        if presets:
            # Smoke mode: only first enabled preset
            if search_config.get("single_profile"):
                presets = presets[:1]
            for p in presets:
                search_units.extend(_build_preset_search_units(p))
        else:
            try:
                profiles = load_search_profiles()
            except (OSError, ValueError, yaml.YAMLError) as exc:
                console.print(
                    f"[red]Не удалось прочитать поисковые профили: {exc}[/red]"
                )
                return 2
            profiles = {
                n: v for n, v in profiles.items() if v and v.get("enabled", True)
            }
            if not profiles:
                console.print("[red]Нет enabled profiles или presets.[/red]")
                return 2
            if search_config.get("single_profile"):
                first = next(iter(profiles.items()))
                profiles = {first[0]: first[1]}
            search_units = _build_legacy_search_units(profiles)

    if not search_units:
        console.print("[red]Нет search units для выполнения.[/red]")
        return 2

    # Dry-run
    if args.dry_run:
        client = HHClient()
        estimate_selected = _build_estimate_selected(search_units)
        print_run_estimate(estimate_selected, search_config, client)
        console.print(
            "\n[bold green]Dry-run complete. No API requests were made.[/bold green]"
        )
        return 0

    # Real run
    storage, client, _rules = _services()
    if rules is None:
        rules = _rules

    client.set_budget(
        max_requests=search_config["max_requests_per_run"],
        max_details=search_config["max_detail_fetches_per_run"],
    )

    estimate_selected = _build_estimate_selected(search_units)
    est_search = print_run_estimate(estimate_selected, search_config, client)

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

    for unit in search_units:
        if stop_all:
            break
        profiles_processed += 1
        query = unit["query"]
        area = unit["area"]
        profile_name = unit["source"]
        params = unit.get("params")

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
                        "[yellow]Request budget reached. Partial results were saved.[/yellow]"
                    )
                    run_counters["skipped_by_budget"] += 1
                    stop_all = True
                    break

                try:
                    result = client.search_vacancies(
                        query, area, page, per_page, params
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
                                        "[yellow]Detail request budget reached. Saving remaining vacancies without details.[/yellow]"
                                    )
                                run_counters["skipped_by_budget"] += 1
                                if storage.vacancy_exists(vacancy_id):
                                    storage.touch_vacancy(vacancy_id)
                                    counters["updated_count"] += 1
                                else:
                                    vacancy = Vacancy.from_hh(summary, profile_name)
                                    is_new = storage.upsert_vacancy(vacancy)
                                    _score_and_store(storage, vacancy, rules, unit)
                                    counters[
                                        "new_count" if is_new else "updated_count"
                                    ] += 1
                                counters["loaded_count"] += 1
                                continue

                            detail = client.get_vacancy(vacancy_id)
                            vacancy = Vacancy.from_hh(detail, profile_name)
                            if verbose:
                                console.print(f"    detail: {vacancy.name[:60]}")
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
                        _score_and_store(storage, vacancy, rules, unit)
                        counters["loaded_count"] += 1
                        counters["new_count" if is_new else "updated_count"] += 1

                    except HHBudgetExceeded:
                        console.print(
                            "[yellow]Request budget reached. Partial results were saved.[/yellow]"
                        )
                        run_counters["skipped_by_budget"] += 1
                        stop_all = True
                        break
                    except (HHAPIError, ValueError) as exc:
                        logging.warning("Вакансия %s пропущена: %s", vacancy_id, exc)

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
                "[yellow]Поиск остановлен: HH API сейчас требует авторизацию приложения для доступа к вакансиям.[/yellow]"
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
                    "[yellow]Search stopped due to HH API rate limit (429). Partial results were saved.[/yellow]"
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
            f"{profile_name}: {query} / {area}: {counters['loaded_count']} загружено"
        )

    print_run_summary(
        run_started, search_config, client, profiles_processed, run_counters
    )
    return exit_code


def _score_and_store(
    storage,
    vacancy: Vacancy,
    rules: dict[str, Any] | None,
    unit: dict[str, Any],
) -> None:
    """Score vacancy using the unit's preset (if any) or legacy rules."""
    preset = unit.get("preset")
    mode = unit.get("mode", "legacy")
    if preset and mode in ("preset", "adhoc"):
        storage.upsert_score(score_by_preset(vacancy, preset))
    elif rules:
        storage.upsert_score(score_vacancy(vacancy, rules))
