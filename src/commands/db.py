from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ..storage import Storage

console = Console()


def _get_db_path() -> str:
    load_dotenv()
    return os.getenv("DB_PATH", "data/vacancies.sqlite")


def command_db_info(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    path = Path(db_path)
    exists = path.is_file()
    size_mb = path.stat().st_size / (1024 * 1024) if exists else 0

    table = Table(title="Database Info")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("DB path", str(path.resolve()))
    table.add_row("Exists", "[green]yes[/green]" if exists else "[red]no[/red]")
    table.add_row("Size", f"{size_mb:.2f} MB" if exists else "-")

    if exists:
        storage = Storage(db_path)
        with storage.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
            reviews = conn.execute("SELECT COUNT(*) FROM vacancy_reviews").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
            samples = conn.execute(
                "SELECT COUNT(*) FROM vacancies WHERE id LIKE 'sample-%'"
            ).fetchone()[0]
            latest_vacancy = conn.execute("SELECT MAX(first_seen_at) FROM vacancies").fetchone()[0]
            latest_run = conn.execute("SELECT MAX(started_at) FROM search_runs").fetchone()[0]

        table.add_row("Total vacancies", str(total))
        table.add_row("Total reviews", str(reviews))
        table.add_row("Total search runs", str(runs))
        table.add_row("Sample vacancies (sample-* ids)", str(samples))
        table.add_row("Latest first_seen_at", latest_vacancy or "-")
        table.add_row("Latest search run", latest_run or "-")

    console.print(table)
    return 0


def command_db_purge_samples(args: argparse.Namespace) -> int:
    db_path = _get_db_path()
    path = Path(db_path)
    if not path.is_file():
        console.print(f"[red]База {db_path} не найдена.[/red]")
        return 1

    storage = Storage(db_path)
    with storage.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM vacancies WHERE id LIKE 'sample-%'").fetchone()[
            0
        ]

    if count == 0:
        console.print("[green]Sample-вакансий не найдено.[/green]")
        return 0

    if not args.yes:
        console.print(
            f"[yellow]Будет удалено {count} sample-вакансий "
            f"и связанные scores/reviews из {db_path}.[/yellow]"
        )
        try:
            if not Confirm.ask("Продолжить?", default=False):
                console.print("[yellow]Отменено.[/yellow]")
                return 0
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Отменено.[/yellow]")
            return 0

    with storage.connect() as conn:
        conn.execute("DELETE FROM scores WHERE vacancy_id LIKE 'sample-%'")
        conn.execute("DELETE FROM vacancy_reviews WHERE vacancy_id LIKE 'sample-%'")
        conn.execute("DELETE FROM vacancies WHERE id LIKE 'sample-%'")
        conn.commit()

    console.print(f"[green]Удалено {count} sample-вакансий и связанные записи.[/green]")
    return 0


