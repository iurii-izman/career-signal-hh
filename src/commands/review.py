from __future__ import annotations

import argparse
from datetime import date

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..storage import REVIEW_STATUSES, Storage

console = Console()


def _review_storage() -> Storage:
    import os

    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def _normalize_review_date(value: str) -> str:
    if value.strip().lower() == "today":
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"Некорректная дата {value!r}. Используйте today или YYYY-MM-DD.") from exc


def command_review_list(args: argparse.Namespace) -> int:
    storage = _review_storage()
    try:
        profile = args.preset or args.profile
        rows = storage.list_reviewed_vacancies(
            status=args.status,
            min_score=args.min_score,
            limit=args.limit,
            profile=profile,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    table = Table(title="Manual vacancy review")
    for column in [
        "Status",
        "Score",
        "Profile",
        "Employer",
        "Title",
        "Area",
        "Updated",
        "URL",
    ]:
        table.add_column(column)
    for row in rows:
        table.add_row(
            row.get("review_status") or "new",
            str(row.get("total_score") or 0),
            row.get("best_profile") or "",
            row.get("employer_name") or "",
            row.get("name") or "",
            row.get("area_name") or "",
            (row.get("review_updated_at") or "")[:19],
            row.get("alternate_url") or "",
        )
    console.print(table)
    return 0


def command_review_set(args: argparse.Namespace) -> int:
    try:
        review = _review_storage().set_review_status(args.vacancy_id, args.status)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(f"[green]{args.vacancy_id}: status={review['status']}[/green]")
    return 0


def command_review_note(args: argparse.Namespace) -> int:
    try:
        _review_storage().set_review_note(args.vacancy_id, args.note)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(f"[green]{args.vacancy_id}: заметка сохранена[/green]")
    return 0


def command_review_apply(args: argparse.Namespace) -> int:
    try:
        applied_at = _normalize_review_date(args.date)
        _review_storage().mark_applied(args.vacancy_id, applied_at)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(f"[green]{args.vacancy_id}: status=applied, applied_at={applied_at}[/green]")
    return 0


def command_review_next(args: argparse.Namespace) -> int:
    try:
        next_action_at = _normalize_review_date(args.date)
        _review_storage().set_next_action(args.vacancy_id, args.action, next_action_at)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: следующее действие сохранено на {next_action_at}[/green]"
    )
    return 0


# ---------------------------------------------------------------------------
# Review queue commands
# ---------------------------------------------------------------------------


def _print_queue_table(rows: list[dict[str, Any]], title: str = "Review Queue") -> None:
    table = Table(title=title)
    for col in [
        "#",
        "Score",
        "Decision",
        "Preset",
        "Status",
        "Employer",
        "Title",
        "Area",
        "Salary",
        "Risks",
        "URL",
    ]:
        table.add_column(col)
    for i, row in enumerate(rows, 1):
        risks = _short_risks(row.get("risk_flags_json"))
        salary = _short_salary(
            row.get("salary_from"), row.get("salary_to"), row.get("salary_currency")
        )
        table.add_row(
            str(i),
            str(row.get("total_score") or 0),
            row.get("decision") or "-",
            row.get("best_profile") or "-",
            row.get("review_status") or "new",
            (row.get("employer_name") or "")[:25],
            (row.get("name") or "")[:35],
            row.get("area_name") or "",
            salary,
            risks,
            row.get("alternate_url") or "",
        )
    console.print(table)
    # Print copy-paste commands
    if rows:
        ids = " ".join(row["id"] for row in rows[:5])
        console.print(
            f"\n[dim]Copy: review set ID --status interesting | review apply ID --date today[/dim]"
        )
        console.print(f"[dim]Top 5 IDs: {ids}[/dim]")


def _short_risks(risk_flags_json: str | None) -> str:
    if not risk_flags_json or risk_flags_json == "[]":
        return "-"
    from ..utils import json_loads

    flags = json_loads(risk_flags_json, [])
    return ", ".join(str(f) for f in flags[:3])


def _short_salary(sfrom: int | None, sto: int | None, curr: str | None) -> str:
    if sfrom is None and sto is None:
        return "-"
    parts = []
    if sfrom:
        parts.append(str(sfrom))
    if sto:
        parts.append(str(sto))
    txt = "–".join(parts) if parts else "?"
    if curr:
        txt += f" {curr}"
    return txt


