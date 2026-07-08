from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..services.notion_sync_service import NotionSyncService, load_notion_sync_config
from ..storage import Storage
from ..utils import json_dumps

console = Console()


def _service() -> NotionSyncService:
    import os

    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    return NotionSyncService(storage, load_notion_sync_config())


def _short_error(value: str | None, limit: int = 80) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _print_status_table(rows: list[dict[str, object]]) -> None:
    table = Table(title="Notion / n8n Outbox")
    for column in ["ID", "Status", "Attempts", "Event", "Vacancy", "Created", "Updated", "Last Error"]:
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("status") or ""),
            str(row.get("attempts") or 0),
            str(row.get("event_type") or ""),
            str(row.get("vacancy_id") or ""),
            str(row.get("created_at") or "")[:19],
            str(row.get("updated_at") or "")[:19],
            _short_error(str(row.get("last_error") or "")),
        )
    console.print(table)


def command_notion_sync_status(args: argparse.Namespace) -> int:
    service = _service()
    summary = service.storage.summarize_outbox(target=service.config.target)
    rows = service.list_entries(
        status=args.status,
        vacancy_id=args.vacancy_id,
        outbox_id=args.outbox_id,
        limit=args.limit,
    )
    url_label = service.config.webhook_url_env
    if service.config.webhook_url:
        from ..services.notion_sync_service import redact_webhook_url

        url_label = redact_webhook_url(service.config.webhook_url) or url_label

    console.print(
        f"enabled={service.config.enabled} | provider={service.config.provider} | "
        f"target={service.config.target} | webhook={url_label}"
    )
    console.print(
        f"total={summary['total']} | pending={summary['counts'].get('pending', 0)} | "
        f"failed={summary['counts'].get('failed', 0)} | sent={summary['counts'].get('sent', 0)}"
    )
    if summary["oldest_pending_at"]:
        console.print(f"oldest pending: {summary['oldest_pending_at']}")
    if summary["oldest_failed_at"]:
        console.print(f"oldest failed update: {summary['oldest_failed_at']}")
    if rows:
        _print_status_table(rows)
    else:
        console.print("[yellow]No matching outbox entries.[/yellow]")
    return 0


def command_notion_sync_dry_run(args: argparse.Namespace) -> int:
    service = _service()
    rows = service.dry_run_entries(
        status=args.status,
        vacancy_id=args.vacancy_id,
        outbox_id=args.outbox_id,
        limit=args.limit,
        replayed=args.replay,
    )
    if not rows:
        console.print("[yellow]No matching outbox entries.[/yellow]")
        return 0
    for item in rows:
        entry = item["entry"]
        console.print(
            f"[bold]Outbox #{entry['id']}[/bold] "
            f"event={entry['event_type']} vacancy={entry.get('vacancy_id') or '-'} "
            f"status={entry['status']} attempts={entry['attempts']}"
        )
        console.print(f"url: {item['url'] or '(not configured)'}")
        console.print(f"headers: {json_dumps(item['headers'])}")
        console.print(item["body"])
        console.print()
    return 0


def command_notion_sync_push(args: argparse.Namespace) -> int:
    service = _service()
    try:
        result = service.push_entries(
            status=args.status,
            vacancy_id=args.vacancy_id,
            outbox_id=args.outbox_id,
            limit=args.limit,
            replayed=args.replay,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    console.print(
        f"processed={result['processed']} | sent=[green]{result['sent']}[/green] | "
        f"failed=[red]{result['failed']}[/red]"
    )
    if result["results"]:
        table = Table(title="Push Results")
        for column in ["ID", "Status", "HTTP", "Attempts", "Last Error"]:
            table.add_column(column)
        for row in result["results"]:
            table.add_row(
                str(row["id"]),
                str(row["status"]),
                str(row["http_status"] or "-"),
                str(row["attempts"]),
                _short_error(row["last_error"]),
            )
        console.print(table)
    return 0 if result["failed"] == 0 else 1


def command_notion_sync_retry_failed(args: argparse.Namespace) -> int:
    service = _service()
    try:
        result = service.push_entries(
            status="failed",
            vacancy_id=args.vacancy_id,
            outbox_id=args.outbox_id,
            limit=args.limit,
            replayed=True,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"retry-failed processed={result['processed']} | "
        f"sent=[green]{result['sent']}[/green] | failed=[red]{result['failed']}[/red]"
    )
    return 0 if result["failed"] == 0 else 1


def command_notion_sync_replay(args: argparse.Namespace) -> int:
    if args.outbox_id is None:
        console.print("[red]Specify --outbox-id for replay.[/red]")
        return 2
    service = _service()
    entry = service.storage.get_outbox_entry(args.outbox_id)
    if not entry:
        console.print(f"[red]Outbox entry id={args.outbox_id} not found.[/red]")
        return 2
    if entry["status"] == "sent" and not args.dry_run:
        console.print(
            "[red]Replay for already sent entries is blocked to preserve local audit state. "
            "Use --dry-run to inspect the payload.[/red]"
        )
        return 2
    if args.dry_run:
        dry = service.dry_run_entries(outbox_id=args.outbox_id, limit=1, replayed=True)
        if not dry:
            console.print("[yellow]No matching outbox entry.[/yellow]")
            return 0
        item = dry[0]
        console.print(
            f"[bold]Replay dry-run for outbox #{args.outbox_id}[/bold] "
            f"event={entry['event_type']} status={entry['status']}"
        )
        console.print(item["body"])
        return 0
    try:
        result = service.push_entries(
            status=None,
            outbox_id=args.outbox_id,
            limit=1,
            replayed=True,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    console.print(
        f"replay processed={result['processed']} | "
        f"sent=[green]{result['sent']}[/green] | failed=[red]{result['failed']}[/red]"
    )
    return 0 if result["failed"] == 0 else 1
