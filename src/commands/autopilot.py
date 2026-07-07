from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import _services
from ..hh_client import HHClient

console = Console()


def _check_auth_light() -> tuple[bool, str]:
    """Light auth check: verify mode/token, optionally test API."""
    client = HHClient()
    ok = True
    msgs: list[str] = []
    msgs.append(f"Auth mode: {client.auth_mode}")
    token_ok = client.active_token_present
    msgs.append(f"{client.active_token_env_name}: {'present' if token_ok else 'MISSING'}")
    if client.auth_mode in {"application_token", "user_oauth"} and not token_ok:
        msgs.append(
            f"WARNING: {client.auth_mode} mode but {client.active_token_env_name} is not set"
        )
        ok = False
    return ok, "\n".join(msgs)


def _doctor_ok() -> tuple[bool, list[str]]:
    """Run quick local checks without network."""
    errors: list[str] = []
    for path_str in ["config/search_presets.yaml", "config/search_profiles.yaml"]:
        if not Path(path_str).exists():
            errors.append(f"MISSING: {path_str}")
    # DB check: warn if missing, but don't fail — Storage creates it on demand
    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")
    if not Path(db_path).exists():
        errors.append(f"DB not found: {db_path} (will be created on first use)")
    return len(errors) == 0 or all("will be created" in e for e in errors), errors


