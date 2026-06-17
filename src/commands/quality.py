from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import _services
from ..data_quality import find_duplicates, normalize_employer_name

console = Console()


def command_quality_duplicates(_: argparse.Namespace) -> int:
    try:
        storage, _, _ = _services()
    except Exception as exc:
        console.print(f"[red]Failed to initialise services: {exc}[/red]")
        return 1
    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    if not clusters:
        console.print("[green]No duplicates found.[/green]")
        return 0

    table = Table(title="Duplicate Clusters")
    table.add_column("Cluster")
    table.add_column("Reason")
    table.add_column("Count")
    table.add_column("Top Vacancy")
    for c in clusters[:20]:
        vs = c["vacancies"]
        top = max(vs, key=lambda v: v.get("total_score", 0))
        table.add_row(
            c["cluster_id"],
            c["reason"],
            str(len(vs)),
            f"{top.get('name', '?')} ({top.get('employer_name', '?')}) - score {top.get('total_score', 0)}",
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(clusters)} clusters, {sum(len(c['vacancies']) for c in clusters)} total duplicates[/dim]"
    )
    return 0


def command_quality_cluster(_: argparse.Namespace) -> int:
    try:
        storage, _, _ = _services()
    except Exception as exc:
        console.print(f"[red]Failed to initialise services: {exc}[/red]")
        return 1
    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    if not clusters:
        console.print("[green]No clusters to create.[/green]")
        return 0

    # Save to SQLite
    storage.replace_vacancy_clusters(clusters)

    # Compute and save employer aliases
    norm_emps: dict[str, list[str]] = {}
    for r in rows:
        raw = (r.get("employer_name") or "").strip()
        if raw:
            norm = normalize_employer_name(raw)
            norm_emps.setdefault(norm, []).append(raw)
    aliases = {k: list(set(v)) for k, v in norm_emps.items() if len(set(v)) > 1}
    if aliases:
        storage.replace_employer_aliases(aliases)

    dup_vacancies = sum(len(c["vacancy_ids"]) for c in clusters)
    console.print(
        f"[green]Saved {len(clusters)} clusters ({dup_vacancies} vacancies) to SQLite[/green]"
    )
    console.print(f"[green]Saved {len(aliases)} employer alias groups to SQLite[/green]")

    # Also save clusters to JSON as secondary artifact
    try:
        out = Path("data/vacancy_clusters.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        cluster_data = []
        for c in clusters:
            cluster_data.append(
                {
                    "cluster_id": c["cluster_id"],
                    "reason": c["reason"],
                    "vacancy_ids": c["vacancy_ids"],
                    "similarity": c["similarity"],
                }
            )
        out.write_text(json.dumps(cluster_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"[dim]Also saved {len(cluster_data)} clusters to {out}[/dim]")
    except OSError as exc:
        console.print(f"[red]Failed to save clusters JSON: {exc}[/red]")
    return 0


def command_quality_report(_: argparse.Namespace) -> int:
    try:
        storage, _, _ = _services()
    except Exception as exc:
        console.print(f"[red]Failed to initialise services: {exc}[/red]")
        return 1
    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    table = Table(title="Data Quality Report")
    table.add_column("Metric")
    table.add_column("Value")

    total = len(rows)
    dup_url = sum(1 for c in clusters if c["reason"] == "same_url")
    dup_emp = sum(1 for c in clusters if c["reason"] != "same_url")
    dup_total = sum(len(c["vacancies"]) for c in clusters)
    missing_desc = sum(1 for r in rows if not (r.get("description_text") or "").strip())
    missing_scores = sum(1 for r in rows if not r.get("total_score"))
    stale = sum(1 for r in rows if (r.get("last_seen_at") or "") < "2026-06-01")

    # Employer aliases
    norm_emps: dict[str, list[str]] = {}
    for r in rows:
        raw = (r.get("employer_name") or "").strip()
        if raw:
            norm = normalize_employer_name(raw)
            norm_emps.setdefault(norm, []).append(raw)
    aliases = {k: list(set(v)) for k, v in norm_emps.items() if len(set(v)) > 1}

    table.add_row("Total vacancies", str(total))
    table.add_row("Duplicate URL clusters", str(dup_url))
    table.add_row("Similar employer+title clusters", str(dup_emp))
    table.add_row("Total duplicates", str(dup_total))
    table.add_row("Missing descriptions", str(missing_desc))
    table.add_row("Missing scores", str(missing_scores))
    table.add_row("Stale (before 2026-06)", str(stale))
    table.add_row("Employer aliases", str(len(aliases)))

    console.print(table)

    if aliases:
        at = Table(title="Employer Aliases")
        at.add_column("Canonical")
        at.add_column("Variants")
        for norm, variants in sorted(aliases.items())[:10]:
            at.add_row(norm, "\n".join(variants))
        console.print(at)

    return 0


def command_quality_export(_: argparse.Namespace) -> int:
    try:
        storage, _, _ = _services()
    except Exception as exc:
        console.print(f"[red]Failed to initialise services: {exc}[/red]")
        return 1
    rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(rows)

    out = Path("exports")

    # Duplicates CSV
    def _write_dup(h):
        w = csv.writer(h)
        w.writerow(["cluster_id", "reason", "vacancy_count", "vacancy_ids"])
        for c in clusters:
            w.writerow(
                [c["cluster_id"], c["reason"], len(c["vacancy_ids"]), ";".join(c["vacancy_ids"])]
            )

    tp = out / "duplicates.csv"
    try:
        tp.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False, dir=tp.parent
        ) as h:
            _write_dup(h)
            os.replace(h.name, tp)
        console.print(f"[green]duplicates.csv ({len(clusters)} clusters)[/green]")
    except OSError as exc:
        console.print(f"[red]Failed to write duplicates.csv: {exc}[/red]")

    # Employer aliases CSV
    norm_emps: dict[str, list[str]] = {}
    for r in rows:
        raw = (r.get("employer_name") or "").strip()
        if raw:
            norm = normalize_employer_name(raw)
            norm_emps.setdefault(norm, []).append(raw)
    aliases = {k: list(set(v)) for k, v in norm_emps.items() if len(set(v)) > 1}

    def _write_emp(h):
        w = csv.writer(h)
        w.writerow(["canonical", "variants"])
        for k, v in sorted(aliases.items()):
            w.writerow([k, "; ".join(v)])

    tp2 = out / "employer_aliases.csv"
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", delete=False, dir=tp2.parent
        ) as h:
            _write_emp(h)
            os.replace(h.name, tp2)
        console.print(f"[green]employer_aliases.csv ({len(aliases)} groups)[/green]")
    except OSError as exc:
        console.print(f"[red]Failed to write employer_aliases.csv: {exc}[/red]")

    # HTML
    rows_html = "".join(
        f"<tr><td>{c['cluster_id']}</td><td>{c['reason']}</td><td>{len(c['vacancy_ids'])}</td></tr>"
        for c in clusters[:50]
    )
    html = f"""<!doctype html><html><head><meta charset=utf-8><title>Data Quality</title>
<style>body{{background:#0b1020;color:#e8edf7;font:14px system-ui;max-width:900px;margin:30px auto;padding:20px}}
h1{{color:#67e8f9}} table{{width:100%;border-collapse:collapse}} th,td{{padding:8px;border-bottom:1px solid #26324d}} th{{color:#fde68a}}</style></head><body>
<h1>Data Quality Report</h1>
<h2>Duplicates ({len(clusters)})</h2>
<table><tr><th>Cluster</th><th>Reason</th><th>Count</th></tr>{rows_html}</table>
</body></html>"""
    try:
        (out / "data_quality_report.html").write_text(html, encoding="utf-8")
        console.print(f"[green]data_quality_report.html[/green]")
    except OSError as exc:
        console.print(f"[red]Failed to write data_quality_report.html: {exc}[/red]")
    return 0
