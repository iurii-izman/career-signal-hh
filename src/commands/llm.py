"""LLM prompt commands — generate prompt files for manual use.

Usage:
  python -m src.main llm status
  python -m src.main llm prompt apply-pack ID
  python -m src.main llm prompt score-review ID
  python -m src.main llm prompt preset-improve NAME
  python -m src.main llm export-prompts --top 5
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ..llm_prompts import (
    PROMPTS_DIR,
    generate_apply_pack_prompt,
    generate_preset_improve_prompt,
    generate_score_review_prompt,
    load_llm_config,
    preview_fields,
)

console = Console()


# ── status ───────────────────────────────────────────────────────────────────


def command_llm_status(_: argparse.Namespace) -> int:
    """Show LLM configuration status."""
    config = load_llm_config()

    table = Table(title="LLM Configuration")
    table.add_column("Setting")
    table.add_column("Value")

    table.add_row("Enabled", "[green]yes[/green]" if config.get("enabled") else "[dim]no[/dim]")
    table.add_row("Provider", config.get("provider", "manual"))
    table.add_row("Privacy mode", config.get("privacy_mode", "strict"))
    table.add_row(
        "Include descriptions", "yes" if config.get("include_description", True) else "no"
    )
    table.add_row("Max description chars", str(config.get("max_description_chars", 3000)))

    console.print(table)

    # Show what fields would be included
    console.print("\n[bold]Fields included in prompts:[/bold]")
    for f in preview_fields(config):
        console.print(f"  • {f}")

    console.print("\n[dim]Prompts are saved to exports/llm_prompts/ for manual copy/paste.[/dim]")
    console.print("[dim]No API keys or .env values are ever included.[/dim]")
    return 0


# ── prompt apply-pack ────────────────────────────────────────────────────────


def command_llm_prompt_apply_pack(args: argparse.Namespace) -> int:
    """Generate cover letter improvement prompt."""
    config = load_llm_config()
    yes = getattr(args, "yes", False)

    # Privacy preview
    console.print("[bold]The following fields will be included in the prompt:[/bold]")
    for f in preview_fields(config):
        console.print(f"  • {f}")

    if not yes:
        try:
            if not Confirm.ask("\nGenerate prompt file?", default=True):
                console.print("[yellow]Cancelled.[/yellow]")
                return 0
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 0

    prompt = generate_apply_pack_prompt(args.vacancy_id)
    if "not found" in prompt:
        console.print(f"[red]{prompt}[/red]")
        return 1

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"apply_pack_{args.vacancy_id}.md"
    path.write_text(prompt, encoding="utf-8")

    # Safety: verify no token/env in output
    _safety_check(prompt, str(path))

    console.print(f"[green]✓[/green] {path}")
    console.print("[dim]Copy the content of this file and paste into your preferred LLM.[/dim]")
    return 0


# ── prompt score-review ──────────────────────────────────────────────────────


def command_llm_prompt_score_review(args: argparse.Namespace) -> int:
    """Generate score review prompt."""
    yes = getattr(args, "yes", False)

    if not yes:
        try:
            if not Confirm.ask("Generate score review prompt?", default=True):
                console.print("[yellow]Cancelled.[/yellow]")
                return 0
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 0

    prompt = generate_score_review_prompt(args.vacancy_id)
    if "not found" in prompt:
        console.print(f"[red]{prompt}[/red]")
        return 1

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"score_review_{args.vacancy_id}.md"
    path.write_text(prompt, encoding="utf-8")

    _safety_check(prompt, str(path))

    console.print(f"[green]✓[/green] {path}")
    return 0


# ── prompt preset-improve ────────────────────────────────────────────────────


def command_llm_prompt_preset_improve(args: argparse.Namespace) -> int:
    """Generate preset improvement prompt."""
    yes = getattr(args, "yes", False)

    if not yes:
        try:
            if not Confirm.ask(
                f"Generate preset improvement prompt for '{args.preset_name}'?", default=True
            ):
                console.print("[yellow]Cancelled.[/yellow]")
                return 0
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 0

    prompt = generate_preset_improve_prompt(args.preset_name)
    if "not found" in prompt:
        console.print(f"[red]{prompt}[/red]")
        return 1

    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"preset_improve_{args.preset_name}.md"
    path.write_text(prompt, encoding="utf-8")

    _safety_check(prompt, str(path))

    console.print(f"[green]✓[/green] {path}")
    return 0


# ── export-prompts ───────────────────────────────────────────────────────────


def command_llm_export_prompts(args: argparse.Namespace) -> int:
    """Batch export prompts for top vacancies."""
    import os

    from dotenv import load_dotenv

    from ..storage import Storage

    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    top_n = args.top or 5

    with storage.connect() as conn:
        rows = conn.execute(
            """SELECT v.id, v.name, sd.total_score, sd.decision
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id=v.id
               WHERE sd.decision='strong_match'
               ORDER BY sd.total_score DESC LIMIT ?""",
            (top_n,),
        ).fetchall()

    if not rows:
        console.print("[yellow]No strong match vacancies found.[/yellow]")
        return 0

    console.print(f"Exporting prompts for top {len(rows)} vacancies...")
    for r in rows:
        vid = r["id"]
        prompt = generate_apply_pack_prompt(vid)
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        path = PROMPTS_DIR / f"apply_pack_{vid}.md"
        path.write_text(prompt, encoding="utf-8")
        console.print(f"  [green]✓[/green] {vid} — {r['name'][:50]}")

    console.print(f"\n[green]Exported {len(rows)} prompts to {PROMPTS_DIR}[/green]")
    return 0


# ── Safety check ─────────────────────────────────────────────────────────────


def _safety_check(prompt: str, path: str) -> None:
    """Verify prompt doesn't contain sensitive data."""
    import os

    # Never include token
    token = os.getenv("HH_APP_ACCESS_TOKEN", "")
    if token and token in prompt:
        console.print(f"[red]SAFETY VIOLATION: Token found in {path}![/red]")
    # Never include .env path
    if ".env" in prompt.lower() and "HH_AUTH_MODE" not in prompt:
        console.print(f"[yellow]Warning: possible .env reference in {path}[/yellow]")
