"""Search Lab — query planner and analytics for search terms.

Usage:
  python -m src.main search-lab terms --preset NAME
  python -m src.main search-lab suggest-terms --preset NAME
  python -m src.main search-lab compare --preset A --preset B
  python -m src.main search-lab dry-plan --preset NAME
  python -m src.main search-lab export
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..search_presets import get_preset, list_presets
from ..storage import Storage
from ..utils import json_dumps

console = Console()


def _get_storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


# ── Recommendation logic ────────────────────────────────────────────────────


def _recommend(term_row: dict[str, Any]) -> tuple[str, str]:
    """Return (label, reason) recommendation for a search term."""
    avg = term_row.get("avg_score") or 0
    strong = term_row.get("strong_count") or 0
    rejected = term_row.get("rejected_count") or 0
    good = term_row.get("good_outcome_count") or 0
    found = term_row.get("max_found") or 0
    vac_count = term_row.get("vacancy_count") or 0

    if good >= 3 and avg >= 75:
        return ("keep", "High conversion: many applied/interview/offer outcomes")
    if strong >= 5 and avg >= 80:
        return ("keep", "Many strong matches with high average score")
    if rejected > strong * 2 and vac_count > 5:
        return ("remove", f"High rejection rate: {rejected} rejected vs {strong} strong matches")
    if found > 50 and vac_count == 0:
        return ("refine", "High find count but no vacancies stored — check filtering")
    if avg < 50 and vac_count > 3:
        return ("refine", f"Low average score ({avg}) — consider narrowing the term")
    if found == 0 and vac_count == 0:
        return ("remove", "No results found — remove or replace")
    if strong >= 1:
        return ("keep", f"{strong} strong matches, {good} good outcomes")
    return ("refine", "Mixed results — review manually")


# ── terms ────────────────────────────────────────────────────────────────────


def command_search_lab_terms(args: argparse.Namespace) -> int:
    """Show per-search-term performance analytics."""
    storage = _get_storage()
    preset_name = args.preset

    preset = get_preset(preset_name)
    if preset is None:
        console.print(f"[red]Preset '{preset_name}' not found.[/red]")
        return 1

    terms = preset.get("search_terms", [])
    if not terms:
        console.print(f"[yellow]Preset '{preset_name}' has no search_terms.[/yellow]")
        return 0

    perf = storage.search_term_performance(preset_name)

    # Build lookup
    perf_map: dict[str, dict[str, Any]] = {r["term"]: r for r in perf}

    table = Table(title=f"Search Term Performance — {preset_name}")
    columns = [
        ("Term", "term"),
        ("Runs", "total_runs"),
        ("Found", "max_found"),
        ("Vacancies", "vacancy_count"),
        ("Avg Score", "avg_score"),
        ("Strong", "strong_count"),
        ("Queue", "queue_count"),
        ("Rejected", "rejected_count"),
        ("Good ✓", "good_outcome_count"),
        ("Recommendation", None),
    ]
    for col_name, _ in columns:
        table.add_column(col_name)

    total_vacancies = 0
    total_strong = 0

    for term in terms:
        row = perf_map.get(term, {})
        rec_label, rec_reason = _recommend(row)
        color = {"keep": "green", "refine": "yellow", "remove": "red"}.get(rec_label, "white")

        table.add_row(
            term,
            str(row.get("total_runs", 0)),
            str(row.get("max_found", 0)),
            str(row.get("vacancy_count", 0)),
            str(row.get("avg_score", 0)),
            str(row.get("strong_count", 0)),
            str(row.get("queue_count", 0)),
            str(row.get("rejected_count", 0)),
            str(row.get("good_outcome_count", 0)),
            f"[{color}]{rec_label.upper()}[/{color}] — {rec_reason}",
        )
        total_vacancies += row.get("vacancy_count", 0)
        total_strong += row.get("strong_count", 0)

    console.print(table)
    console.print(
        f"\n[bold]Total:[/bold] {total_vacancies} vacancies, "
        f"{total_strong} strong matches across {len(terms)} terms"
    )

    return 0


# ── suggest-terms ────────────────────────────────────────────────────────────


def _multi_word_phrases(words: list[str], max_phrase: int = 3) -> list[str]:
    """Generate multi-word phrases from title words that appear together."""
    phrases: list[str] = []
    for i in range(len(words) - 1):
        for n in range(2, min(max_phrase + 1, len(words) - i + 1)):
            phrase = " ".join(words[i : i + n])
            if len(phrase) > 4:
                phrases.append(phrase)
    return phrases


def command_search_lab_suggest_terms(args: argparse.Namespace) -> int:
    """Suggest new search terms based on high-quality keyword analysis."""
    storage = _get_storage()
    preset_name = args.preset

    preset = get_preset(preset_name)
    if preset is None:
        console.print(f"[red]Preset '{preset_name}' not found.[/red]")
        return 1

    existing_terms = set(t.lower() for t in preset.get("search_terms", []))

    # Get high-quality keywords
    keywords = storage.high_quality_keywords(preset_name, min_score=70)

    if not keywords:
        console.print(f"[yellow]No high-scoring vacancies for '{preset_name}'.[/yellow]")
        console.print("[dim]Run a search first to populate data.[/dim]")
        return 0

    existing_lower = {t.lower() for t in existing_terms}

    table = Table(title=f"Suggested Search Terms — {preset_name}")
    table.add_column("Suggested Term")
    table.add_column("Evidence")
    table.add_column("Source")

    suggested_count = 0
    for kw in keywords:
        term = kw["keyword"]
        if term.lower() in existing_lower:
            continue
        if len(term) < 4:
            continue

        evidence = f"Appears in {kw['count']} high-score vacancies"
        table.add_row(term, evidence, kw["source"])
        suggested_count += 1
        if suggested_count >= 15:
            break

    if suggested_count == 0:
        console.print("[green]All high-quality keywords are already in search terms.[/green]")
        return 0

    console.print(table)
    console.print(
        f"\n[dim]{suggested_count} suggested terms (existing: {len(existing_terms)}).[/dim]"
    )
    console.print(
        '[dim]Add manually: python -m src.main presets add-term {preset} "new term"[/dim]'
    )
    return 0


# ── compare ──────────────────────────────────────────────────────────────────


def command_search_lab_compare(args: argparse.Namespace) -> int:
    """Compare two presets side by side."""
    preset_a_name = getattr(args, "preset_a", None)
    preset_b_name = getattr(args, "preset_b", None)

    # Support both --preset A --preset B (repeated) and --preset-a --preset-b
    if preset_a_name is None or preset_b_name is None:
        console.print("[red]Specify two presets: --preset-a NAME --preset-b NAME[/red]")
        return 1

    storage = _get_storage()
    overlap = storage.preset_overlap(preset_a_name, preset_b_name)

    # Summary table
    summary = Table(title=f"Preset Comparison: {preset_a_name} vs {preset_b_name}")
    summary.add_column("Metric")
    summary.add_column(preset_a_name)
    summary.add_column(preset_b_name)

    summary.add_row("Total vacancies", str(overlap["total_a"]), str(overlap["total_b"]))
    summary.add_row(
        "Overlapping vacancies",
        str(overlap["overlap"]),
        str(overlap["overlap"]),
    )
    summary.add_row("Unique vacancies", str(overlap["unique_a"]), str(overlap["unique_b"]))
    summary.add_row("Avg score", str(overlap["avg_score_a"]), str(overlap["avg_score_b"]))

    console.print(summary)

    # Top keywords
    kw_table = Table(title="Top Keywords")
    kw_table.add_column(f"{preset_a_name} Keywords")
    kw_table.add_column(f"{preset_b_name} Keywords")

    top_a = overlap["top_keywords"].get("a", [])
    top_b = overlap["top_keywords"].get("b", [])
    for i in range(max(len(top_a), len(top_b))):
        a_str = f"{top_a[i][0]} ({top_a[i][1]})" if i < len(top_a) else ""
        b_str = f"{top_b[i][0]} ({top_b[i][1]})" if i < len(top_b) else ""
        kw_table.add_row(a_str, b_str)

    console.print(kw_table)

    # Recommendation
    if overlap["overlap"] > max(overlap["total_a"], overlap["total_b"]) * 0.7:
        console.print(
            "\n[yellow]High overlap (>70%). Consider merging or differentiating presets.[/yellow]"
        )
    elif overlap["overlap"] == 0:
        console.print("\n[green]No overlap — presets serve different markets.[/green]")
    else:
        overlap_pct = (
            overlap["overlap"] / max(overlap["total_a"], overlap["total_b"]) * 100
            if max(overlap["total_a"], overlap["total_b"]) > 0
            else 0
        )
        console.print(f"\n[dim]Overlap: {overlap_pct:.0f}% — moderate differentiation.[/dim]")

    return 0


# ── dry-plan ─────────────────────────────────────────────────────────────────


def command_search_lab_dry_plan(args: argparse.Namespace) -> int:
    """Show what a search run would do without making API calls."""
    preset_name = args.preset

    preset = get_preset(preset_name)
    if preset is None:
        console.print(f"[red]Preset '{preset_name}' not found.[/red]")
        return 1

    search_terms = preset.get("search_terms", [])
    remote_only = preset.get("remote_only", True)
    areas = preset.get("areas", [])
    schedule = preset.get("schedule", [])
    experience = preset.get("experience", [])

    # Estimate API requests:
    # - 1 request per search term (per page, but minimum 1)
    # - 1 detail request per vacancy loaded (estimated from history)
    storage = _get_storage()

    # Historical found/loaded ratio
    with storage.connect() as conn:
        hist = conn.execute(
            """SELECT AVG(CAST(loaded_count AS REAL) / NULLIF(found_count, 0)) ratio
               FROM search_runs
               WHERE profile_name = ? AND found_count > 0""",
            (preset_name,),
        ).fetchone()
    load_ratio = hist["ratio"] if hist and hist["ratio"] else 0.5

    with storage.connect() as conn:
        avg_found_row = conn.execute(
            """SELECT ROUND(AVG(found_count), 0) avg_found
               FROM search_runs
               WHERE profile_name = ? AND found_count > 0""",
            (preset_name,),
        ).fetchone()
    avg_found = avg_found_row["avg_found"] if avg_found_row and avg_found_row["avg_found"] else 50

    estimated_search_requests = len(search_terms)
    estimated_found = int(avg_found * len(search_terms)) if avg_found else 0
    estimated_loaded = int(estimated_found * load_ratio)
    estimated_detail_requests = estimated_loaded
    total_api_requests = estimated_search_requests + estimated_detail_requests

    # Noise estimate based on historical rejection rate
    perf = storage.search_term_performance(preset_name)
    noisy_terms = [r for r in perf if _recommend(r)[0] in ("refine", "remove")]
    noise_estimate = (
        f"{len(noisy_terms)}/{len(search_terms)} terms noisy" if search_terms else "n/a"
    )

    # Build plan
    console.print(
        Panel.fit(
            f"[bold cyan]Search Dry Plan — {preset_name}[/bold cyan]",
            border_style="cyan",
        )
    )

    table = Table(title="Plan Details")
    table.add_column("Parameter")
    table.add_column("Value")

    table.add_row("Search terms", str(len(search_terms)))
    table.add_row(
        "Terms list", ", ".join(search_terms[:5]) + ("..." if len(search_terms) > 5 else "")
    )
    table.add_row("Remote only", "yes" if remote_only else "no")
    table.add_row("Areas", ", ".join(areas) if areas else "all")
    table.add_row("Schedule", ", ".join(schedule) if schedule else "any")
    table.add_row("Experience", ", ".join(experience) if experience else "any")
    table.add_row("Est. search requests", str(estimated_search_requests))
    table.add_row("Est. found vacancies", str(estimated_found))
    table.add_row("Est. detail requests", str(estimated_detail_requests))
    table.add_row("Est. total API calls", str(total_api_requests))
    table.add_row("Historical load ratio", f"{load_ratio:.0%}")
    table.add_row("Noise estimate", noise_estimate)

    console.print(table)

    if total_api_requests > 200:
        console.print(
            f"\n[yellow]⚠ {total_api_requests} estimated API calls — consider smoke mode first.[/yellow]"
        )
    else:
        console.print(f"\n[green]✓ {total_api_requests} API calls — within safe range.[/green]")

    console.print(
        "\n[dim]Run: python -m src.main search --preset {preset} --dry-run --mode smoke[/dim]"
    )
    return 0


# ── export ───────────────────────────────────────────────────────────────────


def _export_html(storage: Storage, out_dir: Path) -> Path:
    """Generate search_lab_report.html."""
    presets = list_presets()
    rows: list[str] = []

    for p in presets[:10]:  # limit to 10 presets
        pname = p.get("_name", "unknown")
        perf = storage.search_term_performance(pname)
        if not perf:
            continue

        cards = []
        for r in perf[:20]:
            rec_label, _ = _recommend(r)
            color = {"keep": "#4ade80", "refine": "#facc15", "remove": "#f87171"}.get(
                rec_label, "#fff"
            )
            cards.append(
                f"<tr><td>{r['term']}</td>"
                f"<td>{r['vacancy_count']}</td>"
                f"<td>{r['avg_score']}</td>"
                f"<td>{r['strong_count']}</td>"
                f"<td style='color:{color}'>{rec_label.upper()}</td></tr>"
            )

        rows.append(
            f"<h2>{pname}</h2>"
            f"<table><tr><th>Term</th><th>Vacancies</th><th>Avg</th>"
            f"<th>Strong</th><th>Rec</th></tr>"
            f"{''.join(cards)}</table>"
        )

    html = f"""<!doctype html><html><head><meta charset=utf-8>
