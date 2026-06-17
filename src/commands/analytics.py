from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from ..utils import json_loads

console = Console()


def _storage():
    import os as _os

    from dotenv import load_dotenv

    from ..storage import Storage

    load_dotenv()
    return Storage(_os.getenv("DB_PATH", "data/vacancies.sqlite"))


def command_analytics_summary(_: argparse.Namespace) -> int:
    storage = _storage()
    with storage.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        new_24h = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE datetime(first_seen_at) >= datetime('now','-1 day')"
        ).fetchone()[0]
        new_7d = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE datetime(first_seen_at) >= datetime('now','-7 days')"
        ).fetchone()[0]
        new_30d = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE datetime(first_seen_at) >= datetime('now','-30 days')"
        ).fetchone()[0]
        avg_score = conn.execute("SELECT COALESCE(AVG(total_score),0) FROM scores").fetchone()[0]
        strong = conn.execute(
            "SELECT COUNT(*) FROM score_details WHERE decision='strong_match'"
        ).fetchone()[0]
        queue = conn.execute(
            "SELECT COUNT(*) FROM score_details WHERE decision IN ('strong_match','queue')"
        ).fetchone()[0]
        remote = conn.execute(
            "SELECT COUNT(*) FROM scores WHERE work_format_flags_json LIKE '%remote%'"
        ).fetchone()[0]
        with_salary = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL"
        ).fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='applied'"
        ).fetchone()[0]
        interview = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='interview'"
        ).fetchone()[0]
        offer = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='offer'"
        ).fetchone()[0]

    table = Table(title="Analytics Summary")
    table.add_column("Metric")
    table.add_column("Value")
    for label, val in [
        ("Total vacancies", total),
        ("New 24h", new_24h),
        ("New 7d", new_7d),
        ("New 30d", new_30d),
        ("Avg score", f"{avg_score:.0f}"),
        ("Strong match", strong),
        ("Queue (strong+queue)", queue),
        ("Remote", remote),
        ("With salary", with_salary),
        ("Applied", applied),
        ("Interview", interview),
        ("Offer", offer),
    ]:
        table.add_row(label, str(val))
    console.print(table)
    return 0


def command_analytics_skills(_: argparse.Namespace) -> int:
    storage = _storage()
    skill_counts: dict[str, dict[str, Any]] = {}
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT key_skills_json, s.total_score, s.best_profile FROM vacancies v "
            "LEFT JOIN scores s ON s.vacancy_id=v.id WHERE key_skills_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            skills = json_loads(row[0], [])
            score = row[1] or 0
            profile = row[2] or ""
            for skill in skills:
                s = skill.strip().lower()
                if not s or len(s) < 2:
                    continue
                if s not in skill_counts:
                    skill_counts[s] = {"count": 0, "total_score": 0, "presets": set()}
                skill_counts[s]["count"] += 1
                skill_counts[s]["total_score"] += score
                if profile:
                    skill_counts[s]["presets"].add(profile)

    items = sorted(skill_counts.items(), key=lambda x: -x[1]["count"])[:30]
    table = Table(title="Top Skills")
    for col in ["Skill", "Count", "Avg Score", "Presets"]:
        table.add_column(col)
    for skill, data in items:
        table.add_row(
            skill,
            str(data["count"]),
            f"{data['total_score'] / max(1, data['count']):.0f}",
            ", ".join(sorted(data["presets"])),
        )
    console.print(table)
    return 0


def command_analytics_employers(_: argparse.Namespace) -> int:
    storage = _storage()
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT employer_name, COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score, "
            "SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END) applied, "
            "SUM(CASE WHEN r.status='interview' THEN 1 ELSE 0 END) interview, "
            "SUM(CASE WHEN sd.decision='strong_match' THEN 1 ELSE 0 END) strong "
            "FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id "
            "LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id "
            "LEFT JOIN score_details sd ON sd.vacancy_id=v.id "
            "WHERE v.employer_name IS NOT NULL AND v.employer_name != '' "
            "GROUP BY v.employer_name ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

    table = Table(title="Top Employers")
    for col in ["Employer", "Vacancies", "Avg Score", "Applied", "Interview", "Strong"]:
        table.add_column(col)
    for row in rows:
        table.add_row(
            row[0] or "?",
            str(row[1]),
            f"{row[2]:.0f}",
            str(row[3]),
            str(row[4]),
            str(row[5]),
        )
    console.print(table)
    return 0


