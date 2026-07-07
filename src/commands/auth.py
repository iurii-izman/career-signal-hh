from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..config import _short_body
from ..hh_client import HHAPIError, HHClient

console = Console()


def command_auth_check(_: argparse.Namespace) -> int:
    load_dotenv()
    client = HHClient()
    token_present = getattr(client, "active_token_present", bool(client.app_access_token))
    token_env_name = getattr(client, "active_token_env_name", "HH_APP_ACCESS_TOKEN")
    console.print(f"HH_AUTH_MODE: [bold]{client.auth_mode}[/bold]")
    console.print(
        f"{token_env_name}: "
        + ("[green]указан[/green]" if token_present else "[yellow]не указан[/yellow]")
    )
    console.print(f"HH_USER_AGENT: {client.user_agent}")

    table = Table(title="Проверка доступа HH API")
    table.add_column("Проверка")
    table.add_column("Результат")
    table.add_column("Status")
    table.add_column("Объяснение")
    checks = [
        ("GET /me", client.get_me),
        (
            "GET /vacancies",
            lambda: client.search_vacancies("python", per_page=1),
        ),
    ]
    failed = False
    for label, operation in checks:
        try:
            operation()
            table.add_row(label, "[green]OK[/green]", "200", "Доступ разрешён")
        except NotImplementedError as exc:
            failed = True
            table.add_row(label, "[red]FAIL[/red]", "-", str(exc))
        except HHAPIError as exc:
            failed = True
            status = str(exc.status_code) if exc.status_code is not None else "-"
            explanation = str(exc)
            body = _short_body(exc.body)
            if body and body not in explanation:
                explanation = f"{explanation}\nBody: {body}"
            table.add_row(label, "[red]FAIL[/red]", status, explanation)
        except Exception as exc:
            failed = True
            table.add_row(label, "[red]FAIL[/red]", "-", f"Ошибка соединения: {exc}")
    console.print(table)
    return 1 if failed else 0
