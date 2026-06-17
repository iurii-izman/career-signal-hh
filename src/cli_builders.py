"""Parser builder functions for CareerSignal HH CLI.

Each function takes an argparse subparser object and registers its arguments.
"""

from __future__ import annotations

import argparse

from .commands import (
    analytics,
    apply_pack,
    auth,
    autopilot,
    calibrate,
    campaigns,
    cockpit,
    db,
    doctor,
    export,
    health,
    import_vacancy,
    maintenance,
    presets,
    profiles,
    quality,
    review,
    sample,
    scheduler,
    score,
    search,
    search_lab,
    stats,
    version_cmd,
    wizard,
)
from .storage import REVIEW_STATUSES


def build_search_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search")
    p.add_argument(
        "--mode",
        choices=["smoke", "normal", "deep"],
        default=None,
        help="Search mode: smoke (small, fast), normal (daily), deep (full). Default: normal.",
    )
    p.add_argument("--max-pages", type=int, default=None)
    p.add_argument("--per-page", type=int, default=None)
    p.add_argument("--profile", help="Use legacy search profile.")
    p.add_argument("--preset", help="Use universal search preset.")
    p.add_argument("--adhoc", action="store_true")
    p.add_argument("--include", default=None)
    p.add_argument("--exclude", default=None)
    p.add_argument("--remote-only", action="store_true", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force-details", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-y", "--yes", action="store_true")
    p.set_defaults(func=search.command_search)


def build_apply_pack_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("apply-pack")
    p.add_argument("vacancy_id", nargs="?", help="Vacancy ID.")
    p.add_argument("--top", type=int)
    p.add_argument("--limit", type=int)
    p.add_argument("--decision")
    p.add_argument("--preset")
    p.add_argument("--min-score", type=int, default=0)
    p.add_argument("--lang", choices=["ru", "en"], default="ru")
    p.add_argument("--format", choices=["md", "html", "both"], default="both")
    p.add_argument("--style", choices=["short", "medium", "detailed"], default="medium")
    p.add_argument("--template", help="Override template (e.g. ai_rag_remote)")
    p.add_argument("--save-review", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=apply_pack.command_apply_pack)


def build_autopilot_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("autopilot")
    ps = p.add_subparsers(dest="autopilot_command", required=True)
    d = ps.add_parser("daily")
    d.add_argument("--mode", choices=["smoke", "normal"], default="normal")
    d.add_argument("--preset")
    d.add_argument("--skip-auth-check", action="store_true")
    d.add_argument("--skip-search", action="store_true")
    d.add_argument("--skip-rescore", action="store_true")
    d.add_argument("--skip-export", action="store_true")
    d.add_argument("--skip-queue", action="store_true")
    d.add_argument("--queue-limit", type=int, default=20)
    d.add_argument("--min-score", type=int, default=70)
    d.add_argument("--backup-first", action="store_true")
    d.add_argument("--allow-deep", action="store_true")
    d.add_argument("--ignore-doctor-warnings", action="store_true")
    d.add_argument("-y", "--yes", action="store_true")
    d.set_defaults(func=autopilot.command_autopilot_daily)
    s = ps.add_parser("status")
    s.set_defaults(func=autopilot.command_autopilot_status)


def build_analytics_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("analytics")
    ps = p.add_subparsers(dest="analytics_command", required=True)
    ps.add_parser("summary").set_defaults(func=analytics.command_analytics_summary)
    ps.add_parser("skills").set_defaults(func=analytics.command_analytics_skills)
    ps.add_parser("employers").set_defaults(func=analytics.command_analytics_employers)
    ps.add_parser("salary").set_defaults(func=analytics.command_analytics_salary)
    ps.add_parser("presets").set_defaults(func=analytics.command_analytics_presets)
    ps.add_parser("funnel").set_defaults(func=analytics.command_analytics_funnel)
    ps.add_parser("export").set_defaults(func=analytics.command_analytics_export)


def build_score_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("score")
    ps = p.add_subparsers(dest="score_command", required=True)
    e = ps.add_parser("explain")
    e.add_argument("vacancy_id")
    e.set_defaults(func=score.command_score_explain)
    r = ps.add_parser("rescore")
    r.add_argument("--preset")
    r.add_argument("--limit", type=int)
    r.set_defaults(func=score.command_score_rescore)