def command_analytics_salary(_: argparse.Namespace) -> int:
    storage = _storage()
    with storage.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        with_salary = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL"
        ).fetchone()[0]
        rur = conn.execute("SELECT COUNT(*) FROM vacancies WHERE salary_currency='RUR'").fetchone()[
            0
        ]
        usd = conn.execute("SELECT COUNT(*) FROM vacancies WHERE salary_currency='USD'").fetchone()[
            0
        ]
        eur = conn.execute("SELECT COUNT(*) FROM vacancies WHERE salary_currency='EUR'").fetchone()[
            0
        ]
        avg_from = conn.execute(
            "SELECT COALESCE(AVG(salary_from),0) FROM vacancies WHERE salary_from IS NOT NULL"
        ).fetchone()[0]
        max_from = conn.execute(
            "SELECT COALESCE(MAX(salary_from),0) FROM vacancies WHERE salary_from IS NOT NULL"
        ).fetchone()[0]
        ranges = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE salary_from BETWEEN 0 AND 100000"
        ).fetchone()[0]
        mid = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE salary_from BETWEEN 100001 AND 300000"
        ).fetchone()[0]
        high = conn.execute("SELECT COUNT(*) FROM vacancies WHERE salary_from > 300000").fetchone()[
            0
        ]

    table = Table(title="Salary Analytics")
    table.add_column("Metric")
    table.add_column("Value")
    for label, val in [
        ("Total", total),
        ("With salary", f"{with_salary} ({100 * with_salary / max(1, total):.0f}%)"),
        ("RUR", rur),
        ("USD", usd),
        ("EUR", eur),
        ("Avg salary_from", f"{avg_from:,.0f}".replace(",", " ")),
        ("Max salary_from", f"{max_from:,.0f}".replace(",", " ")),
        ("0–100k", ranges),
        ("100k–300k", mid),
        ("300k+", high),
    ]:
        table.add_row(label, str(val))
    console.print(table)
    return 0


def command_analytics_presets(_: argparse.Namespace) -> int:
    storage = _storage()
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT COALESCE(sd.preset_name, s.best_profile, 'unknown') preset, "
            "COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score, "
            "SUM(CASE WHEN sd.decision='strong_match' THEN 1 ELSE 0 END) strong, "
            "SUM(CASE WHEN sd.decision IN ('strong_match','queue') THEN 1 ELSE 0 END) queue, "
            "SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END) applied, "
            "SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END) rejected, "
            "SUM(CASE WHEN r.status='interview' THEN 1 ELSE 0 END) interview, "
            "SUM(CASE WHEN r.status='offer' THEN 1 ELSE 0 END) offer "
            "FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id "
            "LEFT JOIN score_details sd ON sd.vacancy_id=v.id "
            "LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id "
            "GROUP BY preset ORDER BY cnt DESC"
        ).fetchall()

    table = Table(title="Preset Performance")
    for col in [
        "Preset",
        "Vacancies",
        "Avg Score",
        "Strong",
        "Queue",
        "Applied",
        "Rejected",
        "Intvw",
        "Offer",
    ]:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(c) for c in row])
    console.print(table)
    return 0


def command_analytics_funnel(_: argparse.Namespace) -> int:
    storage = _storage()
    with storage.connect() as conn:
        stages = [
            ("new", "COALESCE(r.status,'new')='new'"),
            ("interesting", "r.status='interesting'"),
            ("maybe", "r.status='maybe'"),
            ("applied", "r.status='applied'"),
            ("interview", "r.status='interview'"),
            ("offer", "r.status='offer'"),
            ("rejected", "r.status='rejected'"),
            ("archived", "r.status='archived'"),
        ]
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]

    table = Table(title="Review Funnel")
    table.add_column("Stage")
    table.add_column("Count")
    table.add_column("% of Total")
    for name, where in stages:
        with storage.connect() as conn:
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM vacancies v LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id WHERE {where}"
            ).fetchone()[0]
        pct = f"{100 * cnt / max(1, total):.1f}%"
        table.add_row(name, str(cnt), pct)
    console.print(table)
    return 0


