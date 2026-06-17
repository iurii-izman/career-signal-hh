from __future__ import annotations

import argparse

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from ..models import Vacancy
from ..scoring_v2 import compute_score_details
from ..search_presets import get_preset, list_presets
from ..storage import Storage
from ..utils import json_loads

console = Console()


def _storage() -> Storage:
    import os

    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def command_score_explain(args: argparse.Namespace) -> int:
    storage = _storage()
    vacancy_data = storage.get_vacancy(args.vacancy_id)
    if not vacancy_data:
        console.print(f"[red]Vacancy '{args.vacancy_id}' not found.[/red]")
        return 1

    details_data = storage.get_score_details(args.vacancy_id)

    # Vacancy info
    console.print(f"\n[bold]{vacancy_data.get('name', '?')}[/bold]")
    console.print(f"Company: {vacancy_data.get('employer_name', '?')}")
    console.print(f"URL: {vacancy_data.get('alternate_url', '?')}")

    if not details_data:
        console.print(
            "\n[yellow]No v2 score details found. Run 'score rescore' or search with presets.[/yellow]"
        )
        return 0

    total = details_data.get("total_score", 0)
    confidence = details_data.get("confidence_score", 0)
    noise = details_data.get("noise_score", 0)
    decision = details_data.get("decision", "?")
    preset = details_data.get("preset_name", "?")
    cat_scores = json_loads(details_data.get("category_scores_json"), {})
    matched = json_loads(details_data.get("matched_keywords_json"), [])
    excluded = json_loads(details_data.get("excluded_keywords_json"), [])
    risk_flags = json_loads(details_data.get("risk_flags_json"), [])
    quality_flags = json_loads(details_data.get("quality_flags_json"), [])
    explanation = json_loads(details_data.get("explanation_json"), {})

    # Score summary
    conf_style = "green" if confidence >= 70 else "yellow" if confidence >= 40 else "red"
    noise_style = "green" if noise <= 20 else "yellow" if noise <= 50 else "red"
    console.print(
        f"\nTotal Score: [bold]{total}[/bold] | "
        f"Confidence: [bold {conf_style}]{confidence}%[/bold {conf_style}] | "
        f"Noise: [bold {noise_style}]{noise}%[/bold {noise_style}] | "
        f"Decision: [bold]{decision}[/bold] | Preset: {preset}"
    )

    # Quality flags
    if quality_flags:
        console.print(f"Quality: {', '.join(str(f) for f in quality_flags)}")

    # Confidence/Noise breakdown
    if explanation:
        if explanation.get("confidence_breakdown"):
            console.print(f"[dim]Confidence: {explanation['confidence_breakdown']}[/dim]")
        if explanation.get("noise_breakdown"):
            console.print(f"[dim]Noise: {explanation['noise_breakdown']}[/dim]")
        if explanation.get("decision_logic"):
            console.print(f"[dim]Decision logic: {explanation['decision_logic']}[/dim]")

    # Category scores
    if cat_scores:
        cat_table = Table(title="Category Scores")
        cat_table.add_column("Category")
        cat_table.add_column("Score")
        for cat, score in sorted(cat_scores.items()):
            cat_table.add_row(cat, str(score))
        console.print(cat_table)

    # Matched keywords
    if matched:
        kw_table = Table(title="Matched Keywords")
        kw_table.add_column("Keyword")
        kw_table.add_column("Field")
        kw_table.add_column("Weight")
        kw_table.add_column("Reason")
        for kw in matched:
            kw_table.add_row(
                kw.get("keyword", ""),
                kw.get("field", ""),
                f"+{kw.get('weight', 0)}",
                kw.get("reason", ""),
            )
        console.print(kw_table)

    # Excluded keywords
    if excluded:
        ex_table = Table(title="Excluded Keywords")
        ex_table.add_column("Keyword")
        ex_table.add_column("Field")
        ex_table.add_column("Weight")
        ex_table.add_column("Reason")
        for kw in excluded:
            ex_table.add_row(
                kw.get("keyword", ""),
                kw.get("field", ""),
                str(kw.get("weight", 0)),
                kw.get("reason", ""),
            )
        console.print(ex_table)

    # Risk flags
    if risk_flags:
        console.print(f"\nRisk flags: {', '.join(str(f) for f in risk_flags)}")

    # Explanation
    if explanation:
        console.print(f"\n[dim]{explanation.get('total_formula', '')}[/dim]")

    return 0


def command_score_rescore(args: argparse.Namespace) -> int:
    storage = _storage()
    limit = args.limit or None

    if args.preset:
        preset = get_preset(args.preset)
        if preset is None:
            console.print(f"[red]Preset '{args.preset}' not found.[/red]")
            return 1
        presets = {args.preset: preset}
        rows = storage.list_vacancies_for_rescore(limit=limit, preset=args.preset)
    else:
        all_presets = list_presets()
        if not all_presets:
            console.print(
                "[red]No presets available. Create config/search_presets.yaml or use --preset.[/red]"
            )
            return 1
        presets = {p["_name"]: p for p in all_presets}
        rows = storage.list_vacancies_for_rescore(limit=limit)

    if not rows:
        console.print("[yellow]No vacancies to rescore.[/yellow]")
        return 0

    scored = 0
    for row in rows:
        vacancy = Vacancy(
            id=row["id"],
            name=row.get("name") or "",
            employer_name=row.get("employer_name") or "",
            description_text=row.get("description_text") or "",
            key_skills=json_loads(row.get("key_skills_json"), []),
            snippet_requirement="",
            snippet_responsibility="",
            schedule_name=row.get("schedule_name"),
            published_at=row.get("published_at"),
            salary_from=row.get("salary_from"),
            salary_to=row.get("salary_to"),
            salary_currency=row.get("salary_currency"),
            raw_json=row.get("raw_json", "{}"),
            first_seen_at=row.get("first_seen_at", ""),
            last_seen_at=row.get("last_seen_at", ""),
            source_profile=row.get("source_profile"),
        )

        source = row.get("source_profile") or ""
        preset = presets.get(source)
        if preset is None:
            # Try first preset as fallback
            if not args.preset:
                preset = next(iter(presets.values()), None)
            if preset is None:
                continue

        details = compute_score_details(vacancy, preset)
        storage.upsert_score_details(details)
        from ..scoring_v2 import _to_score_result

        storage.upsert_score(_to_score_result(details))
        scored += 1

    console.print(f"[green]Rescored {scored} vacancies.[/green]")
    return 0