<title>CareerSignal HH — Search Lab</title>
<style>
body{{background:#0b1020;color:#e8edf7;font:14px system-ui;max-width:900px;margin:20px auto;padding:20px}}
h1{{color:#67e8f9}}h2{{color:#9bf6e8;margin-top:24px;border-bottom:1px solid #26324d;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{padding:6px 10px;text-align:left;border-bottom:1px solid #26324d}}
th{{color:#fde68a}}
</style></head><body>
<h1>CareerSignal HH — Search Lab</h1>
<p>Generated {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
{"".join(rows)}
</body></html>"""

    path = out_dir / "search_lab_report.html"
    path.write_text(html, encoding="utf-8")
    return path


def _export_terms_csv(storage: Storage, out_dir: Path) -> Path:
    """Generate search_terms.csv with all term performance data."""
    presets = list_presets()
    lines = ["preset,term,runs,found,vacancies,avg_score,strong,queue,rejected,good,recommendation"]

    for p in presets:
        pname = p.get("_name", "unknown")
        for r in storage.search_term_performance(pname):
            rec, _ = _recommend(r)
            lines.append(
                f"{pname},{r['term']},{r['total_runs']},{r['max_found']},"
                f"{r['vacancy_count']},{r['avg_score']},{r['strong_count']},"
                f"{r['queue_count']},{r['rejected_count']},{r['good_outcome_count']},"
                f"{rec}"
            )

    path = out_dir / "search_terms.csv"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _export_comparison_json(storage: Storage, out_dir: Path) -> Path:
    """Generate preset_comparison.json for all preset pairs."""
    presets = list_presets()
    comparisons: list[dict[str, Any]] = []

    for i, pa in enumerate(presets):
        for pb in presets[i + 1 :]:
            aname = pa.get("_name", "?")
            bname = pb.get("_name", "?")
            try:
                overlap = storage.preset_overlap(aname, bname)
                comparisons.append(
                    {
                        "preset_a": aname,
                        "preset_b": bname,
                        "total_a": overlap["total_a"],
                        "total_b": overlap["total_b"],
                        "overlap": overlap["overlap"],
                        "avg_score_a": overlap["avg_score_a"],
                        "avg_score_b": overlap["avg_score_b"],
                    }
                )
            except Exception:
                pass

    path = out_dir / "preset_comparison.json"
    path.write_text(json_dumps(comparisons), encoding="utf-8")
    return path


def command_search_lab_export(_: argparse.Namespace) -> int:
    """Export search lab reports."""
    storage = _get_storage()
    out_dir = Path("exports")
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = _export_html(storage, out_dir)
    csv_path = _export_terms_csv(storage, out_dir)
    json_path = _export_comparison_json(storage, out_dir)

    console.print(f"[green]✓[/green] {html_path}")
    console.print(f"[green]✓[/green] {csv_path}")
    console.print(f"[green]✓[/green] {json_path}")
    return 0
