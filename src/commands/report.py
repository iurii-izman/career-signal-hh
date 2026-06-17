"""Weekly report pack — progress tracking and action planning.

Usage:
  python -m src.main report weekly
  python -m src.main report weekly --days 7 --preset ai_rag_remote
  python -m src.main report export
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from ..storage import Storage
from ..utils import json_dumps, json_loads

console = Console()


def _storage() -> Storage:
    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# Data collection
# ═══════════════════════════════════════════════════════════════════════════


def _collect_report_data(
    storage: Storage, days: int, preset: str | None, campaign: str | None
) -> dict:
    """Collect all report data from DB."""
    since = _days_ago(days)
    data: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "preset": preset,
        "campaign": campaign,
    }

    with storage.connect() as conn:
        # ── Executive summary ──────────────────────────────────────────
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        new_count = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE first_seen_at >= ?", (since,)
        ).fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE COALESCE(archived,0)=0"
        ).fetchone()[0]

        # ── Search activity ────────────────────────────────────────────
        runs = conn.execute(
            "SELECT COUNT(*) FROM search_runs WHERE started_at >= ?", (since,)
        ).fetchone()[0]
        found = conn.execute(
            "SELECT COALESCE(SUM(found_count),0) FROM search_runs WHERE started_at >= ?",
            (since,),
        ).fetchone()[0]
        loaded = conn.execute(
            "SELECT COALESCE(SUM(loaded_count),0) FROM search_runs WHERE started_at >= ?",
            (since,),
        ).fetchone()[0]

        # ── Scoring ────────────────────────────────────────────────────
        strong = conn.execute(
            """SELECT COUNT(*) FROM score_details
               WHERE decision='strong_match' AND scored_at >= ?""",
            (since,),
        ).fetchone()[0]
        avg_score = (
            conn.execute("SELECT ROUND(AVG(COALESCE(total_score,0)),1) FROM scores").fetchone()[0]
            or 0
        )

        # ── Review funnel ──────────────────────────────────────────────
        applied = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='applied' AND updated_at >= ?",
            (since,),
        ).fetchone()[0]
        interview = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='interview'"
        ).fetchone()[0]
        offer = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='offer'"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='rejected' AND updated_at >= ?",
            (since,),
        ).fetchone()[0]
        total_reviewed = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status != 'new'"
        ).fetchone()[0]

        # ── Preset performance ─────────────────────────────────────────
        preset_rows = conn.execute(
            """SELECT v.source_profile,
                      COUNT(v.id) total,
                      ROUND(AVG(COALESCE(s.total_score,0)),1) avg_score,
                      SUM(CASE WHEN COALESCE(r.status,'new') IN ('interesting','applied','interview','offer') THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN COALESCE(r.status,'new') IN ('rejected','archived') THEN 1 ELSE 0 END) bad
               FROM vacancies v
               LEFT JOIN scores s ON s.vacancy_id=v.id
               LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id
               WHERE v.source_profile IS NOT NULL AND v.source_profile != ''
               GROUP BY v.source_profile
               ORDER BY total DESC""",
        ).fetchall()

        # ── Top skills ─────────────────────────────────────────────────
        skill_rows = conn.execute(
            """SELECT sd.matched_keywords_json
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id=v.id
               WHERE v.first_seen_at >= ?
               ORDER BY sd.total_score DESC LIMIT 200""",
            (since,),
        ).fetchall()
        skill_freq: dict[str, int] = {}
        for row in skill_rows:
            for kw in json_loads(row["matched_keywords_json"], []):
                k = kw.get("keyword", "")
                if k and len(k) > 2:
                    skill_freq[k] = skill_freq.get(k, 0) + 1
        top_skills = sorted(skill_freq.items(), key=lambda x: -x[1])[:15]

        # ── Salary insight ─────────────────────────────────────────────
        salary_rows = conn.execute(
            """SELECT salary_from, salary_to, salary_currency
               FROM vacancies
               WHERE first_seen_at >= ?
                 AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)
               ORDER BY COALESCE(salary_from, salary_to) DESC LIMIT 50""",
            (since,),
        ).fetchall()
        salaries = [r["salary_from"] or r["salary_to"] or 0 for r in salary_rows]
        avg_salary = sum(salaries) // max(len(salaries), 1) if salaries else 0
        with_salary = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE first_seen_at>=? AND (salary_from IS NOT NULL OR salary_to IS NOT NULL)",
            (since,),
        ).fetchone()[0]

        # ── Data quality ───────────────────────────────────────────────
        missing_desc = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE first_seen_at>=? AND (description_text IS NULL OR description_text='')",
            (since,),
        ).fetchone()[0]
        missing_salary = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE first_seen_at>=? AND salary_from IS NULL AND salary_to IS NULL",
            (since,),
        ).fetchone()[0]

        # ── Follow-ups needed ──────────────────────────────────────────
        followup_rows = conn.execute(
            """SELECT v.id, v.name, v.employer_name, r.applied_at
               FROM vacancy_reviews r
               JOIN vacancies v ON v.id=r.vacancy_id
               WHERE r.status='applied'
                 AND r.applied_at IS NOT NULL
                 AND r.applied_at <= ?
                 AND (r.next_action IS NULL OR r.next_action='')
               ORDER BY r.applied_at ASC LIMIT 10""",
            (_days_ago(5),),
        ).fetchall()

        # ── Calibration suggestions ────────────────────────────────────
        from ..commands.calibrate import _load_suggestions

        try:
            suggestions = _load_suggestions()
            pending = [s for s in suggestions if s.get("status") == "pending"]
        except Exception:
            pending = []

    data.update(
        {
            "total_vacancies": total,
            "new_vacancies": new_count,
            "active_vacancies": active,
            "search_runs": runs,
            "total_found": found,
            "total_loaded": loaded,
            "strong_matches": strong,
            "avg_score": avg_score,
            "applied": applied,
            "interview": interview,
            "offer": offer,
            "rejected": rejected,
            "total_reviewed": total_reviewed,
            "preset_performance": [dict(r) for r in preset_rows],
            "top_skills": [{"keyword": k, "count": c} for k, c in top_skills],
            "avg_salary": avg_salary,
            "with_salary_count": with_salary,
            "missing_description": missing_desc,
            "missing_salary": missing_salary,
            "follow_ups": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "company": r["employer_name"],
                    "applied_at": r["applied_at"],
                }
                for r in followup_rows
            ],
            "pending_calibrations": len(pending),
        }
    )
    return data


# ═══════════════════════════════════════════════════════════════════════════
# Action plan
# ═══════════════════════════════════════════════════════════════════════════


def _action_plan(data: dict) -> list[str]:
    """Generate next-week action plan from report data."""
    plan: list[str] = []

    if data["strong_matches"] > 0:
        plan.append(
            f"Review {data['strong_matches']} strong matches: "
            "python -m src.main review queue --decision strong_match --min-score 0"
        )

    if data["follow_ups"]:
        plan.append(
            f"Follow up on {len(data['follow_ups'])} applications older than 5 days:\n"
            + "\n".join(
                f"  python -m src.main review next {f['id']} "
                f'--action "Follow up" --date {_days_ago(-3)[:10]}'
                for f in data["follow_ups"][:5]
            )
        )

    if data["strong_matches"] >= 3:
        plan.append(
            "Generate apply packs for top strong matches: "
            "python -m src.main campaigns apply-pack iurii_ai --top 5"
        )

    if data["pending_calibrations"] > 0:
        plan.append(
            f"Apply {data['pending_calibrations']} pending calibration suggestions: "
            "python -m src.main calibrate suggest"
        )

    # Maintenance
    plan.append("Run maintenance: python -m src.main maintenance cleanup --dry-run")

    return plan


# ═══════════════════════════════════════════════════════════════════════════
# Generators: MD / HTML / JSON
# ═══════════════════════════════════════════════════════════════════════════


def _generate_md(data: dict, plan: list[str]) -> str:
    p = data
    return f"""# CareerSignal HH — Weekly Report

