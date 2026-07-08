"""Wizard — guided workflow for CareerSignal HH.

Usage:
  python -m src.main wizard              # interactive menu
  python -m src.main wizard first-run     # guided setup
  python -m src.main wizard daily         # daily job search
  python -m src.main wizard improve       # quality improvement
  python -m src.main wizard apply         # briefing + apply-pack workflow

All subcommands support --plan to print the plan without executing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

console = Console()

# ── Shared helpers ──────────────────────────────────────────────────────────


def _run_command(args: list[str], check: bool = False) -> int:
    """Run a subprocess command via 'python -m src.main ...'. Returns exit code."""
    cmd = [sys.executable, "-m", "src.main"] + args
    try:
        result = subprocess.run(cmd, capture_output=False, timeout=120)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        console.print(f"[yellow]Timeout: {' '.join(args)}[/yellow]")
        rc = 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        rc = 130
    if check and rc != 0:
        console.print(f"[red]Command failed (exit {rc}): {' '.join(cmd)}[/red]")
    return rc


def _run_readonly(args: list[str]) -> int:
    """Run a command that must succeed. Print result badge."""
    label = " ".join(args)
    rc = _run_command(args)
    if rc == 0:
        console.print(f"  [green]✓[/green] {label}")
    else:
        console.print(f"  [red]✗[/red] {label} (exit {rc})")
    return rc


def _run_with_confirm(args: list[str], description: str, force: bool = False) -> int:
    """Run a command, asking for confirmation first."""
    if force:
        console.print(f"\n[yellow]→ {description}[/yellow]")
        return _run_command(args)
    if Confirm.ask(f"\nRun '{description}'?", default=True):
        return _run_command(args)
    console.print(f"  [dim]Skipped: {description}[/dim]")
    return 0


def _section(title: str) -> None:
    console.print(f"\n[bold cyan]{title}[/bold cyan]")


def _plan_step(command: str, why: str, safe: bool = True) -> None:
    """Print a plan step."""
    tag = "[green]SAFE[/green]" if safe else "[yellow]CONFIRM[/yellow]"
    console.print(f"  {tag}  [bold]{command}[/bold]")
    console.print(f"        {why}")


# ── Wizard menu (default) ────────────────────────────────────────────────────


def _show_menu() -> int:
    """Show interactive menu, return chosen option (1-7)."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]CareerSignal HH Wizard[/bold cyan]\n"
            "Guided workflow — follow the steps below.",
            border_style="cyan",
        )
    )
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("num", style="bold cyan")
    table.add_column("label")
    options = [
        (1, "First run setup — configure environment"),
        (2, "Daily job search — search, score, export"),
        (3, "Review best vacancies — queue + decisions"),
        (4, "Generate apply packs — cover letters"),
        (5, "Improve presets — calibrate quality"),
        (6, "Maintenance / health — check system"),
        (7, "Exit"),
    ]
    for num, label in options:
        table.add_row(str(num), label)
    console.print(table)

    try:
        choice = IntPrompt.ask("Choose option", choices=["1", "2", "3", "4", "5", "6", "7"])
        return int(choice)
    except (EOFError, KeyboardInterrupt):
        return 7


def command_wizard(args: argparse.Namespace) -> int:
    """Interactive menu wizard."""
    if getattr(args, "plan", False):
        console.print("[bold cyan]Wizard plan (interactive menu)[/bold cyan]")
        console.print("  Run [bold]wizard[/bold] to see the interactive menu.")
        console.print("  Subcommands: first-run, daily, improve, apply")
        console.print("  All support --plan for non-interactive preview.")
        return 0

    while True:
        choice = _show_menu()

        if choice == 1:
            command_wizard_first_run(argparse.Namespace(plan=False))
        elif choice == 2:
            command_wizard_daily(argparse.Namespace(plan=False, yes=False, mode="normal"))
        elif choice == 3:
            _run_command(["review", "queue", "--min-score", "70", "--limit", "15"])
        elif choice == 4:
            command_wizard_apply(argparse.Namespace(plan=False))
        elif choice == 5:
            command_wizard_improve(argparse.Namespace(plan=False, yes=False))
        elif choice == 6:
            _run_command(["health"])
        elif choice == 7:
            console.print("[dim]Goodbye![/dim]")
            return 0
        else:
            console.print("[red]Invalid choice.[/red]")

        if Confirm.ask("\nReturn to menu?", default=True):
            continue
        return 0


# ── First run ────────────────────────────────────────────────────────────────


