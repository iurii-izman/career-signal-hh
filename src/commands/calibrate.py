from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import _services
from ..utils import json_loads

console = Console()

GOOD_STATUSES = {"interesting", "applied", "interview", "offer"}
BAD_STATUSES = {"rejected", "archived"}
SUGGESTIONS_PATH = "data/calibration_suggestions.json"


def _load_suggestions() -> list[dict]:
    try:
        return json.loads(Path(SUGGESTIONS_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_suggestions(suggestions: list[dict]) -> None:
    Path(SUGGESTIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SUGGESTIONS_PATH).write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def command_calibrate_analyze(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    good_keywords: dict[str, int] = {}
    bad_keywords: dict[str, int] = {}
    good_total = 0
    bad_total = 0

    with storage.connect() as conn:
        rows = conn.execute(
            """SELECT sd.matched_keywords_json, COALESCE(r.status,'new') status
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id"""
        ).fetchall()

        for kw_json, status in rows:
            keywords = json_loads(kw_json, [])
            if status in GOOD_STATUSES:
                good_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower()
                    if k:
                        good_keywords[k] = good_keywords.get(k, 0) + 1
            elif status in BAD_STATUSES:
                bad_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower()
                    if k:
                        bad_keywords[k] = bad_keywords.get(k, 0) + 1

    if good_total == 0 and bad_total == 0:
        console.print("[yellow]No review data yet. Review some vacancies first.[/yellow]")
        return 0

    table = Table(title="Calibration Analysis")
    table.add_column("Keyword")
    table.add_column("Good (applied/intvw/offer)")
    table.add_column("Bad (rejected/archived)")
    table.add_column("Lift")
    table.add_column("Suggestion")

    all_kw = set(good_keywords) | set(bad_keywords)
    results = []
    for kw in all_kw:
        g = good_keywords.get(kw, 0)
        b = bad_keywords.get(kw, 0)
        g_rate = g / max(1, good_total)
        b_rate = b / max(1, bad_total)
        lift = g_rate / max(0.001, b_rate)
        if g >= 2 or b >= 2:
            sug = ""
            if lift >= 2.0 and b_rate < 0.1:
                sug = "boost"
            elif b_rate > 0.3 and g_rate < 0.1:
                sug = "exclude"
            results.append((kw, g, b, lift, sug))

    results.sort(key=lambda x: -x[3])
    for kw, g, b, lift, sug in results[:30]:
        table.add_row(kw, str(g), str(b), f"{lift:.1f}", sug)

    console.print(table)
    console.print(f"\n[dim]Based on {good_total} good + {bad_total} bad reviews[/dim]")
    return 0


def command_calibrate_suggest(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    good_keywords: dict[str, int] = {}
    bad_keywords: dict[str, int] = {}
    good_total = 0
    bad_total = 0

    with storage.connect() as conn:
        rows = conn.execute(
            """SELECT sd.matched_keywords_json, COALESCE(r.status,'new') status
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
               WHERE sd.preset_name = ? OR ? IS NULL""",
            (args.preset, args.preset),
        ).fetchall()

        for kw_json, status in rows:
            keywords = json_loads(kw_json, [])
            if status in GOOD_STATUSES:
                good_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower()
                    if k:
                        good_keywords[k] = good_keywords.get(k, 0) + 1
            elif status in BAD_STATUSES:
                bad_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower()
                    if k:
                        bad_keywords[k] = bad_keywords.get(k, 0) + 1

    if good_total == 0 and bad_total == 0:
        console.print("[yellow]No review data for this preset.[/yellow]")
        return 0

    suggestions = _load_suggestions()
    new_count = 0

    # Generate exclude suggestions
    for kw, count in sorted(bad_keywords.items(), key=lambda x: -x[1]):
        g = good_keywords.get(kw, 0)
        b_rate = count / max(1, bad_total)
        if b_rate >= 0.3 and g <= 1:
            sid = str(uuid.uuid4())[:8]
            suggestions.append(
                {
                    "id": sid,
                    "preset": args.preset or "all",
                    "type": "add_exclude",
                    "keyword": kw,
                    "reason": f"Appears in {count}/{bad_total} rejected ({b_rate:.0%})",
                    "evidence": {"good_count": g, "bad_count": count, "bad_rate": round(b_rate, 2)},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            new_count += 1
            if new_count >= 10:
                break

    # Generate boost suggestions
    for kw, count in sorted(good_keywords.items(), key=lambda x: -x[1]):
        b = bad_keywords.get(kw, 0)
        g_rate = count / max(1, good_total)
        if g_rate >= 0.3 and b <= 2:
            sid = str(uuid.uuid4())[:8]
            suggestions.append(
                {
                    "id": sid,
                    "preset": args.preset or "all",
                    "type": "add_boost",
                    "keyword": kw,
                    "reason": f"Appears in {count}/{good_total} accepted ({g_rate:.0%})",
                    "evidence": {
                        "good_count": count,
                        "bad_count": b,
                        "good_rate": round(g_rate, 2),
                    },
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            new_count += 1
            if new_count >= 20:
                break

    _save_suggestions(suggestions)
    console.print(f"[green]{new_count} new suggestions saved to {SUGGESTIONS_PATH}[/green]")

    if suggestions:
        table = Table(title="Latest Suggestions")
        table.add_column("ID")
        table.add_column("Type")
        table.add_column("Keyword")
        table.add_column("Reason")
        for s in suggestions[-new_count:]:
            table.add_row(s["id"], s["type"], s["keyword"], s["reason"])
        console.print(table)

    return 0


def command_calibrate_apply(args: argparse.Namespace) -> int:
    suggestions = _load_suggestions()
    target = None
    for s in suggestions:
        if s["id"] == args.suggestion_id:
            target = s
            break
    if target is None:
        console.print(f"[red]Suggestion '{args.suggestion_id}' not found.[/red]")
        return 1

    console.print(f"\nSuggestion: {target['type']} '{target['keyword']}' for {target['preset']}")
    console.print(f"Reason: {target['reason']}")

    if not args.yes:
        from rich.prompt import Confirm

        if not Confirm.ask("Apply this suggestion?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    # Apply: modify search_presets.yaml
    preset_name = target["preset"]
    keyword = target["keyword"]
    typ = target["type"]

    try:
        from datetime import datetime as dt
        from shutil import copy2

        import yaml

        path = Path("config/search_presets.yaml")
        if not path.exists():
            console.print("[red]search_presets.yaml not found.[/red]")
            return 1

        # Backup
        backup_dir = Path("config/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        copy2(path, backup_dir / f"search_presets_{ts}.yaml")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        presets = data.setdefault("presets", {})
        preset = presets.get(preset_name)
        if preset is None:
            console.print(f"[red]Preset '{preset_name}' not found.[/red]")
            return 1

        if typ == "add_exclude":
            preset.setdefault("exclude", {}).setdefault("any", [])
            if keyword not in preset["exclude"]["any"]:
                preset["exclude"]["any"].append(keyword)
                console.print(
                    f"[green]Added '{keyword}' to exclude.any in '{preset_name}'.[/green]"
                )
        elif typ == "add_boost":
            preset.setdefault("boost", {}).setdefault("skills", {})
            if keyword not in preset["boost"]["skills"]:
                preset["boost"]["skills"][keyword] = 10
                console.print(f"[green]Added '{keyword}' boost +10 in '{preset_name}'.[/green]")
        else:
            console.print(f"[yellow]Unknown suggestion type: {typ}[/yellow]")
            return 1

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    except Exception as exc:
        console.print(f"[red]Failed to apply: {exc}[/red]")
        return 1

    console.print(f"[green]Applied. Backup: config/backups/search_presets_{ts}.yaml[/green]")
    return 0


def command_calibrate_export(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    suggestions = _load_suggestions()

    out = Path("exports")

    # JSON
    with open(out / "calibration_suggestions.json", "w", encoding="utf-8") as f:
        json.dump(suggestions, f, ensure_ascii=False, indent=2)
    console.print(f"[green]calibration_suggestions.json ({len(suggestions)} suggestions)[/green]")

    # CSV
    import csv
    import tempfile

    def _write(h):
        w = csv.writer(h)
        w.writerow(["id", "preset", "type", "keyword", "reason"])
        for s in suggestions:
            w.writerow([s["id"], s["preset"], s["type"], s["keyword"], s["reason"]])

    tp = out / "calibration_keywords.csv"
    tp.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=tp.parent
    ) as h:
        _write(h)
        os.replace(h.name, tp)
    console.print(f"[green]calibration_keywords.csv[/green]")

    # HTML
    rows_html = "".join(
        f"<tr><td>{s['id']}</td><td>{s['type']}</td><td>{s['keyword']}</td><td>{s['preset']}</td><td>{s['reason']}</td></tr>"
        for s in suggestions
    )
    html = f"""<!doctype html><html><head><meta charset=utf-8><title>Calibration Report</title>
<style>body{{background:#0b1020;color:#e8edf7;font:14px system-ui;max-width:900px;margin:30px auto;padding:20px}}
h1{{color:#67e8f9}} table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #26324d;text-align:left}} th{{color:#fde68a}}</style></head><body>
<h1>Calibration Suggestions</h1>
<table><tr><th>ID</th><th>Type</th><th>Keyword</th><th>Preset</th><th>Reason</th></tr>{rows_html}</table>
</body></html>"""
    (out / "calibration_report.html").write_text(html, encoding="utf-8")
    console.print(f"[green]calibration_report.html[/green]")
    return 0
