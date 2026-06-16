from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone
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
            latest_vacancy = conn.execute(
                "SELECT MAX(first_seen_at) FROM vacancies"
            ).fetchone()[0]
            latest_run = conn.execute(
                "SELECT MAX(started_at) FROM search_runs"
            ).fetchone()[0]

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
        count = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE id LIKE 'sample-%'"
        ).fetchone()[0]

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