def build_presets_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("presets")
    ps = p.add_subparsers(dest="presets_command", required=True)
    ps.add_parser("list").set_defaults(func=presets.command_presets_list)
    s = ps.add_parser("show")
    s.add_argument("preset_name")
    s.set_defaults(func=presets.command_presets_show)
    ps.add_parser("validate").set_defaults(func=presets.command_presets_validate)
    c = ps.add_parser("create")
    c.add_argument("name")
    c.add_argument("--terms", required=True)
    c.add_argument("--include")
    c.add_argument("--exclude")
    c.add_argument("--description")
    c.add_argument("--remote-only", action="store_true", default=True)
    c.add_argument("--overwrite", action="store_true")
    c.set_defaults(func=presets.command_presets_create)
    cl = ps.add_parser("clone")
    cl.add_argument("source")
    cl.add_argument("new_name")
    cl.add_argument("--overwrite", action="store_true")
    cl.set_defaults(func=presets.command_presets_clone)
    for name, fn in [
        ("add-term", presets.command_presets_add_term),
        ("remove-term", presets.command_presets_remove_term),
        ("add-include", presets.command_presets_add_include),
        ("add-exclude", presets.command_presets_add_exclude),
    ]:
        x = ps.add_parser(name)
        x.add_argument("name")
        x.add_argument("keyword" if "include" in name or "exclude" in name else "term")
        x.set_defaults(func=fn)
    for name, fn in [
        ("disable", presets.command_presets_disable),
        ("enable", presets.command_presets_enable),
    ]:
        x = ps.add_parser(name)
        x.add_argument("name")
        x.set_defaults(func=fn)
    sa = ps.add_parser("save-adhoc")
    sa.add_argument("name")
    sa.add_argument("--include", required=True)
    sa.add_argument("--exclude", default="")
    sa.add_argument("--remote-only", action="store_true", default=True)
    sa.add_argument("--overwrite", action="store_true")
    sa.set_defaults(func=presets.command_presets_save_adhoc)


def build_export_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("export")
    p.add_argument("--min-score", type=int, default=0)
    p.add_argument("--profile", default=None)
    p.add_argument("--preset", default=None)
    p.add_argument("--days", type=int)
    p.set_defaults(func=export.command_export)


def build_db_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("db")
    ps = p.add_subparsers(dest="db_command", required=True)
    ps.add_parser("info").set_defaults(func=db.command_db_info)
    ps.add_parser("migrate").set_defaults(func=db.command_db_migrate)
    ps.add_parser("integrity").set_defaults(func=db.command_db_integrity)
    ps.add_parser("vacuum").set_defaults(func=db.command_db_vacuum)
    ps.add_parser("optimize").set_defaults(func=db.command_db_optimize)
    pu = ps.add_parser("purge-samples")
    pu.add_argument("-y", "--yes", action="store_true")
    pu.set_defaults(func=db.command_db_purge_samples)
    co = ps.add_parser("cleanup-orphans")
    co.add_argument("-y", "--yes", action="store_true")
    co.set_defaults(func=db.command_db_cleanup_orphans)
    ps.add_parser("backup").set_defaults(func=db.command_db_backup)


def build_review_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("review")
    ps = p.add_subparsers(dest="review_command", required=True)
    rl = ps.add_parser("list")
    rl.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    rl.add_argument("--min-score", type=int, default=0)
    rl.add_argument("--limit", type=int, default=30)
    rl.add_argument("--profile", default=None)
    rl.add_argument("--preset", default=None)
    rl.set_defaults(func=review.command_review_list)
    for name, fn, args in [
        (
            "set",
            review.command_review_set,
            [
                ("vacancy_id", {}),
                ("--status", {"required": True, "choices": sorted(REVIEW_STATUSES)}),
            ],
        ),
        ("note", review.command_review_note, [("vacancy_id", {}), ("--note", {"required": True})]),
        (
            "apply",
            review.command_review_apply,
            [("vacancy_id", {}), ("--date", {"default": "today"})],
        ),
        (
            "next",
            review.command_review_next,
            [("vacancy_id", {}), ("--action", {"required": True}), ("--date", {"required": True})],
        ),
    ]:
        x = ps.add_parser(name)
        for arg_name, kwargs in args:
            x.add_argument(arg_name, **kwargs)
        x.set_defaults(func=fn)
    # Queue
    q = ps.add_parser("queue")
    q.add_argument("--decision")
    q.add_argument("--min-score", type=int, default=0)
    q.add_argument("--preset")
    q.add_argument("--profile", default=None)
    q.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    q.add_argument("--limit", type=int, default=20)
    q.add_argument("--remote-only", action="store_true")
    q.add_argument("--with-salary", action="store_true")
    q.add_argument("--hide-risk", action="store_true")
    q.add_argument("--new-only", action="store_true")
    q.add_argument("--dedupe", action="store_true", help="Show only best per duplicate cluster")
    q.set_defaults(func=review.command_review_queue)
    ps.add_parser("next-best").set_defaults(func=review.command_review_next_best)
    # Draft management
    dr = ps.add_parser("draft")
    dr.add_argument("vacancy_id")
    dr.set_defaults(func=review.command_review_draft)
    cd = ps.add_parser("clear-draft")
    cd.add_argument("vacancy_id")
    cd.add_argument("-y", "--yes", action="store_true")
    cd.set_defaults(func=review.command_review_clear_draft)
    # Bulk
    for name, fn, extra in [
        (
            "bulk-archive",
            review.command_review_bulk_archive,
            [("--decision", {"default": "auto_hide"})],
        ),
        (
            "bulk-reject",
            review.command_review_bulk_reject,
            [("--max-score", {"type": int, "default": 35})],
        ),
        (
            "bulk-interesting",
            review.command_review_bulk_interesting,
            [
                ("--min-score", {"type": int, "default": 85}),
                ("--decision", {"default": "strong_match"}),
            ],
        ),
    ]:
        b = ps.add_parser(name)
        for a, kw in extra:
            b.add_argument(a, **kw)
        b.add_argument("--force", action="store_true")
        b.add_argument("-y", "--yes", action="store_true")
        b.set_defaults(func=fn)
    bs = ps.add_parser("bulk-set")
    bs.add_argument("--new-status", required=True, choices=sorted(REVIEW_STATUSES))
    bs.add_argument("--min-score", type=int)
    bs.add_argument("--max-score", type=int)
    bs.add_argument("--decision")
    bs.add_argument("--preset")
    bs.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    bs.add_argument("--force", action="store_true")
    bs.add_argument("-y", "--yes", action="store_true")
    bs.set_defaults(func=review.command_review_bulk_set)


