from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..hh_oauth import HHOAuthError
from ..hh_sync import HHSyncService

console = Console()


def command_hh_sync_me(_: argparse.Namespace) -> int:
    load_dotenv()
    service = HHSyncService()
    try:
        result = service.sync_me()
    except Exception as exc:
        return _print_sync_error(exc)
    console.print(f"Synced profile: {result['profile_id']} ({result.get('email') or 'no email'})")
    return 0


def command_hh_sync_resumes(_: argparse.Namespace) -> int:
    load_dotenv()
    service = HHSyncService()
    try:
        result = service.sync_resumes()
    except Exception as exc:
        return _print_sync_error(exc)
    console.print(f"Synced resumes: {result['count']}")
    return 0


def command_hh_sync_negotiations(args: argparse.Namespace) -> int:
    load_dotenv()
    service = HHSyncService()
    try:
        result = service.sync_negotiations(status=args.status, per_page=args.per_page)
    except Exception as exc:
        return _print_sync_error(exc)
    console.print(
        f"Synced negotiations: {result['count']} (status filter: {result.get('status_filter') or 'any'})"
    )
    return 0


def command_hh_sync_messages(args: argparse.Namespace) -> int:
    load_dotenv()
    service = HHSyncService()
    try:
        result = service.sync_messages(
            args.negotiation_id,
            status=args.status,
            per_page=args.per_page,
            messages_per_page=args.messages_per_page,
        )
    except Exception as exc:
        return _print_sync_error(exc)
    console.print(
        "Synced messages: "
        f"{result['count']} across {result['negotiations_synced']}/{result['negotiations_considered']} negotiations"
    )
    if result["failed_negotiations"]:
        console.print(
            "[yellow]Message sync degraded for some negotiations:[/yellow] "
            + ", ".join(item["negotiation_id"] for item in result["failed_negotiations"][:5])
        )
    return 0


def command_hh_sync_reconcile(_: argparse.Namespace) -> int:
    load_dotenv()
    result = HHSyncService().reconcile()
    table = Table(title="HH Read-Only Reconcile")
    table.add_column("Metric")
    table.add_column("Value")
    for key in [
        "profiles",
        "resumes",
        "negotiations",
        "messages",
        "negotiations_matched_local_vacancies",
        "negotiations_unmatched_local_vacancies",
        "matched_without_review",
        "matched_remote_newer_than_review",
        "negotiations_with_unread_messages",
        "read_only",
    ]:
        table.add_row(key, str(result[key]))
    console.print(table)
    for line in result.get("actionable_summary", []):
        console.print(f"- {line}")
    return 0


def _print_sync_error(exc: Exception) -> int:
    if isinstance(exc, HHOAuthError):
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[red]{exc}[/red]")
    return 1
