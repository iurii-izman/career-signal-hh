from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from ..config import _services
from ..utils import json_loads

console = Console()

GOOD_STATUSES = {"interesting", "applied", "interview", "offer"}
BAD_STATUSES = {"rejected", "archived"}
SUGGESTIONS_PATH = "data/calibration_suggestions.json"

SCORE_BUCKETS = [
    (0, 24),
    (25, 49),
    (50, 69),
    (70, 84),
    (85, 100),
]


# ── Suggestion CRUD ────────────────────────────────────────────────────────


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


def _suggestion_exists(suggestions: list[dict], preset: str, typ: str, keyword: str) -> bool:
    """Check if a suggestion with same preset/type/keyword already exists
    and is pending or applied."""
    for s in suggestions:
        if (
            s.get("preset") == preset
            and s.get("type") == typ
            and (s.get("keyword") or s.get("search_term", "")) == keyword
            and s.get("status", "pending") in ("pending", "applied")
        ):
            return True
    return False


def _add_suggestion(
    suggestions: list[dict],
    preset: str,
    typ: str,
    keyword: str,
    reason: str,
    evidence: dict,
    target_path: str = "",
    proposed_value: object = None,
) -> str | None:
    """Add suggestion if not duplicate. Returns suggestion id or None."""
    if _suggestion_exists(suggestions, preset, typ, keyword):
        return None
    sid = str(uuid.uuid4())[:8]
    suggestions.append(
        {
            "id": sid,
            "preset": preset,
            "type": typ,
            "keyword": keyword if "search_term" not in typ else "",
            "search_term": keyword if "search_term" in typ else "",
            "target_path": target_path,
            "proposed_value": proposed_value,
            "reason": reason,
            "evidence": evidence,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "applied_at": None,
        }
    )
    return sid


# ── Analyze ────────────────────────────────────────────────────────────────


