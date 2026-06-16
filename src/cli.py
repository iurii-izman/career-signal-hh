from __future__ import annotations

import argparse

from .commands.apply_pack import command_apply_pack
from .commands.auth import command_auth_check
from .commands.db import command_db_backup, command_db_info, command_db_purge_samples
from .commands.doctor import command_doctor
from .commands.export import command_export
from .commands.presets import command_presets_list, command_presets_show
from .commands.profiles import command_profiles
from .commands.review import (
    command_review_apply,
    command_review_bulk_archive,
    command_review_bulk_interesting,
    command_review_bulk_reject,
    command_review_bulk_set,
    command_review_list,
    command_review_next,
    command_review_next_best,
    command_review_note,
    command_review_queue,
    command_review_set,
)
from .commands.sample import command_sample_export
from .commands.score import command_score_explain, command_score_rescore
from .commands.search import command_search
from .commands.stats import command_stats, command_top
from .storage import REVIEW_STATUSES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="career-signal-hh")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    search = sub.add_parser("search")
    search.add_argument(
        "--mode",
        choices=["smoke", "normal", "deep"],
        default=None,
        help="Search mode: smoke (small, fast), normal (daily), deep (full). "
        "Default: normal.",
    )
    search.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max pages for the selected mode.",
    )
    search.add_argument(
        "--per-page",
        type=int,
        default=None,
        help="Override per-page for the selected mode.",
    )
    search.add_argument(
        "--profile", help="Use legacy search profile (from search_profiles.yaml)."
    )
    search.add_argument(
        "--preset", help="Use universal search preset (from search_presets.yaml)."
    )
    search.add_argument(
        "--adhoc",
        action="store_true",
        help="Create a temporary ad-hoc preset from --include/--exclude.",
    )
    search.add_argument(
        "--include",
        default=None,
        help="Comma-separated include keywords (for adhoc mode).",
    )
    search.add_argument(
        "--exclude",
        default=None,
        help="Comma-separated exclude keywords (for adhoc mode).",
    )
    search.add_argument(
        "--remote-only",
        action="store_true",
        default=None,
        help="Restrict to remote vacancies (default true for adhoc).",
    )
    search.add_argument(
        "--dry-run", action="store_true", help="Show estimate without API calls."
    )
    search.add_argument(
        "--force-details",
        action="store_true",
        help="Force refresh vacancy details even if already cached.",
    )
    search.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show per-page and per-vacancy progress during search.",
    )
    search.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (e.g. for deep mode).",
    )
    search.set_defaults(func=command_search)

    # --- apply-pack ---
    apply_pack = sub.add_parser("apply-pack")
    apply_pack.add_argument("vacancy_id", nargs="?", help="Vacancy ID.")
    apply_pack.add_argument(
        "--top", type=int, help="Generate packs for top N vacancies."
    )
    apply_pack.add_argument("--limit", type=int, help="Alias for --top.")
    apply_pack.add_argument("--decision", help="Filter by decision label.")
    apply_pack.add_argument("--preset", help="Filter by preset name.")
    apply_pack.add_argument("--min-score", type=int, default=0)
    apply_pack.add_argument("--lang", choices=["ru", "en"], default="ru")
    apply_pack.add_argument("--format", choices=["md", "html", "both"], default="both")
    apply_pack.add_argument(
        "--save-review", action="store_true", help="Save cover letter draft to review."
    )
    apply_pack.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing draft."
    )
    apply_pack.set_defaults(func=command_apply_pack)

    # --- score ---
    score_parser = sub.add_parser("score")
    score_sub = score_parser.add_subparsers(dest="score_command", required=True)
    score_explain = score_sub.add_parser("explain")
    score_explain.add_argument("vacancy_id", help="Vacancy ID to explain.")
    score_explain.set_defaults(func=command_score_explain)
    score_rescore = score_sub.add_parser("rescore")
    score_rescore.add_argument("--preset", help="Preset to use for rescoring.")
    score_rescore.add_argument("--limit", type=int, help="Max vacancies to rescore.")
    score_rescore.set_defaults(func=command_score_rescore)

    # --- presets ---
    presets_parser = sub.add_parser("presets")
    presets_sub = presets_parser.add_subparsers(dest="presets_command", required=True)
    presets_list = presets_sub.add_parser("list")
    presets_list.set_defaults(func=command_presets_list)
    presets_show = presets_sub.add_parser("show")
    presets_show.add_argument("preset_name", help="Preset name to show.")
    presets_show.set_defaults(func=command_presets_show)

    # --- export ---
    export = sub.add_parser("export")
    export.add_argument("--min-score", type=int, default=0)
    export.add_argument(
        "--profile", default=None, help="Filter by legacy profile name."
    )
    export.add_argument(
        "--preset", default=None, help="Filter by preset name (alias for --profile)."
    )
    export.add_argument("--days", type=int)
    export.set_defaults(func=command_export)

    # --- top ---
    sub.add_parser("top").set_defaults(func=command_top)

    # --- stats ---
    sub.add_parser("stats").set_defaults(func=command_stats)

    # --- auth-check ---
    sub.add_parser("auth-check").set_defaults(func=command_auth_check)

    # --- doctor ---
    sub.add_parser("doctor").set_defaults(func=command_doctor)

    # --- profiles ---
    sub.add_parser("profiles").set_defaults(func=command_profiles)

    # --- sample-export ---
    sample_export = sub.add_parser("sample-export")
    sample_export.add_argument(
        "--db",
        default=None,
        help="Database path (default: data/sample_vacancies.sqlite).",
    )
    sample_export.set_defaults(func=command_sample_export)

    # --- db ---
    db_parser = sub.add_parser("db")
    db_sub = db_parser.add_subparsers(dest="db_command", required=True)
    db_info = db_sub.add_parser("info")
    db_info.set_defaults(func=command_db_info)
    db_purge = db_sub.add_parser("purge-samples")
    db_purge.add_argument("-y", "--yes", action="store_true", help="Skip confirmation.")
    db_purge.set_defaults(func=command_db_purge_samples)
    db_backup = db_sub.add_parser("backup")
    db_backup.set_defaults(func=command_db_backup)

    # --- review ---
    review = sub.add_parser("review")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_list = review_sub.add_parser("list")
    review_list.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    review_list.add_argument("--min-score", type=int, default=0)
    review_list.add_argument("--limit", type=int, default=30)
    review_list.add_argument(
        "--profile", default=None, help="Filter by legacy profile name."
    )
    review_list.add_argument(
        "--preset", default=None, help="Filter by preset name (alias for --profile)."
    )
    review_list.set_defaults(func=command_review_list)
    review_set = review_sub.add_parser("set")
    review_set.add_argument("vacancy_id")
    review_set.add_argument("--status", required=True, choices=sorted(REVIEW_STATUSES))
    review_set.set_defaults(func=command_review_set)
    review_note = review_sub.add_parser("note")
    review_note.add_argument("vacancy_id")
    review_note.add_argument("--note", required=True)
    review_note.set_defaults(func=command_review_note)
    review_apply = review_sub.add_parser("apply")
    review_apply.add_argument("vacancy_id")
    review_apply.add_argument("--date", default="today")
    review_apply.set_defaults(func=command_review_apply)
    review_next = review_sub.add_parser("next")
    review_next.add_argument("vacancy_id")
    review_next.add_argument("--action", required=True)
    review_next.add_argument("--date", required=True)
    review_next.set_defaults(func=command_review_next)

    # --- review queue ---
    review_queue = review_sub.add_parser("queue")
    review_queue.add_argument(
        "--decision", help="Comma-separated decisions (default: strong_match,queue)"
    )
    review_queue.add_argument("--min-score", type=int, default=0)
    review_queue.add_argument("--preset")
    review_queue.add_argument("--profile", default=None)
    review_queue.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    review_queue.add_argument("--limit", type=int, default=20)
    review_queue.add_argument("--remote-only", action="store_true")
    review_queue.add_argument("--with-salary", action="store_true")
    review_queue.add_argument("--hide-risk", action="store_true")
    review_queue.add_argument("--new-only", action="store_true")
    review_queue.set_defaults(func=command_review_queue)

    # --- review next-best ---
    review_next_best = review_sub.add_parser("next-best")
    review_next_best.set_defaults(func=command_review_next_best)

    # --- bulk archive ---
    bulk_archive = review_sub.add_parser("bulk-archive")
    bulk_archive.add_argument("--decision", default="auto_hide")
    bulk_archive.add_argument("--force", action="store_true")
    bulk_archive.add_argument("-y", "--yes", action="store_true")
    bulk_archive.set_defaults(func=command_review_bulk_archive)

    # --- bulk reject ---
    bulk_reject = review_sub.add_parser("bulk-reject")
    bulk_reject.add_argument("--max-score", type=int, default=35)
    bulk_reject.add_argument("--force", action="store_true")
    bulk_reject.add_argument("-y", "--yes", action="store_true")
    bulk_reject.set_defaults(func=command_review_bulk_reject)

    # --- bulk interesting ---
    bulk_interesting = review_sub.add_parser("bulk-interesting")
    bulk_interesting.add_argument("--min-score", type=int, default=85)
    bulk_interesting.add_argument("--decision", default="strong_match")
    bulk_interesting.add_argument("--force", action="store_true")
    bulk_interesting.add_argument("-y", "--yes", action="store_true")
    bulk_interesting.set_defaults(func=command_review_bulk_interesting)

    # --- bulk set ---
    bulk_set = review_sub.add_parser("bulk-set")
    bulk_set.add_argument(
        "--new-status", required=True, choices=sorted(REVIEW_STATUSES)
    )
    bulk_set.add_argument("--min-score", type=int)
    bulk_set.add_argument("--max-score", type=int)
    bulk_set.add_argument("--decision")
    bulk_set.add_argument("--preset")
    bulk_set.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    bulk_set.add_argument("--force", action="store_true")
    bulk_set.add_argument("-y", "--yes", action="store_true")
    bulk_set.set_defaults(func=command_review_bulk_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))
