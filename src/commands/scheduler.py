from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def command_scheduler_print_windows_task(_: argparse.Namespace) -> int:
    cwd = Path.cwd()
    script = cwd / "scripts" / "daily_run.ps1"
    if not script.exists():
        console.print("[yellow]scripts/daily_run.ps1 not found.[/yellow]")

    console.print("\n[bold]Windows Task Scheduler command:[/bold]\n")
    console.print(
        f'schtasks /Create /SC DAILY /TN "CareerSignalHH Daily" '
        f'/TR "powershell.exe -ExecutionPolicy Bypass -File {script}" '
        f"/ST 09:30"
    )
    console.print("\n[dim]Copy and run this in Administrator PowerShell.[/dim]")
    console.print("[dim]Requires: .venv activated, .env configured with HH_APP_ACCESS_TOKEN.[/dim]")
    console.print("[dim]Deep mode is NOT used. Smoke or normal only.[/dim]")
    return 0


def command_scheduler_status(_: argparse.Namespace) -> int:
    table = Table(title="Scheduler Status")
    table.add_column("Check")
    table.add_column("Status")

    # Scripts
    for script in ["scripts/daily_run.ps1", "scripts/daily_run.sh"]:
        exists = Path(script).exists()
        table.add_row(script, "[green]exists[/green]" if exists else "[yellow]missing[/yellow]")

    # Logs
    log_dir = Path("logs")
    has_logs = log_dir.exists() and any(log_dir.iterdir())
    table.add_row("Logs dir", f"[green]{'has logs' if has_logs else 'empty/missing'}[/green]")

    if has_logs:
        latest = max(log_dir.glob("daily_*.log"), key=lambda p: p.stat().st_mtime, default=None)
        if latest:
            mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
            table.add_row("Latest log", f"{latest.name} ({mtime.strftime('%Y-%m-%d %H:%M')})")

    # Cockpit
    cockpit = Path("exports/cockpit.html")
    table.add_row(
        "Cockpit", "[green]exists[/green]" if cockpit.exists() else "[dim]not generated yet[/dim]"
    )

    # DB backup
    backups = (
        sorted(
            Path("backups").glob("vacancies_*.sqlite"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if Path("backups").exists()
        else []
    )
    table.add_row("Latest backup", backups[0].name if backups else "[dim]none[/dim]")

    console.print(table)

    console.print("\n[bold]Suggested next step:[/bold]")
    console.print("  1. Run manually for 3-5 days to verify.")
    console.print("  2. Then create Task Scheduler manually:")
    console.print("     python -m src.main scheduler print-windows-task")
    console.print("  3. Keep deep mode manual only.")
    return 0
