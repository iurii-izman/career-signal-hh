from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from rich.console import Console

from ..briefing_core import briefing_output_paths, briefing_slug, build_briefing_artifact
from ..config import _services

console = Console()


def _print_console_summary(payload: dict[str, Any]) -> None:
    vacancy = payload["vacancy"]
    score = payload["score"]
    action = payload["recommended_action"]
    console.print(f"[bold]{vacancy['company']} — {vacancy['title']}[/bold]")
    console.print(
        f"score={score['total']} | decision={score['decision']} | "
        f"confidence={score['confidence']} | noise={score['noise']}"
    )
    console.print(f"verdict: {action['verdict']}")
    for block in payload["blocks"][2:]:
        console.print(f"\n[cyan]{block['title']}[/cyan]")
        for item in block["items"][:4]:
            console.print(f"  - {item}")


def _write_artifact(artifact: dict[str, Any], vacancy: dict[str, Any], fmt: str, out_dir: Path) -> list[Path]:
    paths = briefing_output_paths(vacancy, out_dir)
    created: list[Path] = []
    if fmt in {"md", "all"}:
        paths["md"].write_text(artifact["markdown"], encoding="utf-8")
        created.append(paths["md"])
    if fmt in {"html", "all"}:
        paths["html"].write_text(artifact["html"], encoding="utf-8")
        created.append(paths["html"])
    if fmt in {"json", "all"}:
        paths["json"].write_text(artifact["json"], encoding="utf-8")
        created.append(paths["json"])
    return created


def _save_briefing(storage, vacancy_id: str, lang: str, artifact: dict[str, Any]) -> None:
    payload = artifact["payload"]
    score = payload["score"]
    storage.upsert_briefing_report(
        vacancy_id,
        lang=lang,
        score_total=int(score["total"]),
        decision=str(score["decision"]),
        report_md=artifact["markdown"],
        payload=payload,
    )


def _queue_rows(storage, args: argparse.Namespace) -> list[dict[str, Any]]:
    limit = args.top or args.limit or 10
    decisions = [args.decision] if args.decision else None
    return storage.list_queue(
        min_score=args.min_score or 0,
        decisions=decisions,
        preset=args.preset,
        limit=limit,
        status=args.status,
        remote_only=args.remote_only,
        with_salary=args.with_salary,
        hide_risk=args.hide_risk,
        new_only=args.new_only,
    )


def _write_index(rows: list[dict[str, Any]], out_dir: Path) -> Path:
    lines = [
        "<!doctype html><html><head><meta charset=utf-8><title>Briefings</title>",
        "<style>body{background:#0b1020;color:#e8edf7;font:15px system-ui;max-width:860px;margin:40px auto;padding:20px}",
        "h1{color:#67e8f9} a{color:#bfdbfe} li{margin:8px 0}</style></head><body>",
        f"<h1>Briefings ({len(rows)})</h1><ul>",
    ]
    for row in rows:
        slug = briefing_slug(row.get("name", ""))
        lines.append(
            f'<li><a href="{row["id"]}_{slug}.html">{row.get("name", "?")}</a> — '
            f"{row.get('employer_name', '?')} — score {row.get('total_score', 0)}</li>"
        )
    lines.append("</ul></body></html>")
    path = out_dir / "index.html"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def command_briefing(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    lang = getattr(args, "lang", None) or "ru"
    fmt = getattr(args, "format", None) or "all"
    out_dir = Path("exports/briefings")
    out_dir.mkdir(parents=True, exist_ok=True)

    vacancies: list[dict[str, Any]] = []
    if args.vacancy_id:
        row = storage.get_vacancy_full(args.vacancy_id)
        if not row:
            console.print(f"[red]Vacancy '{args.vacancy_id}' not found.[/red]")
            return 1
        vacancies = [row]
    elif args.top or args.limit:
        vacancies = _queue_rows(storage, args)
    else:
        console.print("[red]Specify VACANCY_ID or --top/--limit.[/red]")
        return 1

    if not vacancies:
        console.print("[yellow]No vacancies found.[/yellow]")
        return 0

    generated_rows: list[dict[str, Any]] = []
    for vacancy in vacancies:
        details = storage.get_score_details(vacancy["id"])
        artifact = build_briefing_artifact(vacancy, details, lang=lang)
        _print_console_summary(artifact["payload"])
        created = _write_artifact(artifact, vacancy, fmt, out_dir)
        if created:
            console.print(
                f"[green]{vacancy['id']}:[/green] "
                + ", ".join(path.name for path in created)
            )
        if args.save_review:
            _save_briefing(storage, vacancy["id"], lang, artifact)
            console.print(f"[dim]{vacancy['id']}: briefing saved to DB[/dim]")
        generated_rows.append(vacancy)

    if len(generated_rows) > 1 and fmt in {"html", "all"}:
        index_path = _write_index(generated_rows, out_dir)
        console.print(f"[green]Index:[/green] {index_path}")
    return 0