def _atomic_write(path: Path, writer: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent
    ) as h:
        writer(h)
        tp = Path(h.name)
    os.replace(tp, path)


def command_analytics_export(_: argparse.Namespace) -> int:
    storage = _storage()
    out = Path("exports")

    # JSON summary
    with storage.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        new_24h = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE datetime(first_seen_at) >= datetime('now','-1 day')"
        ).fetchone()[0]
        avg_score = conn.execute("SELECT COALESCE(AVG(total_score),0) FROM scores").fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='applied'"
        ).fetchone()[0]
        interview = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='interview'"
        ).fetchone()[0]
        offer = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='offer'"
        ).fetchone()[0]
    summary = {
        "total": total,
        "new_24h": new_24h,
        "avg_score": round(avg_score, 1),
        "applied": applied,
        "interview": interview,
        "offer": offer,
    }
    _atomic_write(out / "analytics_summary.json", lambda h: json.dump(summary, h, indent=2))
    console.print("[green]analytics_summary.json[/green]")

    # Skills CSV
    skill_counts: dict[str, int] = {}
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT key_skills_json FROM vacancies WHERE key_skills_json IS NOT NULL"
        ).fetchall()
        for (skills_json,) in rows:
            for skill in json_loads(skills_json, []):
                s = skill.strip().lower()
                if s and len(s) >= 2:
                    skill_counts[s] = skill_counts.get(s, 0) + 1
    items = sorted(skill_counts.items(), key=lambda x: -x[1])[:100]

    def _write_skills(h):
        w = csv.writer(h)
        w.writerow(["skill", "count"])
        for s, c in items:
            w.writerow([s, c])

    _atomic_write(out / "analytics_skills.csv", _write_skills)
    console.print(f"[green]analytics_skills.csv ({len(items)} skills)[/green]")

    # Employers CSV
    with storage.connect() as conn:
        emp_rows = conn.execute(
            "SELECT employer_name, COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score "
            "FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id "
            "WHERE employer_name IS NOT NULL AND employer_name != '' "
            "GROUP BY employer_name ORDER BY cnt DESC LIMIT 50"
        ).fetchall()

    def _write_emp(h):
        w = csv.writer(h)
        w.writerow(["employer", "vacancies", "avg_score"])
        for r in emp_rows:
            w.writerow([r[0], r[1], f"{r[2]:.0f}"])

    _atomic_write(out / "analytics_employers.csv", _write_emp)
    console.print(f"[green]analytics_employers.csv ({len(emp_rows)} employers)[/green]")

    # HTML report
    skills_html = "".join(f"<tr><td>{s}</td><td>{c}</td></tr>" for s, c in items[:20])
    emp_html = "".join(
        f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]:.0f}</td></tr>" for r in emp_rows[:20]
    )
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareerSignal HH Analytics</title>
<style>
body{{background:#0b1020;color:#e8edf7;font:14px system-ui;max-width:1000px;margin:30px auto;padding:20px}}
h1{{color:#67e8f9}} h2{{color:#9bf6e8;margin-top:30px}} table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #26324d}} th{{color:#fde68a}}
.card{{background:#141b2d;border:1px solid #26324d;border-radius:10px;padding:16px;margin:10px 0}}
.row{{display:flex;gap:12px;flex-wrap:wrap}} .stat{{flex:1;min-width:120px;text-align:center;padding:10px}}
.stat strong{{display:block;font-size:24px;color:#67e8f9}}
</style></head><body>
<h1>CareerSignal HH Analytics</h1>
<div class="row">{"".join(f'<div class="stat"><strong>{v}</strong><span>{k}</span></div>' for k, v in [("Total", total), ("New 24h", new_24h), ("Avg score", f"{avg_score:.0f}"), ("Applied", applied), ("Interview", interview), ("Offer", offer)])}</div>

<h2>Top Skills</h2>
<table><tr><th>Skill</th><th>Count</th></tr>{skills_html}</table>

<h2>Top Employers</h2>
<table><tr><th>Employer</th><th>Vacancies</th><th>Avg Score</th></tr>{emp_html}</table>
</body></html>"""
    (out / "analytics_report.html").write_text(html, encoding="utf-8")
    console.print("[green]analytics_report.html[/green]")
    return 0