def build_all_parsers(sub: argparse._SubParsersAction) -> None:
    build_search_parser(sub)
    build_apply_pack_parser(sub)
    build_autopilot_parser(sub)
    build_analytics_parser(sub)
    build_score_parser(sub)
    build_presets_parser(sub)
    build_export_parser(sub)
    build_db_parser(sub)
    build_review_parser(sub)
    build_calibrate_parser(sub)
    build_quality_parser(sub)
    build_cockpit_parser(sub)
    build_scheduler_parser(sub)
    build_maintenance_parser(sub)
    build_wizard_parser(sub)
    build_search_lab_parser(sub)
    build_campaigns_parser(sub)
    build_import_parser(sub)

    # Simple parsers
    sub.add_parser("top").set_defaults(func=stats.command_top)
    sub.add_parser("stats").set_defaults(func=stats.command_stats)
    sub.add_parser("auth-check").set_defaults(func=auth.command_auth_check)
    sub.add_parser("doctor").set_defaults(func=doctor.command_doctor)
    sub.add_parser("health").set_defaults(func=health.command_health)
    sub.add_parser("profiles").set_defaults(func=profiles.command_profiles)
    sp = sub.add_parser("sample-export")
    sp.add_argument("--db", default=None)
    sp.set_defaults(func=sample.command_sample_export)
    sub.add_parser("version").set_defaults(func=version_cmd.command_version)


def build_calibrate_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("calibrate")
    ps = p.add_subparsers(dest="calibrate_command", required=True)
    ps.add_parser("analyze").set_defaults(func=calibrate.command_calibrate_analyze)
    s = ps.add_parser("suggest")
    s.add_argument("--preset")
    s.set_defaults(func=calibrate.command_calibrate_suggest)
    a = ps.add_parser("apply")
    a.add_argument("--preset", help="Preset name (detected from suggestion if omitted)")
    a.add_argument("--suggestion-id", required=True)
    a.add_argument("-y", "--yes", action="store_true")
    a.set_defaults(func=calibrate.command_calibrate_apply)
    d = ps.add_parser("dismiss")
    d.add_argument("--suggestion-id", required=True)
    d.set_defaults(func=calibrate.command_calibrate_dismiss)
    ps.add_parser("export").set_defaults(func=calibrate.command_calibrate_export)


def build_quality_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("quality")
    ps = p.add_subparsers(dest="quality_command", required=True)
    ps.add_parser("duplicates").set_defaults(func=quality.command_quality_duplicates)
    ps.add_parser("cluster").set_defaults(func=quality.command_quality_cluster)
    ps.add_parser("report").set_defaults(func=quality.command_quality_report)
    ps.add_parser("export").set_defaults(func=quality.command_quality_export)


def build_cockpit_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("cockpit")
    ps = p.add_subparsers(dest="cockpit_command", required=True)
    ps.add_parser("export").set_defaults(func=cockpit.command_cockpit_export)
    ps.add_parser("open").set_defaults(func=cockpit.command_cockpit_open)


def build_scheduler_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("scheduler")
    ps = p.add_subparsers(dest="scheduler_command", required=True)
    ps.add_parser("print-windows-task").set_defaults(
        func=scheduler.command_scheduler_print_windows_task
    )
    ps.add_parser("status").set_defaults(func=scheduler.command_scheduler_status)


