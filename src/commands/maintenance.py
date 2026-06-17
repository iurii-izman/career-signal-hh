"""Maintenance commands — retention cleanup and health report."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

console = Console()

CONFIG_PATH = "config/maintenance.yaml"

PROTECTED_PATTERNS = [
    "data/*.sqlite",
    ".env",
    "data/calibration_suggestions.json",
]


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _is_protected(file_path: Path) -> bool:
    """True if file should never be deleted."""
    s = str(file_path).replace("\\", "/")
    for pat in PROTECTED_PATTERNS:
        if Path(pat.replace("\\", "/")).match(s) or s.endswith(pat.replace("*", "")):
            return True
    # Also protect .env anywhere
    if file_path.name == ".env":
        return True
    if file_path.suffix == ".sqlite" and "data" in file_path.parts:
        return True
    return False


def _scan_category(path_str: str, pattern: str, days: int | None, count: int | None) -> dict:
    """Scan a directory and return files to keep/delete based on policy."""
    p = Path(path_str)
    if not p.exists():
        return {
            "path": path_str,
            "pattern": pattern,
            "files": [],
            "keep": [],
            "to_delete": [],
            "total_size": 0,
            "delete_size": 0,
            "total_count": 0,
            "delete_count": 0,
            "keep_count": 0,
        }

    files = sorted(p.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    files = [f for f in files if f.is_file() and not _is_protected(f)]

    total_size = sum(f.stat().st_size for f in files)
    cutoff = None
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)

    keep: list[Path] = []
    delete: list[Path] = []

    for i, f in enumerate(files):
        # Keep by count
        if count is not None and i < count:
            keep.append(f)
            continue
        # Keep by age
        if cutoff is not None and datetime.fromtimestamp(f.stat().st_mtime) > cutoff:
            keep.append(f)
            continue
        delete.append(f)

    delete_size = sum(f.stat().st_size for f in delete)

    return {
        "path": path_str,
        "pattern": pattern,
        "files": files,
        "keep": keep,
        "to_delete": delete,
        "total_size": total_size,
        "delete_size": delete_size,
        "total_count": len(files),
        "delete_count": len(delete),
        "keep_count": len(keep),
    }


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def command_maintenance_report(_: argparse.Namespace) -> int:
    """Show what would be cleaned up under current retention policy."""
    config = _load_config()
    retention = config.get("retention", {})

    table = Table(title="Maintenance Report (dry-run)")
    table.add_column("Category")
    table.add_column("Path")
    table.add_column("Files", justify="right")
    table.add_column("Total Size", justify="right")
    table.add_column("To Delete", justify="right")
    table.add_column("Delete Size", justify="right")
    table.add_column("Policy")

    total_delete_size = 0
    total_delete_count = 0

    for category, rules in retention.items():
        if not isinstance(rules, dict):
            continue

        path_str = rules.get("path", "")
        pattern = rules.get("pattern", "*")
        days = rules.get("days")
        count = rules.get("count")

        scan = _scan_category(path_str, pattern, days, count)

        policy_parts = []
        if days:
            policy_parts.append(f"{days}d")
        if count:
            policy_parts.append(f"keep {count}")

        table.add_row(
            category,
            path_str,
            str(scan["total_count"]),
            _fmt_size(scan["total_size"]),
            str(scan["delete_count"]),
            _fmt_size(scan["delete_size"]),
            ", ".join(policy_parts) if policy_parts else "-",
        )
        total_delete_size += scan["delete_size"]
        total_delete_count += scan["delete_count"]

    console.print(table)

    if total_delete_count > 0:
        console.print(
            f"\n[yellow]{total_delete_count} files ({_fmt_size(total_delete_size)}) eligible for deletion.[/yellow]"
        )
        console.print(
            "[dim]Run `maintenance cleanup --dry-run` to preview, `--yes` to execute.[/dim]"
        )
    else:
        console.print("\n[green]Nothing to clean up.[/green]")

    # Protected files awareness
    console.print(
        "\n[dim]Protected (never deleted): data/*.sqlite, .env, data/calibration_suggestions.json[/dim]"
    )

    return 0


def command_maintenance_cleanup(args: argparse.Namespace) -> int:
    """Delete old files according to retention policy."""
    config = _load_config()
    retention = config.get("retention", {})

    all_scans: list[dict] = []
    for category, rules in retention.items():
        if not isinstance(rules, dict):
            continue
        path_str = rules.get("path", "")
        pattern = rules.get("pattern", "*")
        days = rules.get("days")
        count = rules.get("count")

        scan = _scan_category(path_str, pattern, days, count)
        if scan["to_delete"]:
            all_scans.append(scan)

    total_delete = sum(s["delete_count"] for s in all_scans)
    total_size = sum(s["delete_size"] for s in all_scans)

    if total_delete == 0:
        console.print("[green]Nothing to clean up.[/green]")
        return 0

    # Show preview
    table = Table(title="Cleanup Preview")
    table.add_column("Category")
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right")

    for s in all_scans:
        table.add_row(
            s["path"],
            str(s["delete_count"]),
            _fmt_size(s["delete_size"]),
        )
    console.print(table)

    # Default to dry-run behaviour unless --yes is explicitly given.
    if not args.yes:
        console.print(
            f"\n[yellow][DRY RUN] Would delete {total_delete} files ({_fmt_size(total_size)}).[/yellow]"
        )
        console.print("[dim]Run with --yes to execute.[/dim]")
        return 0

    # --yes mode: user already opted in, proceed without interactive prompt
    console.print(f"\n[yellow]Deleting {total_delete} files ({_fmt_size(total_size)})...[/yellow]")

    # Execute deletions
    deleted = 0
    log_lines = [f"Maintenance cleanup — {datetime.now(timezone.utc).isoformat()}"]
    for s in all_scans:
        for f in s["to_delete"]:
            try:
                # Also clean matching .html for .md files in apply_packs
                f.unlink()
                if f.suffix == ".md":
                    html_sibling = f.with_suffix(".html")
                    if html_sibling.exists():
                        html_sibling.unlink()
                        deleted += 1
                deleted += 1
                log_lines.append(f"  DELETED {f}")
            except OSError as exc:
                log_lines.append(f"  ERROR {f}: {exc}")

    log_lines.append(f"Total deleted: {deleted} files ({_fmt_size(total_size)})")
    log_path = Path("logs") / f"maintenance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    console.print(f"[green]Deleted {deleted} files ({_fmt_size(total_size)}).[/green]")
    console.print(f"[dim]Log: {log_path}[/dim]")
    return 0