**Generated:** {p["generated_at"][:16]}
**Period:** {p["period_days"]} days

## Executive Summary
- Total vacancies: {p["total_vacancies"]}
- New this week: {p["new_vacancies"]}
- Active: {p["active_vacancies"]}
- Applied: {p["applied"]}
- Interview: {p["interview"]}
- Offer: {p["offer"]}
- Rejected: {p["rejected"]}

## Search Activity
- Search runs: {p["search_runs"]}
- Found: {p["total_found"]}
- Loaded: {p["total_loaded"]}
- Avg score: {p["avg_score"]}
- Strong matches: {p["strong_matches"]}

## Preset Performance
| Preset | Total | Avg Score | Good | Bad |
|--------|-------|-----------|------|-----|
{"".join("| " + pr["source_profile"] + " | " + str(pr["total"]) + " | " + str(pr["avg_score"]) + " | " + str(pr["good"]) + " | " + str(pr["bad"]) + " |" + chr(10) for pr in p["preset_performance"])}

## Top Skills
{", ".join(f"{s['keyword']} ({s['count']})" for s in p["top_skills"][:15])}

## Salary Insight
- Avg salary: {p["avg_salary"]:,} RUB
- With salary disclosed: {p["with_salary_count"]}

## Data Quality
- Missing description: {p["missing_description"]}
- Missing salary: {p["missing_salary"]}

