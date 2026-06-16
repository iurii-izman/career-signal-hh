from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.table import Table

from ..hh_client import HHClient

console = Console()


def print_run_estimate(
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

    budget_max = search_config["max_requests_per_run"]
    within_budget = est_search <= budget_max
    est_label = (
        f"[green]{est_search}[/green] (within budget)"
        if within_budget
        else f"[yellow]{est_search}[/yellow] [red]EXCEEDS budget of {budget_max}![/red]"
    )
    table.add_row("Est. search requests", est_label)
    table.add_row("Max requests per run (total budget)", str(budget_max))
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


def print_run_summary(
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
    table.add_row("Attempted requests", str(client.stats_attempted_requests))
    table.add_row(
        "Successful requests", str(client.budget["total"] if client.budget else 0)
    )
    table.add_row("Search requests", str(client.stats_search_requests))
    table.add_row("Detail requests", str(client.stats_detail_requests))
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