def command_calibrate_analyze(_: argparse.Namespace) -> int:
    storage, _, _ = _services()

    good_keywords: dict[str, dict[str, int]] = {}
    bad_keywords: dict[str, dict[str, int]] = {}
    good_total = 0
    bad_total = 0
    neutral_total = 0

    # Preset performance
    preset_stats: dict[str, dict[str, int]] = {}
    # Score buckets
    bucket_stats: dict[str, dict[str, int]] = {"good": {}, "bad": {}, "neutral": {}}

    with storage.connect() as conn:
        rows = conn.execute(
            """SELECT sd.matched_keywords_json, sd.excluded_keywords_json,
                      sd.total_score, sd.preset_name,
                      COALESCE(r.status,'new') status
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id"""
        ).fetchall()

        for kw_json, ex_json, total_score, preset, status in rows:
            pname = preset or "unknown"

            # Preset counters
            ps = preset_stats.setdefault(pname, {"reviewed": 0, "good": 0, "bad": 0})
            ps["reviewed"] += 1

            # Score bucket
            bucket = _bucket(total_score or 0)

            if status in GOOD_STATUSES:
                good_total += 1
                ps["good"] += 1
                target = bucket_stats["good"]
                for kw in json_loads(kw_json, []):
                    k = kw.get("keyword", "").lower().strip()
                    if k:
                        field = kw.get("field", "any")
                        good_keywords.setdefault(k, {}).setdefault(field, 0)
                        good_keywords[k][field] += 1
            elif status in BAD_STATUSES:
                bad_total += 1
                ps["bad"] += 1
                target = bucket_stats["bad"]
                for kw in json_loads(kw_json, []):
                    k = kw.get("keyword", "").lower().strip()
                    if k:
                        field = kw.get("field", "any")
                        bad_keywords.setdefault(k, {}).setdefault(field, 0)
                        bad_keywords[k][field] += 1
                # Also track excluded keywords for bad
                for kw in json_loads(ex_json, []):
                    k = kw.get("keyword", "").lower().strip()
                    if k:
                        bad_keywords.setdefault(k, {}).setdefault("excluded", 0)
                        bad_keywords[k]["excluded"] += 1
            else:
                neutral_total += 1
                target = bucket_stats["neutral"]

            target.setdefault(bucket, 0)
            target[bucket] += 1

    reviewed = good_total + bad_total + neutral_total

    # ── Header ──
    console.print("\n[bold]Calibration Analysis[/bold]\n")
    console.print(
        f"  Reviewed: {reviewed}  "
        f"[green]Good: {good_total}[/green]  "
        f"[red]Bad: {bad_total}[/red]  "
        f"[dim]Neutral: {neutral_total}[/dim]"
    )

    # ── Top keywords ──
    _print_keyword_table(
        "Top Positive Keywords (field breakdown)",
        good_keywords,
        good_total,
        bad_keywords,
        bad_total,
        "boost",
    )
    _print_keyword_table(
        "Top Negative Keywords (field breakdown)",
        bad_keywords,
        bad_total,
        good_keywords,
        good_total,
        "exclude",
    )

    # ── Preset performance ──
    if preset_stats:
        pt = Table(title="Preset Performance")
        pt.add_column("Preset")
        pt.add_column("Reviewed", justify="right")
        pt.add_column("Good", justify="right")
        pt.add_column("Bad", justify="right")
        pt.add_column("Good Rate", justify="right")
        pt.add_column("Bad Rate", justify="right")
        for pname, ps in sorted(preset_stats.items(), key=lambda x: -x[1]["reviewed"]):
            g = ps["good"]
            b = ps["bad"]
            r = ps["reviewed"]
            g_rate = g / max(1, r)
            b_rate = b / max(1, r)
            pt.add_row(
                pname,
                str(r),
                str(g),
                str(b),
                f"{g_rate:.0%}",
                f"{b_rate:.0%}",
            )
        console.print(pt)

    # ── Score buckets ──
    bt = Table(title="Score Bucket Quality")
    bt.add_column("Bucket")
    bt.add_column("Good", justify="right")
    bt.add_column("Bad", justify="right")
    bt.add_column("Neutral", justify="right")
    bt.add_column("Total", justify="right")
    bt.add_column("Good Rate", justify="right")
    for lo, hi in SCORE_BUCKETS:
        label = f"{lo}-{hi}" if hi < 100 else "85-100"
        bkey = (lo, hi)
        g = bucket_stats["good"].get(bkey, 0)
        b = bucket_stats["bad"].get(bkey, 0)
        n = bucket_stats["neutral"].get(bkey, 0)
        t = g + b + n
        rate = f"{g / max(1, t):.0%}" if t else "-"
        bt.add_row(label, str(g), str(b), str(n), str(t), rate)
    console.print(bt)

    # ── Search term performance ──
    _print_query_performance(storage)

    return 0


def _bucket(score: int) -> tuple[int, int]:
    for lo, hi in SCORE_BUCKETS:
        if lo <= score <= hi:
            return (lo, hi)
    return (0, 24)


def _print_keyword_table(
    title: str,
    primary: dict[str, dict[str, int]],
    primary_total: int,
    secondary: dict[str, dict[str, int]],
    secondary_total: int,
    suggestion_type: str,
) -> None:
    if primary_total == 0:
        return
    entries = []
    for kw, fields in primary.items():
        total = sum(fields.values())
        other_total = sum(secondary.get(kw, {}).values())
        p_rate = total / max(1, primary_total)
        o_rate = other_total / max(1, secondary_total)
        lift = p_rate / max(0.001, o_rate)
        if total >= 2:
            entries.append((kw, total, other_total, lift, fields))

    if not entries:
        return

    entries.sort(key=lambda x: -x[3] if suggestion_type == "boost" else x[3])
    t = Table(title=title)
    t.add_column("Keyword")
    t.add_column("Count")
    t.add_column("Other")
    t.add_column("Lift")
    t.add_column("Fields")
    t.add_column("Suggestion")

    for kw, cnt, other, lift, fields in entries[:20]:
        field_str = ", ".join(f"{f}:{c}" for f, c in sorted(fields.items()))
        sug = ""
        if suggestion_type == "boost" and lift >= 2.0:
            sug = "boost"
        elif suggestion_type == "exclude" and lift <= 0.5 and cnt >= 3:
            sug = "exclude"
        t.add_row(kw, str(cnt), str(other), f"{lift:.1f}", field_str, sug)
    console.print(t)