def build_maintenance_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("maintenance")
    ps = p.add_subparsers(dest="maintenance_command", required=True)
    ps.add_parser("report").set_defaults(func=maintenance.command_maintenance_report)
    c = ps.add_parser("cleanup")
    c.add_argument(
        "--dry-run", action="store_true", default=False, help="Preview only, no deletion"
    )
    c.add_argument("-y", "--yes", action="store_true", help="Execute deletion")
    c.set_defaults(func=maintenance.command_maintenance_cleanup)


def build_wizard_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("wizard")
    ps = p.add_subparsers(dest="wizard_command", required=False)

    # wizard (no subcommand — menu)
    m = ps.add_parser("menu")
    m.add_argument("--plan", action="store_true")
    m.set_defaults(func=wizard.command_wizard)

    # wizard first-run
    fr = ps.add_parser("first-run")
    fr.add_argument("--plan", action="store_true")
    fr.set_defaults(func=wizard.command_wizard_first_run)

    # wizard daily
    d = ps.add_parser("daily")
    d.add_argument("--plan", action="store_true")
    d.add_argument("--mode", choices=["smoke", "normal"], default="normal")
    d.add_argument("-y", "--yes", action="store_true")
    d.set_defaults(func=wizard.command_wizard_daily)

    # wizard improve
    imp = ps.add_parser("improve")
    imp.add_argument("--plan", action="store_true")
    imp.add_argument("-y", "--yes", action="store_true")
    imp.set_defaults(func=wizard.command_wizard_improve)

    # wizard apply
    ap = ps.add_parser("apply")
    ap.add_argument("--plan", action="store_true")
    ap.set_defaults(func=wizard.command_wizard_apply)

    # Set default handler for bare 'wizard' (no subcommand)
    p.set_defaults(func=wizard.command_wizard, wizard_command="menu")


def build_search_lab_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("search-lab")
    ps = p.add_subparsers(dest="search_lab_command", required=True)

    t = ps.add_parser("terms")
    t.add_argument("--preset", required=True)
    t.set_defaults(func=search_lab.command_search_lab_terms)

    s = ps.add_parser("suggest-terms")
    s.add_argument("--preset", required=True)
    s.set_defaults(func=search_lab.command_search_lab_suggest_terms)

    c = ps.add_parser("compare")
    c.add_argument("--preset-a", required=True)
    c.add_argument("--preset-b", required=True)
    c.set_defaults(func=search_lab.command_search_lab_compare)

    d = ps.add_parser("dry-plan")
    d.add_argument("--preset", required=True)
    d.set_defaults(func=search_lab.command_search_lab_dry_plan)

    ps.add_parser("export").set_defaults(func=search_lab.command_search_lab_export)


def build_campaigns_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("campaigns")
    ps = p.add_subparsers(dest="campaigns_command", required=True)

    ps.add_parser("list").set_defaults(func=campaigns.command_campaigns_list)

    s = ps.add_parser("show")
    s.add_argument("name")
    s.set_defaults(func=campaigns.command_campaigns_show)

    d = ps.add_parser("daily")
    d.add_argument("name")
    d.add_argument("--skip-auth-check", action="store_true")
    d.add_argument("--skip-search", action="store_true")
    d.set_defaults(func=campaigns.command_campaigns_daily)

    q = ps.add_parser("queue")
    q.add_argument("name")
    q.set_defaults(func=campaigns.command_campaigns_queue)

    ap = ps.add_parser("apply-pack")
    ap.add_argument("name")
    ap.add_argument("--top", type=int, default=5)
    ap.set_defaults(func=campaigns.command_campaigns_apply_pack)


def build_import_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import")
    ps = p.add_subparsers(dest="import_command", required=True)

    v = ps.add_parser("vacancy")
    v.add_argument("--title", required=True)
    v.add_argument("--company", required=True)
    v.add_argument("--url", required=True)
    v.add_argument("--area", default="")
    v.add_argument("--description", default="")
    v.add_argument("--salary-from", type=int, default=None)
    v.add_argument("--salary-to", type=int, default=None)
    v.add_argument("--currency", default="")
    v.add_argument("--schedule", default="")
    v.add_argument("--preset")
    v.add_argument("--notes", default="")
    v.set_defaults(func=import_vacancy.command_import_vacancy)

    c = ps.add_parser("csv")
    c.add_argument("path")
    c.set_defaults(func=import_vacancy.command_import_csv)

    j = ps.add_parser("jsonl")
    j.add_argument("path")
    j.set_defaults(func=import_vacancy.command_import_jsonl)

    t = ps.add_parser("text-file")
    t.add_argument("path")
    t.set_defaults(func=import_vacancy.command_import_text_file)