def command_db_backup(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    src = Path(db_path)
    if not src.is_file():
        console.print(f"[red]База {db_path} не найдена — нечего бэкапить.[/red]")
        return 1

    backups_dir = Path("backups")
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backups_dir / f"vacancies_{timestamp}.sqlite"
    shutil.copy2(src, dst)

    size_mb = dst.stat().st_size / (1024 * 1024)
    console.print(f"[green]Бэкап создан: {dst} ({size_mb:.2f} MB)[/green]")
    return 0


def command_db_migrate(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    # Use a raw connection — Storage.__init__ also calls apply_migrations
    # internally, which would make this command a no-op.
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        from ..db_migrations import apply_migrations, get_expected_schema_version

        result = apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()

    # Render results table
    table = Table(title="DB Migrations")
    table.add_column("Version", justify="right")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Error")

    status_style = {
        "applied": "[green]applied[/green]",
        "skipped": "[dim]skipped[/dim]",
        "failed": "[red]failed[/red]",
    }

    for d in result["details"]:
        table.add_row(
            str(d["version"]),
            d["name"],
            status_style.get(d["status"], d["status"]),
            d["error"] or "",
        )

    console.print(table)
    console.print(
        f"applied={result['applied']}  skipped={result['skipped']}  failed={result['failed']}  "
        f"target version={get_expected_schema_version()}"
    )

    return 0 if result["failed"] == 0 else 1


def command_db_integrity(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    storage = Storage(db_path)
    with storage.connect() as conn:
        from ..db_migrations import check_integrity_extended, count_orphans

        ext = check_integrity_extended(conn)
        stats = count_orphans(conn)

    # Build table
    table = Table(title="Database Integrity")
    table.add_column("Check")
    table.add_column("Status")

    # PRAGMA integrity_check
    table.add_row(
        "PRAGMA integrity_check",
        "[green]OK[/green]" if ext["pragma_integrity_ok"] else "[red]FAIL[/red]",
    )

    # schema_migrations table
    table.add_row(
        "schema_migrations table",
        "[green]exists[/green]" if ext["schema_migrations_exists"] else "[red]missing[/red]",
    )

    # Schema version
    ver_current = ext["current_schema_version"]
    ver_expected = ext["expected_schema_version"]
    ver_ok = ver_current >= ver_expected
    table.add_row(
        f"Schema version (current={ver_current}, expected={ver_expected})",
        "[green]OK[/green]" if ver_ok else "[yellow]behind[/yellow]",
    )

    # score_details work_format_flags_json
    table.add_row(
        "score_details.work_format_flags_json",
        "[green]exists[/green]" if ext["score_details_has_wf_flags"] else "[red]missing[/red]",
    )

    # Required indexes
    if ext["missing_indexes"]:
        table.add_row(
            "Required indexes",
            f"[red]missing: {', '.join(ext['missing_indexes'])}[/red]",
        )
    else:
        table.add_row("Required indexes", "[green]all present[/green]")

    # VACUUM estimate
    freelist_mb = ext["freelist_bytes"] / (1024 * 1024) if ext["freelist_bytes"] else 0
    if ext["vacuum_recommended"]:
        table.add_row(
            "VACUUM recommended",
            f"[yellow]yes ({ext['freelist_pages']} pages, ~{freelist_mb:.1f} MB)[/yellow]",
        )
    else:
        table.add_row(
            "VACUUM recommended",
            f"[green]no ({ext['freelist_pages']} pages)[/green]",
        )

    # Orphan stats
    for label, key in [
        ("Orphan scores", "orphan_scores"),
        ("Orphan score_details", "orphan_score_details"),
        ("Orphan reviews", "orphan_reviews"),
        ("Sample-* vacancies", "sample_count"),
        ("Duplicate URLs", "duplicate_urls"),
        ("Missing scores", "missing_scores"),
        ("Missing score_details", "missing_score_details"),
        ("Missing descriptions", "missing_descriptions"),
    ]:
        val = stats[key]
        status = "[green]0[/green]" if val == 0 else f"[yellow]{val}[/yellow]"
        table.add_row(label, status)

    console.print(table)

    # Determine exit code
    issues = 0
    if not ext["pragma_integrity_ok"]:
        issues += 1
    if not ext["schema_migrations_exists"]:
        issues += 1
    if not ext["score_details_has_wf_flags"]:
        issues += 1
    if ext["missing_indexes"]:
        issues += 1

    return 0 if issues == 0 else 1


def command_db_vacuum(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    # Backup first
    command_db_backup(_)
    storage = Storage(db_path)
    with storage.connect() as conn:
        before = Path(db_path).stat().st_size / (1024 * 1024)
        conn.execute("VACUUM")
        conn.commit()
        after = Path(db_path).stat().st_size / (1024 * 1024)
    console.print(f"[green]VACUUM complete. {before:.1f} MB → {after:.1f} MB[/green]")
    return 0


def command_db_optimize(_: argparse.Namespace) -> int:
    db_path = _get_db_path()
    storage = Storage(db_path)
    with storage.connect() as conn:
        conn.execute("PRAGMA optimize")
        conn.execute("ANALYZE")
        conn.commit()
    console.print("[green]PRAGMA optimize + ANALYZE complete.[/green]")
    return 0


def command_db_cleanup_orphans(args: argparse.Namespace) -> int:
    db_path = _get_db_path()
    storage = Storage(db_path)
    with storage.connect() as conn:
        from ..db_migrations import cleanup_orphans, count_orphans

        stats = count_orphans(conn)
        total_orphans = (
            stats["orphan_scores"] + stats["orphan_score_details"] + stats["orphan_reviews"]
        )
        if total_orphans == 0:
            console.print("[green]No orphans found.[/green]")
            return 0
        if not args.yes:
            console.print(f"[yellow]Found {total_orphans} orphan records. Continue?[/yellow]")
            try:
                if not Confirm.ask("Continue?", default=False):
                    return 0
            except (EOFError, KeyboardInterrupt):
                return 0
        result = cleanup_orphans(conn)
    for k, v in result.items():
        if v:
            console.print(f"  {k}: {v}")
    console.print(f"[green]Cleaned up {sum(result.values())} orphan records.[/green]")
    return 0
