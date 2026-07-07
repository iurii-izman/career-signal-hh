"""Health command — read-only project sanity checks."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .. import __version__
from ..db_migrations import apply_migrations, check_integrity_extended
from ..search_presets import load_search_presets

console = Console()


def _check(result: bool, ok: str, fail: str) -> tuple[str, str]:
    """Return (label, rich‑markup line) for a pass/fail check."""
    if result:
        return "OK", f"[green]{ok}[/green]"
    return "FAIL", f"[red]{fail}[/red]"


def _warn_if(result: bool, ok: str, warn: str) -> tuple[str, str]:
    if result:
        return "OK", f"[green]{ok}[/green]"
    return "WARN", f"[yellow]{warn}[/yellow]"


def _latest_file_age(glob_pattern: str) -> int | None:
    """Return age in hours of the newest file matching *glob_pattern*, or None."""
    best_mtime: float | None = None
    for path in Path().glob(glob_pattern):
        if path.is_file():
            mt = path.stat().st_mtime
            if best_mtime is None or mt > best_mtime:
                best_mtime = mt
    if best_mtime is None:
        return None
    return int((datetime.now().timestamp() - best_mtime) / 3600)


def _maintenance_summary() -> str:
    """One-line maintenance report summary."""
    config_path = Path("config/maintenance.yaml")
    if not config_path.is_file():
        return "config/maintenance.yaml missing"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return "config/maintenance.yaml unreadable"
    retention = cfg.get("retention", {})
    categories = [k for k, v in retention.items() if isinstance(v, dict)]
    return f"{len(categories)} categories: {', '.join(categories[:5])}"


def command_health(_: argparse.Namespace) -> int:
    """Run read‑only sanity checks; exit 0 if OK or warnings, 1 if critical."""
    load_dotenv()
    checks: list[tuple[str, str, str]] = []

    def add(label: str, status: str, detail: str) -> None:
        checks.append((label, status, detail))

    # ── Version ──────────────────────────────────────────────────────────
    add("Version", "OK", __version__)

    # ── DB integrity ─────────────────────────────────────────────────────
    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")
    db_file = Path(db_path)
    if db_file.is_file():
        import sqlite3

        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        try:
            # PRAGMA integrity_check
            row = conn.execute("PRAGMA integrity_check").fetchone()
            pragma_ok = row is not None and row[0] == "ok"
            status, text = _check(
                pragma_ok, "OK", f"integrity_check: {row[0] if row else 'no result'}"
            )
            add("DB integrity", status, text)

            # Extended integrity
            ext = check_integrity_extended(conn)
            wf_ok = ext.get("score_details_has_wf_flags", True)
            idx_missing = ext.get("missing_indexes", [])
            ver_current = ext.get("current_schema_version", 0)
            ver_expected = ext.get("expected_schema_version", 0)

            s, t = _check(wf_ok, "OK", "work_format_flags_json missing in score_details")
            add("DB work_format column", s, t)

            if idx_missing:
                add("DB indexes", "WARN", f"missing: {', '.join(idx_missing)}")
            else:
                add("DB indexes", "OK", "all present")

            if ver_current < ver_expected:
                add(
                    "DB schema version",
                    "WARN",
                    f"{ver_current} < {ver_expected} ({ver_expected - ver_current} pending)",
                )
            else:
                add("DB schema version", "OK", f"{ver_current} (expected {ver_expected})")

            # Pending migration check (re-apply and count failed)
            mig_result = apply_migrations(conn)
            if mig_result["failed"] > 0:
                failed_names = [d["name"] for d in mig_result["details"] if d["status"] == "failed"]
                add(
                    "DB pending migrations",
                    "FAIL",
                    f"{mig_result['failed']} failed: {', '.join(failed_names)}",
                )
            elif mig_result["applied"] > 0:
                add("DB pending migrations", "OK", f"{mig_result['applied']} applied now")
            else:
                add("DB pending migrations", "OK", "up to date")
        finally:
            conn.close()
    else:
        add("DB integrity", "WARN", f"DB file not found: {db_path}")
        add("DB work_format column", "OK", "n/a (no DB)")
        add("DB indexes", "OK", "n/a (no DB)")
        add("DB schema version", "OK", "n/a (no DB)")
        add("DB pending migrations", "OK", "n/a (no DB)")

    # ── Presets validate ─────────────────────────────────────────────────
    try:
        presets_data = load_search_presets()
        presets_list = presets_data.get("presets", {})
        if not isinstance(presets_list, dict):
            add("Presets validate", "FAIL", "presets is not a dict")
        else:
            invalid: list[str] = []
            for name, pdata in presets_list.items():
                if not pdata.get("search_terms"):
                    invalid.append(name)
            if invalid:
                add(
                    "Presets validate",
                    "WARN",
                    f"{len(invalid)} presets have no search_terms: {', '.join(invalid[:3])}",
                )
            else:
                add("Presets validate", "OK", f"{len(presets_list)} presets valid")
    except (OSError, yaml.YAMLError) as exc:
        add("Presets validate", "WARN", f"YAML load error: {exc}")

    # ── Doctor local checks (subset) ─────────────────────────────────────
    for filename, required in [
        (".env", False),
        ("config/search_presets.yaml", False),
        ("config/scoring_rules.yaml", True),
    ]:
        path = Path(filename)
        if required:
            s, t = _check(path.is_file(), "exists", "missing (required)")
        else:
            s, t = _warn_if(path.is_file(), "exists", "missing (optional)")
        add(f"Config: {filename}", s, t)

    # ── .env in application_token mode ───────────────────────────────────
    from ..hh_client import HHClient

    client = HHClient()
    if client.auth_mode in {"application_token", "user_oauth"} and not client.active_token_present:
        add(
            "Auth token",
            "FAIL",
            f"{client.auth_mode} mode but {client.active_token_env_name} missing",
        )
    else:
        token_status = "set" if client.active_token_present else "not set"
        add("Auth token", "OK", f"mode={client.auth_mode}, token={token_status}")

    # ── Latest backup age ────────────────────────────────────────────────
    backup_age = _latest_file_age("backups/vacancies_*.sqlite")
    if backup_age is None:
        add("Latest backup", "WARN", "no backups found")
    elif backup_age > 48:
        add("Latest backup", "WARN", f"{backup_age}h old (>48h)")
    else:
        add("Latest backup", "OK", f"{backup_age}h ago")

    # ── Latest export age ────────────────────────────────────────────────
    export_age = _latest_file_age("exports/vacancies_report.html")
    if export_age is None:
        add("Latest export", "WARN", "no export found")
    elif export_age > 48:
        add("Latest export", "WARN", f"{export_age}h old (>48h)")
    else:
        add("Latest export", "OK", f"{export_age}h ago")

    # ── Maintenance report summary ───────────────────────────────────────
    add("Maintenance config", "OK", _maintenance_summary())

    # ═════════════════════════════════════════════════════════════════════
    # Render table (no token printed — only set/not set)
    # ═════════════════════════════════════════════════════════════════════
    table = Table(title="CareerSignal HH Health")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    critical = False
    for label, status, detail in checks:
        table.add_row(label, status, detail)
        if status == "FAIL":
            critical = True
    console.print(table)

    return 1 if critical else 0