def command_wizard_first_run(args: argparse.Namespace) -> int:
    """Guided first-run setup."""
    plan_mode = getattr(args, "plan", False)

    if plan_mode:
        console.print("\n[bold cyan]First Run — Setup Checklist[/bold cyan]\n")
        _plan_step(
            "check .env exists",
            "Verify environment configuration file is present",
        )
        _plan_step(
            "check HH_AUTH_MODE + token",
            "application_token mode requires HH_APP_ACCESS_TOKEN",
        )
        _plan_step(
            "presets validate",
            "Ensure search presets YAML is valid",
        )
        _plan_step(
            "db migrate",
            "Apply any pending schema migrations",
        )
        _plan_step(
            "db integrity",
            "Verify database structure is intact",
        )
        _plan_step(
            "sample-export (optional)",
            "Generate sample data for testing without API calls",
        )
        _plan_step(
            "search --dry-run --mode smoke",
            "Preview first search without making API calls",
            safe=True,
        )
        return 0

    _section("First Run Setup")
    console.print()

    load_dotenv()

    # 1. Check .env
    env_path = Path(".env")
    if env_path.is_file():
        console.print("  [green]✓[/green] .env exists")
    else:
        console.print("  [red]✗[/red] .env not found — copy .env.example to .env")
        console.print("    [dim]cp .env.example .env[/dim]")
        return 1

    # 2. Check auth
    from ..hh_client import HHClient

    client = HHClient()
    auth_mode = client.auth_mode
    console.print(f"  [green]✓[/green] HH_AUTH_MODE = {auth_mode}")
    if auth_mode in {"application_token", "user_oauth"}:
        if client.active_token_present:
            console.print("  [green]✓[/green] Token is set")
        else:
            console.print(
                "  [red]✗[/red] "
                f"{auth_mode} mode but {client.active_token_env_name} is empty"
            )
            return 1
    else:
        console.print("  [dim]  Token not required for current mode[/dim]")

    # 3. Presets validate
    _run_readonly(["presets", "validate"])

    # 4. DB migrate
    _run_readonly(["db", "migrate"])

    # 5. DB integrity
    _run_readonly(["db", "integrity"])

    # 6. Optional sample-export
    if Confirm.ask("\nGenerate sample data for testing?", default=True):
        _run_command(["sample-export"])

    # 7. Dry-run search
    if Confirm.ask("\nRun a dry-run smoke search to verify setup?", default=True):
        _run_command(["search", "--dry-run", "--mode", "smoke"])

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
            "Next commands:\n"
            "  python -m src.main wizard daily     → daily job search\n"
            "  python -m src.main wizard improve   → improve presets\n"
            "  python -m src.main health            → system check",
            border_style="green",
        )
    )
    return 0


# ── Daily ────────────────────────────────────────────────────────────────────


def command_wizard_daily(args: argparse.Namespace) -> int:
    """Guided daily workflow: health → backup → search → cockpit → review."""
    plan_mode = getattr(args, "plan", False)
    yes_flag = getattr(args, "yes", False)

    if plan_mode:
        console.print("\n[bold cyan]Daily Workflow Plan[/bold cyan]\n")
        _plan_step(
            "health",
            "Quick system check: DB integrity, schema version, backups age",
        )
        _plan_step(
            "db backup",
            "Create backup before making changes",
            safe=False,
        )
        _plan_step(
            "autopilot daily --backup-first --mode normal",
            "Search and score new vacancies (normal mode, not deep)",
            safe=False,
        )
        _plan_step(
            "cockpit export",
            "Generate cockpit dashboard HTML",
        )
        _plan_step(
            "review next-best",
            "Show top new vacancies to review",
        )
        console.print("\n[dim]Run with --yes to skip confirmations.[/dim]")
        return 0

    _section("Daily Job Search")

    # 1. Health
    console.print("\n[bold]Step 1: Health check[/bold]")
    if _run_command(["health"]) != 0:
        if not Confirm.ask("Health check had warnings. Continue?", default=True):
            return 0

    # 2. Backup
    console.print("\n[bold]Step 2: Database backup[/bold]")
    _run_with_confirm(
        ["db", "backup"],
        "db backup (create backup before search)",
        force=yes_flag,
    )

    # 3. Search (normal only, never deep)
    console.print("\n[bold]Step 3: Search and score[/bold]")
    mode = getattr(args, "mode", None) or "normal"
    if mode == "deep":
        console.print("[red]Deep mode not allowed in wizard.[/red]")
        mode = "normal"
    _run_with_confirm(
        ["autopilot", "daily", "--backup-first", "--mode", mode],
        f"autopilot daily --mode {mode} (search + score + export)",
        force=yes_flag,
    )

    # 4. Cockpit
    console.print("\n[bold]Step 4: Cockpit[/bold]")
    _run_command(["cockpit", "export"])
    if Confirm.ask("Open cockpit in browser?", default=False):
        _run_command(["cockpit", "open"])

    # 5. Review next-best
    console.print("\n[bold]Step 5: Review top vacancies[/bold]")
    _run_command(["review", "next-best"])

    console.print()
    console.print("[bold green]Daily workflow complete![/bold green]")
    console.print("[dim]Next: wizard apply  |  wizard improve  |  wizard maintenance[/dim]")
    return 0


# ── Improve ──────────────────────────────────────────────────────────────────


