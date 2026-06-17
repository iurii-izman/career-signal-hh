"""Manual vacancy import — CSV, JSONL, text-file, and single vacancy.

Usage:
  python -m src.main import vacancy --title "..." --company "..." --url "..." --preset NAME
  python -m src.main import csv path/to/vacancies.csv
  python -m src.main import jsonl path/to/vacancies.jsonl
  python -m src.main import text-file path/to/vacancies.txt
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console

from ..models import Vacancy
from ..scoring_v2 import _to_score_result, compute_score_details
from ..search_presets import get_preset
from ..storage import Storage

console = Console()


def _storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def _make_manual_id(url: str, fallback: str = "") -> str:
    """Generate a deterministic manual_<hash> id from URL."""
    if url:
        h = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"manual_{h}"
    if fallback:
        h = hashlib.sha256(fallback.encode()).hexdigest()[:12]
        return f"manual_{h}"
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"manual_{ts}"


def _import_one(
    storage: Storage,
    title: str,
    company: str,
    url: str,
    *,
    area: str = "",
    description: str = "",
    salary_from: int | None = None,
    salary_to: int | None = None,
    currency: str = "",
    schedule: str = "",
    preset_name: str | None = None,
    notes: str = "",
) -> str:
    """Import a single vacancy. Returns the vacancy ID (new or existing)."""
    now = datetime.now(timezone.utc).isoformat()

    # Idempotent by URL
    existing_id = storage.find_by_url(url)
    is_update = existing_id is not None
    vid = existing_id or _make_manual_id(url, f"{title}|{company}")

    vacancy = Vacancy(
        id=vid,
        name=title,
        employer_name=company,
        area_name=area,
        alternate_url=url,
        salary_from=salary_from,
        salary_to=salary_to,
        salary_currency=currency or None,
        schedule_name=schedule or None,
        description_text=description,
        description_html=description,
        raw_json=json.dumps({"source": "manual", "imported_at": now}),
        first_seen_at=now,
        last_seen_at=now,
        source_profile=preset_name,
    )
    storage.upsert_vacancy(vacancy)

    # Score if preset provided
    if preset_name:
        preset = get_preset(preset_name)
        if preset:
            details = compute_score_details(vacancy, {**preset, "_name": preset_name})
            storage.upsert_score_details(details)
            storage.upsert_score(_to_score_result(details))

    # Save notes as review note
    if notes:
        storage.upsert_review(vid, user_notes=notes)

    action = "Updated" if is_update else "Imported"
    console.print(f"  [green]✓[/green] {action}: {vid} — {title[:60]}")

    return vid


# ── Single vacancy ─────────────────────────────────────────────────────────


def command_import_vacancy(args: argparse.Namespace) -> int:
    """Import a single vacancy from CLI arguments."""
    if not args.title or not args.company or not args.url:
        console.print("[red]--title, --company, and --url are required.[/red]")
        return 1

    storage = _storage()
    _import_one(
        storage,
        title=args.title,
        company=args.company,
        url=args.url,
        area=getattr(args, "area", "") or "",
        description=getattr(args, "description", "") or "",
        salary_from=getattr(args, "salary_from", None),
        salary_to=getattr(args, "salary_to", None),
        currency=getattr(args, "currency", "") or "",
        schedule=getattr(args, "schedule", "") or "",
        preset_name=getattr(args, "preset", None),
        notes=getattr(args, "notes", "") or "",
    )
    return 0


# ── CSV import ─────────────────────────────────────────────────────────────


def command_import_csv(args: argparse.Namespace) -> int:
    """Import vacancies from a CSV file."""
    path = Path(args.path)
    if not path.is_file():
        console.print(f"[red]File not found: {path}[/red]")
        return 1

    storage = _storage()
    imported = 0
    updated = 0
    errors = 0

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            title = (row.get("title") or row.get("name") or "").strip()
            company = (row.get("company") or row.get("employer_name") or "").strip()
            url = (row.get("url") or row.get("alternate_url") or row.get("link") or "").strip()

            if not title or not url:
                console.print(f"  [yellow]Row {i}: missing title or url, skipped[/yellow]")
                errors += 1
                continue

            existing = storage.find_by_url(url)
            if existing:
                updated += 1
            else:
                imported += 1

            _import_one(
                storage,
                title=title,
                company=company,
                url=url,
                area=row.get("area", "").strip(),
                description=row.get("description", "").strip(),
                salary_from=_parse_int(row.get("salary_from")),
                salary_to=_parse_int(row.get("salary_to")),
                currency=row.get("currency", "").strip(),
                schedule=row.get("schedule", "").strip(),
                preset_name=row.get("preset", "").strip() or None,
                notes=row.get("notes", "").strip(),
            )

    console.print(
        f"\n[green]CSV import: {imported} new, {updated} updated, {errors} skipped[/green]"
    )
    return 0 if errors == 0 else 1


# ── JSONL import ───────────────────────────────────────────────────────────


def command_import_jsonl(args: argparse.Namespace) -> int:
    """Import vacancies from a JSONL file (one JSON object per line)."""
    path = Path(args.path)
    if not path.is_file():
        console.print(f"[red]File not found: {path}[/red]")
        return 1

    storage = _storage()
    imported = 0
    updated = 0
    errors = 0

    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                console.print(f"  [yellow]Line {i}: invalid JSON, skipped[/yellow]")
                errors += 1
                continue

            title = (row.get("title") or row.get("name") or "").strip()
            company = (row.get("company") or row.get("employer_name") or "").strip()
            url = (row.get("url") or row.get("alternate_url") or row.get("link") or "").strip()

            if not title or not url:
                console.print(f"  [yellow]Line {i}: missing title or url, skipped[/yellow]")
                errors += 1
                continue

            existing = storage.find_by_url(url)
            if existing:
                updated += 1
            else:
                imported += 1

            _import_one(
                storage,
                title=title,
                company=company,
                url=url,
                area=row.get("area", "").strip(),
                description=row.get("description", "").strip(),
                salary_from=row.get("salary_from"),
                salary_to=row.get("salary_to"),
                currency=row.get("currency", "").strip(),
                schedule=row.get("schedule", "").strip(),
                preset_name=row.get("preset", "").strip() or None,
                notes=row.get("notes", "").strip(),
            )

    console.print(
        f"\n[green]JSONL import: {imported} new, {updated} updated, {errors} skipped[/green]"
    )
    return 0 if errors == 0 else 1


# ── Text file import (one per line: title|company|url) ────────────────────


def command_import_text_file(args: argparse.Namespace) -> int:
    """Import vacancies from a text file.

    Format: one vacancy per line: title | company | url
    Optional fields after url: area | description | preset
    """
    path = Path(args.path)
    if not path.is_file():
        console.print(f"[red]File not found: {path}[/red]")
        return 1

    storage = _storage()
    imported = 0
    errors = 0

    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                console.print(
                    f"  [yellow]Line {i}: need at least title|company|url, skipped[/yellow]"
                )
                errors += 1
                continue

            title, company, url = parts[0], parts[1], parts[2]
            area = parts[3] if len(parts) > 3 else ""
            description = parts[4] if len(parts) > 4 else ""
            preset_name = parts[5] if len(parts) > 5 else None

            _import_one(
                storage,
                title=title,
                company=company,
                url=url,
                area=area,
                description=description,
                preset_name=preset_name,
            )
            imported += 1

    console.print(f"\n[green]Text import: {imported} imported, {errors} skipped[/green]")
    return 0 if errors == 0 else 1


# ── Helpers ────────────────────────────────────────────────────────────────


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None