def _dedupe_queue(storage, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter *rows* keeping only the best vacancy per cluster.

    "Best" = highest total_score, then latest published_at.
    Non-clustered vacancies pass through.
    """
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    cluster_map = storage.get_clusters_for_vacancies(ids)

    # Group by cluster_id
    clustered: dict[str, list[dict[str, Any]]] = {}
    unclustered: list[dict[str, Any]] = []
    for row in rows:
        cinfo = cluster_map.get(row["id"])
        if cinfo:
            clustered.setdefault(cinfo["cluster_id"], []).append(row)
        else:
            unclustered.append(row)

    # Pick best per cluster
    result: list[dict[str, Any]] = []
    for cid, members in clustered.items():
        best = max(
            members,
            key=lambda r: (
                r.get("total_score", 0),
                r.get("published_at", ""),
            ),
        )
        # Annotate so UI knows this is a cluster member
        best["_cluster_id"] = cid
        best["_cluster_size"] = len(members)
        result.append(best)

    # Sort by score desc (preserve original ordering intention)
    result.extend(unclustered)
    result.sort(key=lambda r: r.get("total_score", 0), reverse=True)
    return result


def command_review_queue(args: argparse.Namespace) -> int:
    storage = _review_storage()
    decisions = args.decision.split(",") if args.decision else None
    try:
        rows = storage.list_queue(
            min_score=args.min_score,
            decisions=decisions,
            preset=args.preset or args.profile,
            status=args.status,
            limit=args.limit,
            remote_only=args.remote_only,
            with_salary=args.with_salary,
            hide_risk=args.hide_risk,
            new_only=args.new_only,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    # Dedupe: show only best per cluster
    if getattr(args, "dedupe", False):
        rows = _dedupe_queue(storage, rows)

    _print_queue_table(rows, "Review Queue")
    console.print(f"\n[dim]{len(rows)} results[/dim]")
    return 0


def command_review_next_best(args: argparse.Namespace) -> int:
    storage = _review_storage()
    try:
        rows = storage.list_queue(
            min_score=70,
            decisions=["strong_match", "queue"],
            new_only=True,
            limit=15,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    _print_queue_table(rows, "Next Best — Top 15 New Strong/Queue Matches")
    console.print(f"\n[dim]{len(rows)} results[/dim]")
    return 0


def _bulk_action(
    storage: Storage,
    new_status: str,
    force: bool,
    **filters: Any,
) -> int:
    """Common bulk update logic with confirmation."""
    result = storage.bulk_update_review_status(
        new_status=new_status,
        force=force,
        **filters,
    )
    matched = result["matched_count"]
    updated = result["updated_count"]
    skipped = result["skipped_protected_count"]

    if matched == 0:
        console.print("[yellow]No matching vacancies found.[/yellow]")
        return 0

    console.print(
        f"Matched: {matched} | Updated: [green]{updated}[/green]"
        + (f" | Skipped (protected): [yellow]{skipped}[/yellow]" if skipped else "")
    )
    return 0


def _confirm_bulk(args: argparse.Namespace, label: str, count: int) -> bool:
    if args.yes:
        return True
    if count == 0:
        return True
    from rich.prompt import Confirm

    console.print(f"\n[yellow]{label}: {count} vacancies will be affected.[/yellow]")
    try:
        return Confirm.ask("Continue?", default=False)
    except (EOFError, KeyboardInterrupt):
        return False


def command_review_bulk_archive(args: argparse.Namespace) -> int:
    storage = _review_storage()
    decision = args.decision or "auto_hide"
    # Count first
    rows = storage.list_queue(decision=decision, limit=1000)
    if not _confirm_bulk(args, f"Bulk archive ({decision})", len(rows)):
        console.print("[yellow]Отменено.[/yellow]")
        return 0
    return _bulk_action(storage, "archived", args.force, decision=decision)


def command_review_bulk_reject(args: argparse.Namespace) -> int:
    storage = _review_storage()
    max_score = args.max_score if args.max_score is not None else 35
    rows = storage.list_queue(max_score=max_score, limit=1000, min_score=0)
    if not _confirm_bulk(args, f"Bulk reject (score ≤ {max_score})", len(rows)):
        console.print("[yellow]Отменено.[/yellow]")
        return 0
    return _bulk_action(storage, "rejected", args.force, max_score=max_score)


def command_review_bulk_interesting(args: argparse.Namespace) -> int:
    storage = _review_storage()
    min_score = args.min_score if args.min_score is not None else 85
    decision = args.decision or "strong_match"
    rows = storage.list_queue(min_score=min_score, decision=decision, limit=1000)
    if not _confirm_bulk(args, f"Bulk interesting (score ≥ {min_score}, {decision})", len(rows)):
        console.print("[yellow]Отменено.[/yellow]")
        return 0
    return _bulk_action(storage, "interesting", args.force, min_score=min_score, decision=decision)


def command_review_bulk_set(args: argparse.Namespace) -> int:
    storage = _review_storage()
    filters: dict[str, Any] = {}
    if args.min_score is not None:
        filters["min_score"] = args.min_score
    if args.max_score is not None:
        filters["max_score"] = args.max_score
    if args.decision:
        filters["decision"] = args.decision
    if args.preset:
        filters["preset"] = args.preset
    if args.status:
        filters["status"] = args.status

    rows = storage.list_queue(**filters, limit=1000)
    label = f"Bulk set → {args.new_status}"
    if not _confirm_bulk(args, label, len(rows)):
        console.print("[yellow]Отменено.[/yellow]")
        return 0
    return _bulk_action(storage, args.new_status, args.force, **filters)
