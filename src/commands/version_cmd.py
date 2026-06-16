from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()[:8]
    except Exception:
        return "unknown"


def command_version(_: argparse.Namespace) -> int:
    from .. import __version__

    table = Table(title="CareerSignal HH Version")
    table.add_column("Property")
    table.add_column("Value")
    table.add_row("Version", __version__)
    table.add_row("Git commit", _git_commit())
    table.add_row("Python", sys.version.split()[0])
    table.add_row("DB path", os.getenv("DB_PATH", "data/vacancies.sqlite"))
    table.add_row("Config", str(Path("config").resolve()))
    console.print(table)
    return 0
