from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..hh_client import HHConfigurationError
from ..hh_oauth import HHOAuthError, HHOAuthManager

console = Console()


def command_oauth_status(_: argparse.Namespace) -> int:
    load_dotenv()
    status = HHOAuthManager().status()
    table = Table(title="HH OAuth V2 Status")
    table.add_column("Field")
    table.add_column("Value")
    for label, value in [
        ("configured", "yes" if status["configured"] else "no"),
        ("storage_backend", status["storage_backend"]),
        ("managed_access_token", "present" if status["managed_access_token_present"] else "missing"),
        ("managed_refresh_token", "present" if status["managed_refresh_token_present"] else "missing"),
        ("managed_access_hint", status["managed_access_token_hint"]),
        ("managed_refresh_hint", status["managed_refresh_token_hint"]),
        ("manual_env_token", "present" if status["manual_env_token_present"] else "missing"),
        ("manual_env_hint", status["manual_env_token_hint"]),
        ("account_id", status["account_id"] or "-"),
        ("account_email", status["account_email"] or "-"),
        ("scope", status["scope"] or "-"),
        ("token_type", status["token_type"] or "-"),
        ("obtained_at", status["obtained_at"] or "-"),
        ("expires_at", status["expires_at"] or "-"),
        ("expired", "yes" if status["expired"] else "no"),
        ("last_refresh_at", status["last_refresh_at"] or "-"),
        ("last_sync_at", status["last_sync_at"] or "-"),
        ("last_error", status["last_error"] or "-"),
        ("storage_error", status["storage_error"] or "-"),
    ]:
        table.add_row(label, str(value))
    console.print(table)
    return 0


def command_oauth_login(args: argparse.Namespace) -> int:
    load_dotenv()
    manager = HHOAuthManager()
    try:
        result = manager.login(code=args.code, open_browser=args.open_browser)
    except (HHOAuthError, HHConfigurationError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    console.print(f"Authorization URL: {result['authorization_url']}")
    if not result["ok"]:
        console.print(result["message"])
        return 0
    console.print(result["message"])
    profile = result.get("profile") or {}
    console.print(f"Account: id={profile.get('id') or '-'}, email={profile.get('email') or '-'}")
    return 0


def command_oauth_refresh(_: argparse.Namespace) -> int:
    load_dotenv()
    manager = HHOAuthManager()
    try:
        bundle = manager.refresh()
    except (HHOAuthError, HHConfigurationError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print("Managed OAuth access token refreshed.")
    console.print(f"Expires at: {bundle.expires_at.isoformat() if bundle.expires_at else 'unknown'}")
    return 0


def command_oauth_revoke_local(_: argparse.Namespace) -> int:
    load_dotenv()
    manager = HHOAuthManager()
    try:
        result = manager.revoke_local()
    except HHOAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(result["message"])
    return 0
