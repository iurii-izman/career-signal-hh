from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console

from ..data_quality import find_duplicates
from ..utils import json_loads

console = Console()


def _storage():
    from dotenv import load_dotenv

    from ..storage import Storage

    load_dotenv()
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


# ── Action plan helpers ────────────────────────────────────────────────────


def _action_cards(storage) -> list[dict]:
    """Return prioritized daily action plan cards."""
    cards: list[dict] = []

    # ── 1. No fresh search in 24h ──
    with storage.connect() as conn:
        last_run = conn.execute("SELECT MAX(started_at) FROM search_runs").fetchone()[0]
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    if not last_run or last_run < day_ago:
        cards.append(
            {
                "priority": "high",
                "title": "No search in 24h",
                "reason": f"Last run: {last_run[:19] if last_run else 'never'}",
                "command": "python -m src.main autopilot daily --backup-first",
            }
        )

    # ── 2. Strong match queue ──
    strong_queue = storage.list_queue(
        min_score=85, decisions=["strong_match"], new_only=True, limit=20
    )
    if strong_queue:
        cards.append(
            {
                "priority": "high",
                "title": f"{len(strong_queue)} new strong matches",
                "reason": "Top candidates ready for review",
                "command": "python -m src.main review next-best",
            }
        )

    # ── 3. Apply pack needed ──
    strong_all = storage.list_queue(min_score=85, decisions=["strong_match"], limit=5)
    apply_pack_exists = Path("exports/apply_packs/index.html").exists()
    if strong_all and not apply_pack_exists:
        cards.append(
            {
                "priority": "medium",
                "title": "Generate apply packs",
                "reason": f"{len(strong_all)} strong matches, no apply pack generated",
                "command": "python -m src.main apply-pack --top 5 --decision strong_match",
            }
        )

    # ── 4. Auto-hide bulk archive ──
    auto_hide = storage.list_queue(decisions=["auto_hide"], new_only=True, limit=9999)
    if len(auto_hide) >= 5:
        cards.append(
            {
                "priority": "medium",
                "title": f"{len(auto_hide)} auto-hide candidates",
                "reason": "Bulk archive low-quality matches",
                "command": "python -m src.main review bulk-archive --decision auto_hide --yes",
            }
        )

    # ── 5. DB backup needed ──
    backups = sorted(
        Path("backups").glob("vacancies_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    week_ago = (datetime.now() - timedelta(days=7)).timestamp()
    if not backups or backups[0].stat().st_mtime < week_ago:
        cards.append(
            {
                "priority": "medium",
                "title": "Database backup needed",
                "reason": "No backup in last 7 days",
                "command": "python -m src.main db backup",
            }
        )

    # ── 6. Duplicate clusters ──
    cluster_count = storage.count_clusters()
    if cluster_count > 0:
        cards.append(
            {
                "priority": "low",
                "title": f"{cluster_count} duplicate clusters",
                "reason": "Review deduplicated queue",
                "command": "python -m src.main review queue --dedupe --min-score 70",
            }
        )

    # ── 7. Calibration suggestions pending ──
    try:
        suggs = json.loads(Path("data/calibration_suggestions.json").read_text(encoding="utf-8"))
        pending = [s for s in suggs if s.get("status", "pending") == "pending"]
        if pending:
            cards.append(
                {
                    "priority": "low",
                    "title": f"{len(pending)} pending calibration suggestions",
                    "reason": "Review and apply or dismiss",
                    "command": "python -m src.main calibrate export",
                }
            )
    except (OSError, json.JSONDecodeError):
        pass

    return cards


def _render_action_cards(cards: list[dict]) -> str:
    if not cards:
        return "<p>All caught up! No actions needed today.</p>"

    priority_cls = {"high": "pri-high", "medium": "pri-medium", "low": "pri-low"}
    priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}

    html = '<div class="actions">'
    for c in cards:
        cls = priority_cls.get(c["priority"], "")
        emoji = priority_emoji.get(c["priority"], "")
        html += f"""<div class="action {cls}">
  <div class="action-head">{emoji} {c["title"]} <span class="pri-tag">{c["priority"]}</span></div>
  <div class="action-reason">{c["reason"]}</div>
  <code>{c["command"]}</code>
</div>"""
    html += "</div>"
    return html


# ── Queue improvements ─────────────────────────────────────────────────────


def _render_queue(storage, limit: int = 15) -> str:
    """Render enhanced queue with decision, risks, keywords, cluster badge, apply-pack link."""
    rows = storage.list_queue(min_score=70, new_only=True, limit=limit)

    if not rows:
        return "<p>No pending queue. Run autopilot daily or search.</p>"

    # Get cluster info for badges
    ids = [r["id"] for r in rows]
    cluster_map = storage.get_clusters_for_vacancies(ids) if ids else {}

    # Get matched keywords
    kw_map: dict[str, list[str]] = {}
    if ids:
        placeholders = ", ".join("?" for _ in ids)
        with storage.connect() as conn:
            kw_rows = conn.execute(
                f"SELECT vacancy_id, matched_keywords_json FROM score_details WHERE vacancy_id IN ({placeholders})",
                ids,
            ).fetchall()
        for row in kw_rows:
            keywords = json_loads(row["matched_keywords_json"], [])
            kw_map[row["vacancy_id"]] = [
                kw.get("keyword", "") for kw in keywords[:3] if kw.get("keyword")
            ]

    html = '<table class="queue"><tr><th>Score</th><th>Dec</th><th>Title</th><th>Company</th><th>Keywords</th><th>Risks</th><th>Actions</th></tr>'

    for q in rows:
        sid = q["id"]
        score = q.get("total_score", 0)
        name = (q.get("name") or "")[:35]
        emp = (q.get("employer_name") or "")[:22]
        decision = q.get("decision", "-")
        url = q.get("alternate_url", "")
        risks_raw = json_loads(q.get("risk_flags_json"), [])
        risks = ", ".join(str(r) for r in risks_raw[:2]) if risks_raw else "-"
        keywords = ", ".join(kw_map.get(sid, []))

        # Cluster badge
        cluster_badge = ""
        cinfo = cluster_map.get(sid)
        if cinfo:
            csize = cinfo.get("cluster_size", 2)
            cluster_badge = f' <span class="cluster-badge" title="Cluster {cinfo["cluster_id"]}">{csize} dupes</span>'

        # Apply-pack link
        ap_files = list(Path("exports/apply_packs").glob(f"{sid}_*.html"))
        ap_link = ""
        if ap_files:
            ap_link = (
                f' <a class="ap-link" href="../exports/apply_packs/{ap_files[0].name}">📄 pack</a>'
            )

        html += f"""<tr>
  <td class="sc">{score}</td>
  <td class="dec">{decision}</td>
  <td><a href="{url}">{name}</a>{cluster_badge}</td>
  <td class="emp">{emp}</td>
  <td class="kw">{keywords}</td>
  <td class="risk">{risks}</td>
  <td class="cmds">
    <code>review set {sid} --status interesting</code>
    {"<code>apply-pack " + sid + "</code>" if score >= 85 else ""}
    {"<code>review apply " + sid + " --date today</code>" if not q.get("applied_at") else ""}
    {ap_link}
  </td>
</tr>"""

    html += "</table>"
    return html


# ── Generated files awareness ──────────────────────────────────────────────


def _render_files_status() -> str:
    files = [
        ("Vacancies Report", "exports/vacancies_report.html", "python -m src.main export"),
        (
            "Analytics Report",
            "exports/analytics_report.html",
            "python -m src.main analytics export",
        ),
        ("Apply Packs", "exports/apply_packs/index.html", "python -m src.main apply-pack --top 5"),
        ("Data Quality", "exports/data_quality_report.html", "python -m src.main quality export"),
        (
            "Calibration Report",
            "exports/calibration_report.html",
            "python -m src.main calibrate export",
        ),
    ]

    rows = ""
    for name, path_str, cmd in files:
        p = Path(path_str)
        if p.exists():
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            rows += f"""<tr>
  <td><span class="file-ok">●</span> {name}</td>
  <td>{mtime}</td>
  <td><code>{cmd}</code></td>
</tr>"""
        else:
            rows += f"""<tr>
  <td><span class="file-miss">○</span> {name}</td>
  <td class="muted">not generated</td>
  <td><code>{cmd}</code></td>
</tr>"""

    return f"<table>{rows}</table>"


# ── Run history ─────────────────────────────────────────────────────────────


def _render_run_history(storage) -> str:
    with storage.connect() as conn:
        runs = conn.execute(
            "SELECT started_at, profile_name, query, found_count, loaded_count, error "
            "FROM search_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall()

    if not runs:
        return "<p>No search runs yet. Run a search to start.</p>"

    rows = ""
    for r in runs:
        ts = (r["started_at"] or "")[:19]
        profile = r["profile_name"] or "-"
        query = (r["query"] or "")[:40]
        found = r["found_count"] or 0
        loaded = r["loaded_count"] or 0
        error = r["error"] or ""
        err_cell = f'<span class="err">{error[:40]}</span>' if error else ""
        rows += f"""<tr>
  <td>{ts}</td><td>{profile}</td><td>{query}</td>
  <td>{found}</td><td>{loaded}</td><td>{err_cell}</td>
</tr>"""

    return f"<table><tr><th>Time</th><th>Profile</th><th>Query</th><th>Found</th><th>Loaded</th><th>Error</th></tr>{rows}</table>"


def _render_metric_cards(items: list[tuple[str, int]]) -> str:
    return '<div class="row">' + "".join(
        f'<div class="stat"><strong>{value}</strong><span>{label}</span></div>'
        for label, value in items
    ) + "</div>"


def _render_attention_items(items: list[dict]) -> str:
    if not items:
        return "<p>No immediate action context.</p>"
    html = '<div class="actions">'
    for item in items:
        kind = "Follow-up due" if item.get("kind") == "follow_up_due" else "Briefing needed"
        html += f"""<div class="action">
  <div class="action-head">{kind}: {item.get("name", "")}</div>
  <div class="action-reason">{item.get("employer_name", "")} · score {item.get("total_score", 0)} · status {item.get("review_status", "new")}</div>
</div>"""
    html += "</div>"
    return html


def _render_recent_activity(items: list[dict]) -> str:
    if not items:
        return "<p>No recent activity.</p>"
    rows = ""
    for item in items:
        rows += (
            "<tr>"
            f"<td>{(item.get('created_at') or '')[:19]}</td>"
            f"<td>{item.get('event_type', '')}</td>"
            f"<td>{item.get('name', '')[:50]}</td>"
            f"<td>{item.get('employer_name', '')[:28]}</td>"
            f"<td>{item.get('new_status', '') or '-'}</td>"
            "</tr>"
        )
    return (
        "<table><tr><th>Time</th><th>Event</th><th>Vacancy</th><th>Employer</th><th>Status</th></tr>"
        f"{rows}</table>"
    )


# ── Main export ────────────────────────────────────────────────────────────


def command_cockpit_export(_: argparse.Namespace) -> int:
    storage = _storage()
    now_ts = datetime.now(timezone.utc)
    now = now_ts.strftime("%Y-%m-%d %H:%M UTC")
    db_path = os.getenv("DB_PATH", "data/vacancies.sqlite")

    # Stats
    stats = storage.stats()
    total = stats["total"]
    remote = stats["remote"]
    operational = storage.get_operational_metrics()

    # Funnel
    funnel = {}
    for status in ["new", "interesting", "applied", "interview", "offer", "rejected", "archived"]:
        funnel[status] = len(storage.list_queue(min_score=0, status=status, limit=9999))

    # Data quality
    all_rows = storage.list_vacancies(limit=9999)
    _dup_clusters = find_duplicates(all_rows)  # keep call for side-effect check
    sample_count = sum(1 for r in all_rows if (r.get("id") or "").startswith("sample-"))
    missing_scores = sum(1 for r in all_rows if not r.get("total_score"))
    db_clusters = storage.count_clusters()
    db_dup_count = storage.count_duplicate_vacancies()
    db_aliases = storage.count_employer_aliases()

    # Action plan
    cards = _action_cards(storage)
    action_html = _render_action_cards(cards)

    # Enhanced queue
    queue_html = _render_queue(storage)

    # Files status
    files_html = _render_files_status()

    # Run history
    history_html = _render_run_history(storage)

    # Presets
    preset_rows = []
    for row in operational.get("preset_performance", []):
        preset_rows.append(row)

    preset_html = "<table><tr><th>Preset</th><th>Total</th><th>Avg</th><th>Strong</th><th>Briefed</th><th>Applied</th><th>Offer</th><th>Risky</th></tr>"
    for p in preset_rows:
        preset_html += (
            f"<tr><td>{p['preset']}</td><td>{p['total']}</td><td>{p['avg_score']:.0f}</td>"
            f"<td>{p['strong']}</td><td>{p['briefed']}</td><td>{p['applied']}</td>"
            f"<td>{p['offer']}</td><td>{p['risky']}</td></tr>"
        )
    preset_html += "</table>"

    pipeline_html = _render_metric_cards(
        [
            ("Sourced", operational.get("pipeline", {}).get("sourced", 0)),
            ("Scored", operational.get("pipeline", {}).get("scored", 0)),
            ("Shortlisted", operational.get("pipeline", {}).get("shortlisted", 0)),
            ("Briefed", operational.get("pipeline", {}).get("briefed", 0)),
            ("Drafted", operational.get("pipeline", {}).get("drafted", 0)),
            ("Applied", operational.get("pipeline", {}).get("applied", 0)),
            ("Interview", operational.get("pipeline", {}).get("interview", 0)),
            ("Offer", operational.get("pipeline", {}).get("offer", 0)),
        ]
    )
    queue_health_html = _render_metric_cards(
        [
            ("Pending New", operational.get("queue_health", {}).get("pending_new", 0)),
            ("Strong New", operational.get("queue_health", {}).get("strong_new", 0)),
            ("Missing Briefing", operational.get("queue_health", {}).get("missing_briefing", 0)),
            (
                "Interesting No Draft",
                operational.get("queue_health", {}).get("interesting_without_draft", 0),
            ),
            ("Follow-up Due", operational.get("queue_health", {}).get("follow_up_due", 0)),
            ("Risky Queue", operational.get("queue_health", {}).get("risky_queue", 0)),
            ("Outbox Pending", operational.get("queue_health", {}).get("outbox_pending", 0)),
            ("Outbox Failed", operational.get("queue_health", {}).get("outbox_failed", 0)),
        ]
    )
    risk_html = _render_metric_cards(
        [
            (bucket.get("label", bucket.get("key", "?")), bucket.get("count", 0))
            for bucket in operational.get("risk_buckets", [])
        ]
    )
    attention_html = _render_attention_items(operational.get("attention_items", []))
    activity_html = _render_recent_activity(operational.get("recent_activity", []))
    briefing_summary = operational.get("briefing_summary", {})
    outbox_summary = operational.get("outbox_summary", {})

    # Backup status
    backups_dir = Path("backups")
    latest_backup = "none"
    if backups_dir.exists():
        backups = sorted(
            backups_dir.glob("vacancies_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if backups:
            latest_backup = datetime.fromtimestamp(backups[0].stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )

    # Build HTML
    header_cards = f"""
    <div class="row">
      <div class="stat"><strong>{total}</strong><span>Total</span></div>
      <div class="stat"><strong>{funnel["new"]}</strong><span>New</span></div>
      <div class="stat"><strong>{funnel.get("applied", 0)}</strong><span>Applied</span></div>
      <div class="stat"><strong>{funnel.get("interview", 0)}</strong><span>Interview</span></div>
      <div class="stat"><strong>{funnel.get("offer", 0)}</strong><span>Offer</span></div>
      <div class="stat"><strong>{remote}</strong><span>Remote</span></div>
    </div>"""

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareerSignal HH Cockpit</title>
<style>
:root{{--bg:#0b1020;--panel:#141b2d;--line:#26324d;--text:#e8edf7;--muted:#9ba8bd;--accent:#67e8f9;--green:#4ade80;--yellow:#facc15;--red:#f87171}}
*{{box-sizing:border-box}} body{{background:var(--bg);color:var(--text);font:14px system-ui,sans-serif;max-width:1200px;margin:20px auto;padding:0 20px}}
h1{{color:var(--accent);font-size:24px}} h2{{color:#9bf6e8;font-size:18px;margin-top:30px;border-bottom:1px solid var(--line);padding-bottom:8px}}
.row{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}
.stat{{flex:1;min-width:95px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;text-align:center}}
.stat strong{{display:block;font-size:22px;color:var(--accent)}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
th,td{{padding:6px 8px;text-align:left;border-bottom:1px solid var(--line)}}
th{{color:#fde68a}} a{{color:#bfdbfe;text-decoration:none}} a:hover{{text-decoration:underline}}
code{{background:#10182a;padding:1px 6px;border-radius:4px;font-size:11px;color:#fda4af;white-space:nowrap}}
.meta{{color:var(--muted);font-size:12px;margin-bottom:20px}}
.muted{{color:var(--muted)}}
/* Actions */
.actions{{display:flex;flex-direction:column;gap:10px;margin:12px 0}}
.action{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 18px}}
.pri-high{{border-left:4px solid var(--red)}}
.pri-medium{{border-left:4px solid var(--yellow)}}
.pri-low{{border-left:4px solid var(--green)}}
.action-head{{font-weight:700;font-size:15px;margin-bottom:4px}}
.action-reason{{color:var(--muted);font-size:13px;margin-bottom:8px}}
.pri-tag{{font-size:11px;padding:2px 8px;border-radius:6px;margin-left:8px}}
.pri-high .pri-tag{{background:#4a2029;color:#fecdd3}}
.pri-medium .pri-tag{{background:#4a3b16;color:#fde68a}}
.pri-low .pri-tag{{background:#164e3b;color:#a7f3d0}}
/* Queue */
.queue .sc{{font-weight:700;font-size:15px;color:var(--accent)}}
.queue .dec{{font-size:11px}} .queue .emp{{color:var(--muted)}}
.queue .kw{{font-size:11px;color:#9bf6e8}} .queue .risk{{font-size:11px;color:#fda4af}}
.queue .cmds{{font-size:11px}} .queue .cmds code{{display:block;margin:2px 0;font-size:10px}}
.cluster-badge{{display:inline-block;background:#4a3b16;color:#fde68a;padding:1px 6px;border-radius:6px;font-size:11px;margin-left:4px}}
.ap-link{{color:var(--green);font-size:11px;margin-left:4px}}
/* Files */
.file-ok{{color:var(--green)}} .file-miss{{color:var(--muted)}}
.err{{color:var(--red);font-size:11px}}
</style></head><body>
<h1>🚀 CareerSignal HH Cockpit</h1>
<div class="meta">Generated: {now} · DB: {db_path} · {total} vacancies · {db_clusters} clusters · Latest backup: {latest_backup}</div>

{header_cards}

<h2>⚡ Today's Action Plan</h2>
{action_html}

<h2>📋 Today's Queue (new, score≥70, top 15)</h2>
{queue_html}

<h2>🧭 Pipeline</h2>
{pipeline_html}

<h2>🚦 Queue Health</h2>
{queue_health_html}

<h2>📊 Preset Performance</h2>
{preset_html if preset_rows else "<p>No preset data.</p>"}

<h2>⚠️ Risk Buckets</h2>
{risk_html}

<h2>📈 Review Funnel</h2>
<div class="row">{"".join(f'<div class="stat"><strong>{c}</strong><span>{k}</span></div>' for k, c in funnel.items())}</div>

<h2>🧠 Briefing & Sync</h2>
<div class="row">
  <div class="stat"><strong>{briefing_summary.get("saved", 0)}</strong><span>Briefings saved</span></div>
  <div class="stat"><strong>{briefing_summary.get("updated_7d", 0)}</strong><span>Briefings 7d</span></div>
  <div class="stat"><strong>{outbox_summary.get("counts", {}).get("pending", 0)}</strong><span>Outbox pending</span></div>
  <div class="stat"><strong>{outbox_summary.get("counts", {}).get("failed", 0)}</strong><span>Outbox failed</span></div>
</div>

<h2>🎯 Action Context</h2>
{attention_html}

<h2>📁 Generated Files</h2>
{files_html}

<h2>📜 Latest Search Runs</h2>
{history_html}

<h2>🕒 Recent Activity</h2>
{activity_html}

<h2>🔍 Data Quality</h2>
<div class="row">
  <div class="stat"><strong>{sample_count}</strong><span>Sample vacancies</span></div>
  <div class="stat"><strong>{missing_scores}</strong><span>Missing scores</span></div>
  <div class="stat"><strong>{db_clusters}</strong><span>Clusters (DB)</span></div>
  <div class="stat"><strong>{db_dup_count}</strong><span>Dup vacancies</span></div>
  <div class="stat"><strong>{db_aliases}</strong><span>Aliases</span></div>
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
