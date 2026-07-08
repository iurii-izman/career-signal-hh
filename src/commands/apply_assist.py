from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from ..config import _services
from ..services.apply_assist_service import execute_apply_assist

console = Console()


def _print_gates(gates: list[dict[str, object]]) -> None:
    table = Table(title="Controlled Apply Assist Gates")
    table.add_column("Gate")
    table.add_column("Status")
    table.add_column("Detail")
    for gate in gates:
        ok = bool(gate.get("ok"))
        table.add_row(
            str(gate.get("name", "")),
            "[green]pass[/green]" if ok else "[red]block[/red]",
            str(gate.get("detail", "")),
        )
    console.print(table)


def command_apply_assist(args: argparse.Namespace) -> int:
    if bool(getattr(args, "open_browser", False)) and not bool(
        getattr(args, "approve", False)
    ):
        console.print(
            "[red]`--open-browser` requires explicit `--approve`.[/red]"
        )
        return 2

    storage, _, _ = _services()
    result = execute_apply_assist(
        storage,
        args.vacancy_id,
        approve=bool(getattr(args, "approve", False)),
        open_browser=bool(getattr(args, "open_browser", False)),
    )

    if result.get("error_type") == "not_found":
        console.print(f"[red]{result['message']}[/red]")
        return 1

    data = result.get("data") or {}
    vacancy = data.get("vacancy") or {}
    score = data.get("score") or {}

    console.print(
        f"[bold]{vacancy.get('employer_name', '?')} — {vacancy.get('name', '?')}[/bold]"
    )
    console.print(
        f"score={score.get('total_score', 0)} | confidence={score.get('confidence_score', 0)} | "
        f"noise={score.get('noise_score', 0)} | decision={score.get('decision') or '-'}"
    )
    _print_gates(data.get("gates", []))

    briefing = (data.get("artifacts") or {}).get("briefing") or {}
    apply_pack = (data.get("artifacts") or {}).get("apply_pack") or {}
    console.print("\n[cyan]Artifacts[/cyan]")
    console.print(f"Briefing HTML: {briefing.get('html') or '-'}")
    console.print(f"Apply pack HTML: {apply_pack.get('html') or '-'}")
    console.print(f"Vacancy URL: {vacancy.get('alternate_url') or '-'}")

    if not result["ok"]:
        console.print(f"\n[red]{result['message']}[/red]")
        return 2

    if not getattr(args, "approve", False):
        console.print(
            "\n[yellow]Assist is ready but not approved.[/yellow] "
            "Re-run with `--approve` for operator handoff."
        )
        return 0

    console.print("\n[green]Operator handoff prepared.[/green]")
    console.print("Checklist:")
    console.print(f"  1. Review briefing/apply-pack artifacts for {args.vacancy_id}")
    console.print("  2. Verify the HH form and vacancy details manually")
    console.print("  3. Submit the application manually")
    console.print(f"  4. Run: {data.get('next_commands', {}).get('mark_applied', '-')}")
    if getattr(args, "open_browser", False):
        console.print("[dim]Browser handoff opened explicitly via --open-browser.[/dim]")
    return 0