## Follow-ups Needed ({len(p["follow_ups"])})
{"".join("- " + f["name"] + " @ " + f["company"] + " — applied " + f["applied_at"][:10] + chr(10) for f in p["follow_ups"])}

## Next Week Action Plan
{"".join(str(i) + ". " + a + chr(10) for i, a in enumerate(plan, 1))}
"""


def _generate_html(data: dict, plan: list[str]) -> str:
    p = data
    preset_rows = "".join(
        f"<tr><td>{pr['source_profile']}</td><td>{pr['total']}</td>"
        f"<td>{pr['avg_score']}</td><td>{pr['good']}</td><td>{pr['bad']}</td></tr>"
        for pr in p["preset_performance"]
    )
    skills = ", ".join(f"<span class='skill'>{s['keyword']}</span>" for s in p["top_skills"][:15])
    plan_items = "".join(f"<li>{a}</li>" for a in plan)
    fu_rows = "".join(
        f"<tr><td>{f['name']}</td><td>{f['company']}</td><td>{f['applied_at'][:10]}</td></tr>"
        for f in p["follow_ups"]
    )

    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>CareerSignal HH — Weekly Report</title>
<style>
body{{background:#0b1020;color:#e8edf7;font:14px system-ui;max-width:800px;margin:20px auto;padding:20px}}
h1{{color:#67e8f9}}h2{{color:#9bf6e8;margin-top:24px;border-bottom:1px solid #26324d;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{padding:6px 10px;text-align:left;border-bottom:1px solid #26324d}}
th{{color:#fde68a}}
.stat{{display:inline-block;background:#141b2d;border:1px solid #26324d;border-radius:10px;padding:12px;margin:6px;text-align:center;min-width:100px}}
.stat strong{{display:block;font-size:20px;color:#67e8f9}}
.skill{{display:inline-block;background:#193b42;color:#9bf6e8;padding:2px 8px;border-radius:6px;margin:2px;font-size:12px}}
li{{margin:4px 0}}
</style></head><body>
<h1>CareerSignal HH — Weekly Report</h1>
<p>Generated: {p["generated_at"][:16]} · Period: {p["period_days"]} days</p>

<h2>Executive Summary</h2>
<div class='row'>
<div class='stat'><strong>{p["total_vacancies"]}</strong>Total</div>
<div class='stat'><strong>{p["new_vacancies"]}</strong>New</div>
<div class='stat'><strong>{p["applied"]}</strong>Applied</div>
<div class='stat'><strong>{p["interview"]}</strong>Interview</div>
<div class='stat'><strong>{p["offer"]}</strong>Offer</div>
<div class='stat'><strong>{p["rejected"]}</strong>Rejected</div>
</div>

<h2>Search Activity</h2>
<table>
<tr><th>Runs</th><th>Found</th><th>Loaded</th><th>Avg Score</th><th>Strong</th></tr>
<tr><td>{p["search_runs"]}</td><td>{p["total_found"]}</td><td>{p["total_loaded"]}</td>
<td>{p["avg_score"]}</td><td>{p["strong_matches"]}</td></tr>
</table>

<h2>Preset Performance</h2>
<table><tr><th>Preset</th><th>Total</th><th>Avg</th><th>Good</th><th>Bad</th></tr>{preset_rows}</table>

<h2>Top Skills</h2>
<p>{skills}</p>

<h2>Salary Insight</h2>
<p>Avg salary: {p["avg_salary"]:,} RUB · With salary: {p["with_salary_count"]}</p>

<h2>Data Quality</h2>
<p>Missing description: {p["missing_description"]} · Missing salary: {p["missing_salary"]}</p>

<h2>Follow-ups Needed ({len(p["follow_ups"])})</h2>
<table><tr><th>Vacancy</th><th>Company</th><th>Applied</th></tr>{fu_rows}</table>

<h2>Next Week Action Plan</h2>
<ol>{plan_items}</ol>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
# CLI commands
# ═══════════════════════════════════════════════════════════════════════════


def command_report_weekly(args: argparse.Namespace) -> int:
    """Generate weekly progress report."""
    days = args.days or 7
    preset = getattr(args, "preset", None)
    campaign = getattr(args, "campaign", None)
    fmt = getattr(args, "format", None) or "all"

    storage = _storage()
    data = _collect_report_data(storage, days, preset, campaign)
    plan = _action_plan(data)

    # Print summary to console
    console.print(Panel.fit("[bold cyan]Weekly Report[/bold cyan]", border_style="cyan"))
    console.print(
        f"Period: {days} days | Total: {data['total_vacancies']} | New: {data['new_vacancies']}"
    )
    console.print(
        f"Applied: {data['applied']} | Interview: {data['interview']} | Offer: {data['offer']}"
    )
    console.print(f"Strong matches: {data['strong_matches']} | Avg score: {data['avg_score']}")

    # Top skills
    if data["top_skills"]:
        skills_str = ", ".join(f"{s['keyword']}({s['count']})" for s in data["top_skills"][:10])
        console.print(f"\nTop skills: {skills_str}")

    # Follow-ups
    if data["follow_ups"]:
        console.print(f"\n[yellow]⚠ {len(data['follow_ups'])} follow-ups needed:[/yellow]")
        for f in data["follow_ups"][:5]:
            console.print(
                f"  {f['name']} @ {f['company']} — "
                f'python -m src.main review next {f["id"]} --action "Follow up" --date {_days_ago(-3)[:10]}'
            )

    # Action plan
    console.print("\n[bold]Next Week Action Plan:[/bold]")
    for i, a in enumerate(plan, 1):
        console.print(f"  {i}. {a}")

    # Generate files
    out_dir = Path("exports/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    datestr = datetime.now().strftime("%Y%m%d")

    created = []
    if fmt in ("md", "all"):
        md_path = out_dir / f"weekly_{datestr}.md"
        md_path.write_text(_generate_md(data, plan), encoding="utf-8")
        created.append(str(md_path))
    if fmt in ("html", "all"):
        html_path = out_dir / f"weekly_{datestr}.html"
        html_path.write_text(_generate_html(data, plan), encoding="utf-8")
        created.append(str(html_path))
    if fmt in ("json", "all"):
        json_path = out_dir / f"weekly_{datestr}.json"
        json_path.write_text(json_dumps({**data, "action_plan": plan}), encoding="utf-8")
        created.append(str(json_path))

    for p in created:
        console.print(f"  [green]✓[/green] {p}")

    return 0


def command_report_export(_: argparse.Namespace) -> int:
    """Shortcut: export weekly report (all formats, 7 days)."""
    return command_report_weekly(
        argparse.Namespace(days=7, preset=None, campaign=None, format="all")
    )