def command_autopilot_daily(args: argparse.Namespace) -> int:
    mode = args.mode or "normal"
    if mode == "deep" and not args.allow_deep:
        console.print("[red]Refusing deep mode in autopilot. Use --allow-deep to override.[/red]")
        return 1
    if mode not in ("smoke", "normal"):
        console.print(f"[red]Invalid mode: {mode}. Use smoke or normal.[/red]")
        return 1

    # 1. Doctor
    doctor_ok, doctor_errors = _doctor_ok()
    if not doctor_ok:
        console.print("[red]Doctor check failed:[/red]")
        for e in doctor_errors:
            console.print(f"  - {e}")
        if not args.ignore_doctor_warnings:
            return 1
        console.print(
            "[yellow]Continuing despite doctor warnings (--ignore-doctor-warnings).[/yellow]"
        )

    # 2. Auth check
    if not args.skip_auth_check:
        auth_ok, auth_msg = _check_auth_light()
        console.print(auth_msg)
        if not auth_ok:
            console.print("[red]Auth check failed. Stopping.[/red]")
            return 1
    else:
        console.print("[dim]Auth check skipped.[/dim]")

    # 3. Backup
    if args.backup_first:
        from .db import command_db_backup

        console.print("[bold]Creating backup...[/bold]")
        try:
            command_db_backup(argparse.Namespace())
        except Exception as exc:
            console.print(f"[yellow]Backup warning: {exc}[/yellow]")

    # 4. Search
    search_ok = True
    if not args.skip_search:
        from .search import command_search

        console.print(f"[bold]Running search ({mode})...[/bold]")
        search_args = argparse.Namespace(
            mode=mode,
            max_pages=None,
            per_page=None,
            profile=None,
            preset=args.preset,
            adhoc=False,
            include=None,
            exclude=None,
            remote_only=None,
            dry_run=False,
            force_details=False,
            verbose=False,
            yes=args.yes,
        )
        try:
            rc = command_search(search_args)
            search_ok = rc == 0
        except Exception as exc:
            console.print(f"[red]Search failed: {exc}[/red]")
            search_ok = False
    else:
        console.print("[dim]Search skipped.[/dim]")

    # 5. Rescore
    if not args.skip_rescore:
        from .score import command_score_rescore

        console.print("[bold]Running rescore...[/bold]")
        rescore_args = argparse.Namespace(preset=args.preset, limit=None)
        try:
            command_score_rescore(rescore_args)
        except Exception as exc:
            console.print(f"[yellow]Rescore warning: {exc}[/yellow]")

    # 6. Export
    if not args.skip_export:
        from .export import command_export

        console.print("[bold]Running export...[/bold]")
        export_args = argparse.Namespace(min_score=0, profile=None, preset=None, days=None)
        try:
            command_export(export_args)
        except Exception as exc:
            console.print(f"[yellow]Export warning: {exc}[/yellow]")

    # 7. Queue
    if not args.skip_queue:
        from .review import command_review_queue

        console.print(f"[bold]Review queue (score≥{args.min_score}, new only)...[/bold]")
        queue_args = argparse.Namespace(
            decision="strong_match,queue",
            min_score=args.min_score,
            preset=args.preset,
            profile=None,
            status=None,
            limit=args.queue_limit,
            remote_only=False,
            with_salary=False,
            hide_risk=False,
            new_only=True,
        )
        try:
            command_review_queue(queue_args)
        except Exception as exc:
            console.print(f"[yellow]Queue warning: {exc}[/yellow]")

    # 8. Summary
    try:
        storage, _, _ = _services()
        stats = storage.stats()
        latest = storage.list_vacancies(limit=5)

        table = Table(title="Autopilot Daily Summary")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Mode", mode)
        table.add_row("Preset", args.preset or "all")
        table.add_row("Search", "OK" if search_ok else "FAILED/SKIPPED")
        table.add_row("Doctor", "OK" if doctor_ok else "WARNINGS")
        table.add_row("Export", "OK")
        table.add_row("Total vacancies", str(stats["total"]))
        table.add_row("New 24h", str(stats["new_24h"]))
        table.add_row("Avg score", f"{stats['avg_score']:.0f}")
        table.add_row("Remote", str(stats["remote"]))
        table.add_row("With salary", str(stats["with_salary"]))
        if latest:
            table.add_row(
                "Top vacancy",
                f"{latest[0].get('name', '?')} (score {latest[0].get('total_score', 0)})",
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[yellow]Summary warning: {exc}[/yellow]")

    return 0 if search_ok else 1


def command_autopilot_status(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    stats = storage.stats()

    table = Table(title="Autopilot Status")
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("DB path", os.getenv("DB_PATH", "data/vacancies.sqlite"))
    table.add_row("Total vacancies", str(stats["total"]))
    table.add_row("New 24h", str(stats["new_24h"]))
    table.add_row("Avg score", f"{stats['avg_score']:.0f}")

    # Queue counts
    try:
        queue_new = len(storage.list_queue(min_score=70, new_only=True, limit=1000))
        table.add_row("Pending queue (new, ≥70)", str(queue_new))
    except Exception:
        table.add_row("Pending queue", "N/A")

    # Applied/interview counts
    try:
        applied = len(storage.list_queue(min_score=0, status="applied", limit=1000))
        interview = len(storage.list_queue(min_score=0, status="interview", limit=1000))
        offer = len(storage.list_queue(min_score=0, status="offer", limit=1000))
        table.add_row("Applied", str(applied))
        table.add_row("Interview", str(interview))
        table.add_row("Offer", str(offer))
    except Exception:
        table.add_row("Review stats", "N/A")

    # Latest backup
    backups_dir = Path("backups")
    if backups_dir.exists():
        backups = sorted(backups_dir.glob("vacancies_*.sqlite"), reverse=True)
        if backups:
            table.add_row("Latest backup", str(backups[0].name))
        else:
            table.add_row("Latest backup", "none")
    else:
        table.add_row("Latest backup", "none")

    # Latest export
    export_html = Path("exports/vacancies_report.html")
    if export_html.exists():
        mtime = datetime.fromtimestamp(export_html.stat().st_mtime, tz=timezone.utc)
        table.add_row("Latest export", mtime.strftime("%Y-%m-%d %H:%M"))
    else:
        table.add_row("Latest export", "none")

    # Latest search run
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT started_at FROM search_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if row:
            table.add_row("Latest search run", (row[0] or "")[:19])
        else:
            table.add_row("Latest search run", "none")

    console.print(table)
    return 0