def _print_query_performance(storage) -> None:
    """Show search term performance from search_runs + reviews."""
    with storage.connect() as conn:
        # Per-profile review stats
        profile_rows = conn.execute(
            """SELECT v.source_profile,
                      COUNT(v.id) total,
                      AVG(COALESCE(s.total_score,0)) avg_score,
                      SUM(CASE WHEN r.status IN ('interesting','applied','interview','offer') THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN r.status IN ('rejected','archived') THEN 1 ELSE 0 END) bad
               FROM vacancies v
               LEFT JOIN scores s ON s.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
               WHERE v.source_profile IS NOT NULL AND v.source_profile != ''
               GROUP BY v.source_profile"""
        ).fetchall()

        if not profile_rows:
            return

        # Per-query stats from search_runs
        query_rows = conn.execute(
            """SELECT profile_name, query, MAX(found_count) found, MAX(loaded_count) loaded
               FROM search_runs
               WHERE query IS NOT NULL AND query != ''
               GROUP BY profile_name, query
               ORDER BY profile_name"""
        ).fetchall()

    profile_map = {r["source_profile"]: dict(r) for r in profile_rows}

    # Build combined rows
    combined: list[dict] = []
    seen: set[str] = set()
    for qr in query_rows:
        pname = qr["profile_name"]
        pinfo = profile_map.get(pname, {})
        key = f"{pname}|{qr['query']}"
        if key in seen:
            continue
        seen.add(key)
        good = pinfo.get("good", 0)
        bad = pinfo.get("bad", 0)
        total = pinfo.get("total", 0)
        if total > 0:
            combined.append(
                {
                    "profile": pname,
                    "query": qr["query"],
                    "found": qr["found"] or 0,
                    "loaded": qr["loaded"] or 0,
                    "total": total,
                    "avg_score": round(pinfo.get("avg_score", 0), 1),
                    "good": good,
                    "bad": bad,
                    "suggestion": "deprioritize" if bad > good and bad >= 3 else "",
                }
            )

    # Also include profiles without queries
    for pname, pinfo in profile_map.items():
        key = f"{pname}|"
        if key not in seen and pinfo.get("total", 0) > 0:
            seen.add(key)
            combined.append(
                {
                    "profile": pname,
                    "query": "(profile-level)",
                    "found": 0,
                    "loaded": 0,
                    "total": pinfo.get("total", 0),
                    "avg_score": round(pinfo.get("avg_score", 0), 1),
                    "good": pinfo.get("good", 0),
                    "bad": pinfo.get("bad", 0),
                    "suggestion": "",
                }
            )

    combined.sort(key=lambda x: -x["bad"])

    if not combined:
        return

    t = Table(title="Search Term / Query Performance")
    t.add_column("Profile / Query")
    t.add_column("Found", justify="right")
    t.add_column("Total", justify="right")
    t.add_column("Avg Score", justify="right")
    t.add_column("Good", justify="right")
    t.add_column("Bad", justify="right")
    t.add_column("Suggestion")

    for c in combined[:20]:
        label = (
            f"{c['profile']} :: {c['query']}" if c["query"] != "(profile-level)" else c["profile"]
        )
        sug = c["suggestion"]
        sug_display = f"[yellow]{sug}[/yellow]" if sug else "-"
        t.add_row(
            label,
            str(c["found"]),
            str(c["total"]),
            str(c["avg_score"]),
            str(c["good"]),
            str(c["bad"]),
            sug_display,
        )
    console.print(t)


# ── Suggest ────────────────────────────────────────────────────────────────


