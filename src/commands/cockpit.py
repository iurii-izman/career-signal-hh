from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from ..config import _services
from ..data_quality import find_duplicates

console = Console()


def _storage():
    from dotenv import load_dotenv

    from ..storage import Storage

    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def command_cockpit_export(_: argparse.Namespace) -> int:
    storage = _storage()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")

    # Get stats
    stats = storage.stats()
    total = stats["total"]
    remote = stats["remote"]
    with_salary = stats["with_salary"]

    # Queue
    queue_rows = storage.list_queue(min_score=70, new_only=True, limit=20)

    # Funnel
    funnel = {}
    for status in ["new", "interesting", "applied", "interview", "offer", "rejected", "archived"]:
        funnel[status] = len(storage.list_queue(min_score=0, status=status, limit=9999))

    # Presets
    preset_rows = []
    with storage.connect() as conn:
        pr = conn.execute(
            """SELECT COALESCE(sd.preset_name, s.best_profile, 'unknown') preset,
               COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score,
               SUM(CASE WHEN sd.decision='strong_match' THEN 1 ELSE 0 END) strong,
               SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END) applied,
               SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END) rejected
            FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id
            LEFT JOIN score_details sd ON sd.vacancy_id=v.id
            LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id
            GROUP BY preset ORDER BY cnt DESC"""
        ).fetchall()
        for row in pr:
            preset_rows.append(
                dict(zip(["preset", "cnt", "avg_score", "strong", "applied", "rejected"], row))
            )

    # Data quality
    all_rows = storage.list_vacancies(limit=9999)
    clusters = find_duplicates(all_rows)
    dup_count = len(clusters)
    sample_count = sum(1 for r in all_rows if (r.get("id") or "").startswith("sample-"))
    missing_scores = sum(1 for r in all_rows if not r.get("total_score"))

    # DB-stored quality counts (may differ if clusters were saved)
    db_clusters = storage.count_clusters()
    db_dup_count = storage.count_duplicate_vacancies()
    db_aliases = storage.count_employer_aliases()

    # Build sections
    header_cards = f"""
    <div class="row">
      <div class="stat"><strong>{total}</strong><span>Total</span></div>
      <div class="stat"><strong>{funnel["new"]}</strong><span>New</span></div>
      <div class="stat"><strong>{funnel.get("applied", 0)}</strong><span>Applied</span></div>
      <div class="stat"><strong>{funnel.get("interview", 0)}</strong><span>Interview</span></div>
      <div class="stat"><strong>{funnel.get("offer", 0)}</strong><span>Offer</span></div>
      <div class="stat"><strong>{remote}</strong><span>Remote</span></div>
    </div>"""

    # Queue table
    queue_html = "<table><tr><th>ID</th><th>Score</th><th>Title</th><th>Company</th><th>Preset</th><th>Salary</th><th>Actions</th></tr>"
    for q in queue_rows:
        sid = q["id"]
        score = q.get("total_score", 0)
        name = (q.get("name") or "")[:40]
        emp = (q.get("employer_name") or "")[:25]
        preset = q.get("best_profile") or ""
        sal = _fmt_salary(q)
        url = q.get("alternate_url", "")
        queue_html += f"""<tr>
          <td>{sid}</td><td>{score}</td><td><a href="{url}">{name}</a></td>
          <td>{emp}</td><td>{preset}</td><td>{sal}</td>
          <td><code>review set {sid} --status interesting</code><br><code>apply-pack {sid}</code></td>
        </tr>"""
    queue_html += "</table>"

    # Presets table
    preset_html = "<table><tr><th>Preset</th><th>Total</th><th>Avg</th><th>Strong</th><th>Applied</th><th>Rejected</th></tr>"
    for p in preset_rows:
        preset_html += f"<tr><td>{p['preset']}</td><td>{p['cnt']}</td><td>{p['avg_score']:.0f}</td><td>{p['strong']}</td><td>{p['applied']}</td><td>{p['rejected']}</td></tr>"
    preset_html += "</table>"

    # Reports links
    links = []
    for name, path in [
        ("Vacancies Report", "exports/vacancies_report.html"),
        ("Analytics Report", "exports/analytics_report.html"),
        ("Apply Packs", "exports/apply_packs/index.html"),
        ("Data Quality", "exports/data_quality_report.html"),
    ]:
        if Path(path).exists():
            links.append(f'<li><a href="../{path}">{name}</a></li>')
    links_html = (
        "<ul>" + "".join(links) + "</ul>"
        if links
        else "<p>Run export commands to generate reports.</p>"
    )

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareerSignal HH Cockpit</title>
<style>
:root{{--bg:#0b1020;--panel:#141b2d;--line:#26324d;--text:#e8edf7;--muted:#9ba8bd;--accent:#67e8f9}}
body{{background:var(--bg);color:var(--text);font:14px system-ui,sans-serif;max-width:1100px;margin:20px auto;padding:0 20px}}
h1{{color:var(--accent);font-size:24px}} h2{{color:#9bf6e8;font-size:18px;margin-top:30px;border-bottom:1px solid var(--line);padding-bottom:8px}}
.row{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.stat{{flex:1;min-width:100px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center}}
.stat strong{{display:block;font-size:24px;color:var(--accent)}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line)}}
th{{color:#fde68a}} a{{color:#bfdbfe}} code{{background:#10182a;padding:1px 6px;border-radius:4px;font-size:12px;color:#fda4af}}
.cmd{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;margin:10px 0}}
.cmd code{{display:block;margin:4px 0;color:#9bf6e8}}
.meta{{color:var(--muted);font-size:12px;margin-bottom:20px}}
</style></head><body>
<h1>🚀 CareerSignal HH Cockpit</h1>
<div class="meta">Generated: {now} · DB: {db_path} · {total} vacancies · {dup_count} duplicate clusters · {missing_scores} missing scores</div>

{header_cards}

<h2>📋 Today's Queue (new, score≥70, top 20)</h2>
{queue_html if queue_rows else "<p>No pending queue. Run autopilot daily or search.</p>"}

<h2>📊 Preset Performance</h2>
{preset_html if preset_rows else "<p>No preset data.</p>"}

<h2>📈 Review Funnel</h2>
<div class="row">{"".join(f'<div class="stat"><strong>{c}</strong><span>{k}</span></div>' for k, c in funnel.items())}</div>

<h2>🔍 Data Quality</h2>
<div class="row">
  <div class="stat"><strong>{sample_count}</strong><span>Sample vacancies</span></div>
  <div class="stat"><strong>{missing_scores}</strong><span>Missing scores</span></div>
  <div class="stat"><strong>{db_clusters}</strong><span>Clusters (DB)</span></div>
  <div class="stat"><strong>{db_dup_count}</strong><span>Dup vacancies (DB)</span></div>
  <div class="stat"><strong>{db_aliases}</strong><span>Employer aliases</span></div>
</div>
<p style="color:var(--muted);margin:0 0 12px">Live scan: {dup_count} clusters · {with_salary} with salary</p>

<h2>📁 Reports</h2>
{links_html}

<h2>⚡ Command Center</h2>
<div class="cmd">
<code>python -m src.main autopilot daily --backup-first</code>
<code>python -m src.main review next-best</code>
<code>python -m src.main apply-pack --top 5 --decision strong_match</code>
<code>python -m src.main analytics export</code>
<code>python -m src.main db backup</code>
<code>python -m src.main quality cluster</code>
<code>python -m src.main calibrate analyze</code>
</div>

</body></html>"""
    out = Path("exports/cockpit.html")
    out.write_text(html, encoding="utf-8")
    console.print(f"[green]Cockpit: {out.resolve()}[/green]")
    return 0


def command_cockpit_open(_: argparse.Namespace) -> int:
    path = Path("exports/cockpit.html")
    if not path.exists():
        console.print("[yellow]Cockpit not generated yet. Run: cockpit export[/yellow]")
        return 1
    try:
        if os.name == "nt":
            os.startfile(str(path.resolve()))
        else:
            subprocess.run(["xdg-open", str(path.resolve())])
    except Exception as exc:
        console.print(f"[yellow]Could not open: {exc}[/yellow]")
        console.print(f"Open manually: {path.resolve()}")
        return 1
    return 0


def _fmt_salary(v: dict) -> str:
    sfrom = v.get("salary_from")
    sto = v.get("salary_to")
    curr = v.get("salary_currency") or ""
    if not sfrom and not sto:
        return "-"
    p = []
    if sfrom:
        p.append(str(sfrom))
    if sto:
        p.append(str(sto))
    return "–".join(p) + (f" {curr}" if curr else "")
