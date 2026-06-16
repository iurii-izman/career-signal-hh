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
        raise ValueError(
            f"Некорректная дата {value!r}. Используйте today или YYYY-MM-DD."
        ) from exc


def command_review_list(args: argparse.Namespace) -> int:
    storage = _review_storage()
    try:
        rows = storage.list_reviewed_vacancies(
            status=args.status,
            min_score=args.min_score,
            limit=args.limit,
            profile=args.profile,
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
    console.print(
        f"[green]{args.vacancy_id}: status=applied, applied_at={applied_at}[/green]"
    )
    return 0


def command_review_next(args: argparse.Namespace) -> int:
    try:
        next_action_at = _normalize_review_date(args.date)
        _review_storage().set_next_action(args.vacancy_id, args.action, next_action_at)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"[green]{args.vacancy_id}: следующее действие сохранено "
        f"на {next_action_at}[/green]"
    )
    return 0