def command_calibrate_suggest(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    suggestions = _load_suggestions()

    # ── Keyword suggestions (from score_details + reviews) ──
    good_kw: dict[str, dict[str, int]] = {}
    bad_kw: dict[str, dict[str, int]] = {}
    good_total = 0
    bad_total = 0

    with storage.connect() as conn:
        params = []
        preset_filter = ""
        if args.preset:
            preset_filter = "WHERE sd.preset_name = ?"
            params = [args.preset]

        rows = conn.execute(
            f"""SELECT sd.matched_keywords_json, sd.excluded_keywords_json,
                      COALESCE(r.status,'new') status
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
               {preset_filter}""",
            params,
        ).fetchall()

        for kw_json, ex_json, status in rows:
            keywords = json_loads(kw_json, [])
            excluded = json_loads(ex_json, [])
            if status in GOOD_STATUSES:
                good_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower().strip()
                    f = kw.get("field", "any")
                    if k:
                        good_kw.setdefault(k, {}).setdefault(f, 0)
                        good_kw[k][f] += 1
            elif status in BAD_STATUSES:
                bad_total += 1
                for kw in keywords:
                    k = kw.get("keyword", "").lower().strip()
                    f = kw.get("field", "any")
                    if k:
                        bad_kw.setdefault(k, {}).setdefault(f, 0)
                        bad_kw[k][f] += 1
                for kw in excluded:
                    k = kw.get("keyword", "").lower().strip()
                    if k:
                        bad_kw.setdefault(k, {}).setdefault("excluded", 0)
                        bad_kw[k]["excluded"] += 1

    new_count = 0
    preset_label = args.preset or "all"

    # ── Exclude suggestions ──
    for kw, fields in sorted(bad_kw.items(), key=lambda x: -sum(x[1].values())):
        total_bad = sum(fields.values())
        total_good = sum(good_kw.get(kw, {}).values())
        b_rate = total_bad / max(1, bad_total)
        if b_rate >= 0.3 and total_good <= 1:
            sid = _add_suggestion(
                suggestions,
                preset_label,
                "add_exclude",
                kw,
                reason=f"Appears in {total_bad}/{bad_total} rejected ({b_rate:.0%})",
                evidence={
                    "good_count": total_good,
                    "bad_count": total_bad,
                    "bad_rate": round(b_rate, 2),
                },
                target_path="exclude.any",
            )
            if sid:
                new_count += 1
            if new_count >= 10:
                break

    # ── Boost suggestions ──
    for kw, fields in sorted(good_kw.items(), key=lambda x: -sum(x[1].values())):
        total_good = sum(fields.values())
        total_bad = sum(bad_kw.get(kw, {}).values())
        g_rate = total_good / max(1, good_total)
        if g_rate >= 0.3 and total_bad <= 2:
            sid = _add_suggestion(
                suggestions,
                preset_label,
                "add_boost",
                kw,
                reason=f"Appears in {total_good}/{good_total} accepted ({g_rate:.0%})",
                evidence={
                    "good_count": total_good,
                    "bad_count": total_bad,
                    "good_rate": round(g_rate, 2),
                },
                target_path="boost.skills",
                proposed_value=10,
            )
            if sid:
                new_count += 1
            if new_count >= 20:
                break

    # ── Search term suggestions ──
    new_count += _suggest_query_terms(storage, suggestions, preset_label)

    _save_suggestions(suggestions)
    console.print(f"[green]{new_count} new suggestions saved to {SUGGESTIONS_PATH}[/green]")

    if suggestions:
        pending = [s for s in suggestions if s.get("status", "pending") == "pending"]
        if pending:
            t = Table(title="Pending Suggestions")
            t.add_column("ID")
            t.add_column("Type")
            t.add_column("Keyword / Term")
            t.add_column("Reason")
            for s in sorted(pending, key=lambda x: x.get("created_at", ""), reverse=True)[:20]:
                t.add_row(
                    s["id"],
                    s["type"],
                    s.get("keyword") or s.get("search_term", ""),
                    s["reason"][:60],
                )
            console.print(t)

    return 0


def _suggest_query_terms(storage, suggestions: list[dict], preset_label: str) -> int:
    """Generate search-term suggestions from query performance."""
    new_count = 0

    with storage.connect() as conn:
        qrows = conn.execute(
            """SELECT profile_name, query, MAX(found_count) found
               FROM search_runs
               WHERE query IS NOT NULL AND query != ''
               GROUP BY profile_name, query"""
        ).fetchall()

        prows = conn.execute(
            """SELECT v.source_profile,
                      COUNT(v.id) total,
                      SUM(CASE WHEN r.status IN ('interesting','applied','interview','offer') THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN r.status IN ('rejected','archived') THEN 1 ELSE 0 END) bad
               FROM vacancies v
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
               WHERE v.source_profile IS NOT NULL AND v.source_profile != ''
               GROUP BY v.source_profile"""
        ).fetchall()

    pmap = {r["source_profile"]: dict(r) for r in prows}

    for qr in qrows:
        pname = qr["profile_name"]
        pinfo = pmap.get(pname, {})
        good = pinfo.get("good", 0)
        bad = pinfo.get("bad", 0)
        query = qr["query"]

        if bad > good and bad >= 3:
            sid = _add_suggestion(
                suggestions,
                preset_label if preset_label != "all" else pname,
                "remove_search_term",
                query,
                reason=f"Query has {bad} bad / {good} good outcomes, found={qr['found']}",
                evidence={"good": good, "bad": bad, "found": qr["found"]},
                target_path="search_terms",
            )
            if sid:
                new_count += 1
        elif bad >= 2 and good >= bad:
            sid = _add_suggestion(
                suggestions,
                preset_label if preset_label != "all" else pname,
                "lower_search_term_priority",
                query,
                reason=f"Query has mixed results: {good} good / {bad} bad",
                evidence={"good": good, "bad": bad, "found": qr["found"]},
                target_path="search_terms",
            )
            if sid:
                new_count += 1

    return new_count


# ── Apply ──────────────────────────────────────────────────────────────────


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

    if target.get("status", "pending") == "applied":
        console.print(f"[yellow]Suggestion '{args.suggestion_id}' already applied.[/yellow]")
        return 0

    console.print(
        f"\nSuggestion: {target['type']} '{target.get('keyword') or target.get('search_term', '')}'"
    )
    console.print(f"  Preset: {target['preset']}")
    console.print(f"  Target: {target.get('target_path', '')}")
    console.print(f"  Reason: {target['reason']}")

    if not args.yes:
        if not Confirm.ask("Apply this suggestion?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    preset_name = target["preset"]
    typ = target["type"]
    keyword = target.get("keyword") or target.get("search_term", "")
    target_path = target.get("target_path", "")

    try:
        from shutil import copy2

        path = Path("config/search_presets.yaml")
        if not path.exists():
            console.print("[red]search_presets.yaml not found.[/red]")
            return 1

        # Backup
        backup_dir = Path("config/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"search_presets_{ts}.yaml"
        copy2(path, backup_path)

        with open(path, "r", encoding="utf-8") as f:
            before_raw = f.read()
            data = yaml.safe_load(f) or {}

        presets = data.setdefault("presets", {})
        preset = presets.get(preset_name)
        if preset is None:
            console.print(f"[red]Preset '{preset_name}' not found in YAML.[/red]")
            return 1

        _apply_suggestion(preset, typ, keyword, target_path)

        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Show diff-like output
        with open(path, "r", encoding="utf-8") as f:
            after_raw = f.read()

        console.print("\n[bold]Changes:[/bold]")
        console.print(f"[dim]Backup: {backup_path}[/dim]")
        if before_raw != after_raw:
            console.print("[yellow]YAML modified. Use git diff to review.[/yellow]")
        else:
            console.print("[dim]No structural change (keyword may already exist).[/dim]")

        # Mark suggestion as applied
        target["status"] = "applied"
        target["applied_at"] = datetime.now(timezone.utc).isoformat()
        _save_suggestions(suggestions)

    except Exception as exc:
        console.print(f"[red]Failed to apply: {exc}[/red]")
        return 1

    console.print(f"[green]Applied suggestion '{args.suggestion_id}'.[/green]")
    return 0


def _apply_suggestion(preset: dict, typ: str, keyword: str, target_path: str) -> None:
    """Apply a suggestion to a preset dict (mutates in place)."""
    if typ == "add_exclude":
        preset.setdefault("exclude", {}).setdefault("any", [])
        if keyword not in preset["exclude"]["any"]:
            preset["exclude"]["any"].append(keyword)
    elif typ == "add_title_exclude":
        preset.setdefault("exclude", {}).setdefault("title", [])
        if keyword not in preset["exclude"]["title"]:
            preset["exclude"]["title"].append(keyword)
    elif typ == "add_title_include":
        preset.setdefault("include", {}).setdefault("title", [])
        if keyword not in preset["include"]["title"]:
            preset["include"]["title"].append(keyword)
    elif typ == "add_boost":
        preset.setdefault("boost", {}).setdefault("skills", {})
        preset["boost"]["skills"][keyword] = 10
    elif typ == "add_penalty":
        preset.setdefault("penalties", {}).setdefault("skills", {})
        preset["penalties"]["skills"][keyword] = 15
    elif typ == "remove_search_term":
        terms = preset.get("search_terms", [])
        if keyword in terms:
            terms.remove(keyword)
    elif typ == "lower_search_term_priority":
        terms = preset.get("search_terms", [])
        if keyword in terms:
            terms.remove(keyword)
            terms.append(keyword)
    else:
        raise ValueError(f"Unknown suggestion type: {typ}")


# ── Dismiss ────────────────────────────────────────────────────────────────


def command_calibrate_dismiss(args: argparse.Namespace) -> int:
    suggestions = _load_suggestions()
    target = None
    for s in suggestions:
        if s["id"] == args.suggestion_id:
            target = s
            break
    if target is None:
        console.print(f"[red]Suggestion '{args.suggestion_id}' not found.[/red]")
        return 1
    target["status"] = "dismissed"
    _save_suggestions(suggestions)
    console.print(f"[yellow]Dismissed suggestion '{args.suggestion_id}'.[/yellow]")
    return 0


# ── Export ──────────────────────────────────────────────────────────────────


def command_calibrate_export(_: argparse.Namespace) -> int:
    storage, _, _ = _services()
    suggestions = _load_suggestions()
    out = Path("exports")

    # ── JSON ──
    with open(out / "calibration_suggestions.json", "w", encoding="utf-8") as f:
        json.dump(suggestions, f, ensure_ascii=False, indent=2)
    console.print(f"[green]calibration_suggestions.json ({len(suggestions)} suggestions)[/green]")

    # ── CSV ──
    def _write_csv(h):
        w = csv.writer(h)
        w.writerow(
            ["id", "preset", "type", "keyword", "target_path", "status", "reason", "created_at"]
        )
        for s in suggestions:
            w.writerow(
                [
                    s["id"],
                    s.get("preset", ""),
                    s.get("type", ""),
                    s.get("keyword") or s.get("search_term", ""),
                    s.get("target_path", ""),
                    s.get("status", "pending"),
                    s.get("reason", ""),
                    s.get("created_at", ""),
                ]
            )

    tp = out / "calibration_keywords.csv"
    tp.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=tp.parent
    )
    try:
        _write_csv(tmp)
        tmp.close()
        os.replace(tmp.name, tp)
    finally:
        if not tmp.closed:
            tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
    console.print("[green]calibration_keywords.csv[/green]")

    # ── HTML ──
    _export_html_report(storage, suggestions, out)
    console.print("[green]calibration_report.html[/green]")
    return 0


def _export_html_report(storage, suggestions: list[dict], out: Path) -> None:
    """Generate rich HTML calibration report."""

    # Summary counts
    pending = sum(1 for s in suggestions if s.get("status", "pending") == "pending")
    applied = sum(1 for s in suggestions if s.get("status") == "applied")
    dismissed = sum(1 for s in suggestions if s.get("status") == "dismissed")
    by_type: dict[str, int] = {}
    for s in suggestions:
        t = s.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1

    # Summary cards
    cards = f"""
    <div class="row">
      <div class="stat"><strong>{len(suggestions)}</strong><span>Total</span></div>
      <div class="stat"><strong>{pending}</strong><span>Pending</span></div>
      <div class="stat"><strong>{applied}</strong><span>Applied</span></div>
      <div class="stat"><strong>{dismissed}</strong><span>Dismissed</span></div>
    </div>"""

    # Type breakdown
    type_rows = "".join(
        f"<tr><td>{t}</td><td>{c}</td></tr>"
        for t, c in sorted(by_type.items(), key=lambda x: -x[1])
    )

    # Suggestions table — pending first
    srows = ""
    for s in sorted(
        suggestions,
        key=lambda x: (x.get("status") != "pending", x.get("created_at", "")),
        reverse=False,
    ):
        status_cls = f"status-{s.get('status', 'pending')}"
        srows += f"""<tr class="{status_cls}">
          <td>{s["id"]}</td><td>{s.get("type", "")}</td>
          <td>{s.get("keyword") or s.get("search_term", "")}</td>
          <td>{s.get("preset", "")}</td><td>{s.get("target_path", "")}</td>
          <td>{s.get("status", "pending")}</td>
          <td>{s.get("reason", "")[:80]}</td>
        </tr>"""

    # Keyword lift table (simplified from analyze logic)
    with storage.connect() as conn:
        kw_rows = conn.execute(
            """SELECT sd.matched_keywords_json, COALESCE(r.status,'new') status
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id = v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id"""
        ).fetchall()

    good_kw: dict[str, int] = {}
    bad_kw: dict[str, int] = {}
    good_t = 0
    bad_t = 0
    for kw_json, status in kw_rows:
        for kw in json_loads(kw_json, []):
            k = kw.get("keyword", "").lower()
            if not k:
                continue
            if status in GOOD_STATUSES:
                good_t += 1
                good_kw[k] = good_kw.get(k, 0) + 1
            elif status in BAD_STATUSES:
                bad_t += 1
                bad_kw[k] = bad_kw.get(k, 0) + 1

    kw_lift_rows = ""
    all_kw = set(good_kw) | set(bad_kw)
    entries = []
    for kw in all_kw:
        g = good_kw.get(kw, 0)
        b = bad_kw.get(kw, 0)
        if g >= 2 or b >= 2:
            g_rate = g / max(1, good_t)
            b_rate = b / max(1, bad_t)
            lift = g_rate / max(0.001, b_rate)
            entries.append((kw, g, b, round(lift, 1)))
    entries.sort(key=lambda x: -x[3])
    for kw, g, b, lift in entries[:30]:
        kw_lift_rows += f"<tr><td>{kw}</td><td>{g}</td><td>{b}</td><td>{lift:.1f}</td></tr>"

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibration Report</title>
<style>
:root{{--bg:#0b1020;--panel:#141b2d;--line:#26324d;--text:#e8edf7;--muted:#9ba8bd;--accent:#67e8f9}}
body{{background:var(--bg);color:var(--text);font:14px system-ui;max-width:1100px;margin:20px auto;padding:0 20px}}
h1{{color:var(--accent);font-size:24px}} h2{{color:#9bf6e8;font-size:18px;margin-top:30px;border-bottom:1px solid var(--line);padding-bottom:8px}}
.row{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.stat{{flex:1;min-width:100px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center}}
.stat strong{{display:block;font-size:24px;color:var(--accent)}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line)}}
th{{color:#fde68a}} .status-pending{{background:#2a3510}} .status-applied{{background:#102a1c}} .status-dismissed{{background:#2a1010}}
</style></head><body>
<h1>Calibration Report</h1>
{cards}

<h2>Suggestions by Type</h2>
<table><tr><th>Type</th><th>Count</th></tr>{type_rows}</table>

<h2>All Suggestions</h2>
<table><tr><th>ID</th><th>Type</th><th>Keyword</th><th>Preset</th><th>Target</th><th>Status</th><th>Reason</th></tr>{srows}</table>

<h2>Keyword Lift Table</h2>
<table><tr><th>Keyword</th><th>Good</th><th>Bad</th><th>Lift</th></tr>{kw_lift_rows}</table>
</body></html>"""

    (out / "calibration_report.html").write_text(html, encoding="utf-8")