def command_wizard_improve(args: argparse.Namespace) -> int:
    """Guided quality improvement: cluster → report → calibrate → suggest."""
    plan_mode = getattr(args, "plan", False)

    if plan_mode:
        console.print("\n[bold cyan]Improve Workflow Plan[/bold cyan]\n")
        _plan_step(
            "quality cluster",
            "Group duplicate vacancies by similarity",
        )
        _plan_step(
            "quality report",
            "Show data quality metrics: duplicates, missing data",
        )
        _plan_step(
            "calibrate analyze",
            "Analyze preset performance: which keywords work best",
        )
        _plan_step(
            "calibrate suggest",
            "Generate suggestions for preset improvements",
        )
        _plan_step(
            "calibrate export",
            "Export calibration report as HTML",
        )
        _plan_step(
            "presets validate",
            "Verify all presets are structurally valid",
        )
        console.print("\n[dim]No changes are applied without confirmation.[/dim]")
        return 0

    _section("Improve Presets & Quality")

    # 1. Quality cluster
    if Confirm.ask("\nRun quality duplicate clustering?", default=True):
        _run_command(["quality", "cluster"])

    # 2. Quality report
    if Confirm.ask("Show quality report?", default=True):
        _run_command(["quality", "report"])

    # 3. Calibrate analyze
    if Confirm.ask("Analyze preset performance?", default=True):
        _run_command(["calibrate", "analyze"])

    # 4. Calibrate suggest
    if Confirm.ask("Generate calibration suggestions?", default=True):
        _run_command(["calibrate", "suggest"])

    # 5. Calibrate export
    if Confirm.ask("Export calibration report?", default=True):
        _run_command(["calibrate", "export"])

    # 6. Presets validate
    _run_command(["presets", "validate"])

    console.print()
    console.print("[bold green]Quality improvement complete![/bold green]")
    console.print("[dim]Review suggestions: python -m src.main calibrate suggest[/dim]")
    console.print(
        "[dim]Apply suggestions: python -m src.main calibrate apply --suggestion-id N[/dim]"
    )
    return 0


# ── Apply ────────────────────────────────────────────────────────────────────


def command_wizard_apply(args: argparse.Namespace) -> int:
    """Guided briefing/apply-pack workflow: queue → choose → explain → briefing → pack."""
    plan_mode = getattr(args, "plan", False)

    if plan_mode:
        console.print("\n[bold cyan]Apply Workflow Plan[/bold cyan]\n")
        _plan_step(
            "review queue --min-score 70 --decision strong_match",
            "Show top-scoring vacancies ready for application",
        )
        _plan_step(
            "Pick a vacancy ID from the queue",
            "Choose the vacancy you want to apply to",
        )
        _plan_step(
            "score explain VACANCY_ID",
            "See detailed scoring breakdown for this vacancy",
        )
        _plan_step(
            "briefing VACANCY_ID --save-review",
            "Generate 7-block briefing and save it to briefing storage",
            safe=False,
        )
        _plan_step(
            "apply-pack VACANCY_ID --save-review",
            "Generate cover letter and save draft to review",
            safe=False,
        )
        _plan_step(
            "review set VACANCY_ID --status interesting",
            "Mark vacancy as interesting after generating pack",
            safe=False,
        )
        console.print("\n[dim]Wizard never sends applications to HH.[/dim]")
        return 0

    _section("Generate Apply Packs")

    # 1. Show strong matches
    console.print("\n[bold]Strong matches:[/bold]")
    _run_command(
        ["review", "queue", "--min-score", "70", "--decision", "strong_match", "--limit", "10"]
    )

    # 2. Pick vacancy ID
    try:
        vacancy_id = Prompt.ask(
            "\nEnter vacancy ID to generate apply pack",
            default="",
        )
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 0

    if not vacancy_id.strip():
        console.print("[yellow]No vacancy ID entered.[/yellow]")
        return 0

    # 3. Score explain
    if Confirm.ask(f"Show scoring breakdown for {vacancy_id}?", default=True):
        _run_command(["score", "explain", vacancy_id])

    # 4. Generate briefing
    if Confirm.ask(f"Generate briefing for {vacancy_id}?", default=True):
        _run_command(["briefing", vacancy_id, "--save-review"])

    # 5. Generate apply-pack
    if Confirm.ask(f"Generate apply pack for {vacancy_id}?", default=True):
        _run_command(["apply-pack", vacancy_id, "--save-review"])

    # 6. Mark as interesting
    if Confirm.ask(f"Mark {vacancy_id} as 'interesting' in reviews?", default=True):
        _run_command(["review", "set", vacancy_id, "--status", "interesting"])

    console.print()
    console.print("[bold green]Apply pack ready![/bold green]")
    console.print(f"[dim]Review draft: python -m src.main review draft {vacancy_id}[/dim]")
    console.print(
        "[dim]Mark as applied: python -m src.main review apply {vacancy_id} --date today[/dim]"
    )
    return 0
