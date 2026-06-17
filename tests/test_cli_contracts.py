"""Contract tests — every CLI subcommand must parse without error."""

from __future__ import annotations

import pytest

from tests.helpers import parse_args

pytestmark = pytest.mark.no_network


# ── search ───────────────────────────────────────────────────────────────────


def test_search_dry_run_smoke_parses() -> None:
    args = parse_args(["search", "--dry-run", "--mode", "smoke"])
    assert args.dry_run is True
    assert args.mode == "smoke"


def test_search_normal_verbose_parses() -> None:
    args = parse_args(["search", "--mode", "normal", "--verbose", "--max-pages", "3"])
    assert args.mode == "normal"
    assert args.verbose is True
    assert args.max_pages == 3


def test_search_with_preset_parses() -> None:
    args = parse_args(["search", "--preset", "ai_rag_remote", "--remote-only"])
    assert args.preset == "ai_rag_remote"


# ── presets ──────────────────────────────────────────────────────────────────


def test_presets_list_parses() -> None:
    args = parse_args(["presets", "list"])
    assert args.presets_command == "list"


def test_presets_show_parses() -> None:
    args = parse_args(["presets", "show", "ai_rag_remote"])
    assert args.presets_command == "show"
    assert args.preset_name == "ai_rag_remote"


def test_presets_validate_parses() -> None:
    args = parse_args(["presets", "validate"])
    assert args.presets_command == "validate"


def test_presets_create_parses() -> None:
    args = parse_args(
        [
            "presets",
            "create",
            "test_preset",
            "--terms",
            "python llm",
            "--include",
            "python",
            "--description",
            "Test",
        ]
    )
    assert args.presets_command == "create"
    assert args.name == "test_preset"


# ── score ────────────────────────────────────────────────────────────────────


def test_score_explain_parses() -> None:
    args = parse_args(["score", "explain", "12345"])
    assert args.score_command == "explain"
    assert args.vacancy_id == "12345"


def test_score_rescore_parses() -> None:
    args = parse_args(["score", "rescore", "--preset", "ai_rag_remote", "--limit", "10"])
    assert args.score_command == "rescore"
    assert args.preset == "ai_rag_remote"
    assert args.limit == 10


# ── review ───────────────────────────────────────────────────────────────────


def test_review_list_parses() -> None:
    args = parse_args(["review", "list", "--status", "new", "--min-score", "70"])
    assert args.review_command == "list"
    assert args.status == "new"


def test_review_queue_parses() -> None:
    args = parse_args(["review", "queue", "--remote-only", "--dedupe", "--limit", "10"])
    assert args.review_command == "queue"
    assert args.remote_only is True
    assert args.dedupe is True


def test_review_draft_parses() -> None:
    args = parse_args(["review", "draft", "12345"])
    assert args.review_command == "draft"
    assert args.vacancy_id == "12345"


def test_review_bulk_interesting_parses() -> None:
    args = parse_args(["review", "bulk-interesting", "--min-score", "85", "--yes"])
    assert args.review_command == "bulk-interesting"
    assert args.min_score == 85
    assert args.yes is True


def test_review_bulk_reject_parses() -> None:
    args = parse_args(["review", "bulk-reject", "--max-score", "30", "--force"])
    assert args.review_command == "bulk-reject"


def test_review_bulk_archive_parses() -> None:
    args = parse_args(["review", "bulk-archive", "--decision", "auto_hide"])
    assert args.review_command == "bulk-archive"


# ── apply-pack ───────────────────────────────────────────────────────────────


def test_apply_pack_vacancy_id_parses() -> None:
    args = parse_args(["apply-pack", "12345"])
    assert args.vacancy_id == "12345"


def test_apply_pack_top_parses() -> None:
    args = parse_args(["apply-pack", "--top", "5", "--lang", "en", "--format", "md"])
    assert args.top == 5
    assert args.lang == "en"
    assert args.format == "md"


# ── analytics ────────────────────────────────────────────────────────────────


def test_analytics_summary_parses() -> None:
    args = parse_args(["analytics", "summary"])
    assert args.analytics_command == "summary"


def test_analytics_presets_parses() -> None:
    args = parse_args(["analytics", "presets"])
    assert args.analytics_command == "presets"


# ── calibrate ────────────────────────────────────────────────────────────────


def test_calibrate_analyze_parses() -> None:
    args = parse_args(["calibrate", "analyze"])
    assert args.calibrate_command == "analyze"


def test_calibrate_apply_parses() -> None:
    args = parse_args(["calibrate", "apply", "--suggestion-id", "1", "--yes"])
    assert args.calibrate_command == "apply"
    assert args.suggestion_id == "1"


# ── quality ──────────────────────────────────────────────────────────────────


def test_quality_duplicates_parses() -> None:
    args = parse_args(["quality", "duplicates"])
    assert args.quality_command == "duplicates"


def test_quality_cluster_parses() -> None:
    args = parse_args(["quality", "cluster"])
    assert args.quality_command == "cluster"


# ── cockpit ──────────────────────────────────────────────────────────────────


def test_cockpit_export_parses() -> None:
    args = parse_args(["cockpit", "export"])
    assert args.cockpit_command == "export"


def test_cockpit_open_parses() -> None:
    args = parse_args(["cockpit", "open"])
    assert args.cockpit_command == "open"


# ── maintenance ──────────────────────────────────────────────────────────────


def test_maintenance_report_parses() -> None:
    args = parse_args(["maintenance", "report"])
    assert args.maintenance_command == "report"


def test_maintenance_cleanup_parses() -> None:
    args = parse_args(["maintenance", "cleanup", "--dry-run"])
    assert args.maintenance_command == "cleanup"
    assert args.dry_run is True


def test_maintenance_cleanup_yes_parses() -> None:
    args = parse_args(["maintenance", "cleanup", "--yes"])
    assert args.yes is True


# ── scheduler ────────────────────────────────────────────────────────────────


def test_scheduler_status_parses() -> None:
    args = parse_args(["scheduler", "status"])
    assert args.scheduler_command == "status"


# ── health ───────────────────────────────────────────────────────────────────


def test_health_parses() -> None:
    args = parse_args(["health"])
    assert args.command == "health"


# ── db ───────────────────────────────────────────────────────────────────────


def test_db_info_parses() -> None:
    args = parse_args(["db", "info"])
    assert args.db_command == "info"


def test_db_migrate_parses() -> None:
    args = parse_args(["db", "migrate"])
    assert args.db_command == "migrate"


def test_db_integrity_parses() -> None:
    args = parse_args(["db", "integrity"])
    assert args.db_command == "integrity"


def test_db_backup_parses() -> None:
    args = parse_args(["db", "backup"])
    assert args.db_command == "backup"


# ── Simple commands ──────────────────────────────────────────────────────────


def test_top_parses() -> None:
    args = parse_args(["top"])
    assert args.command == "top"


def test_stats_parses() -> None:
    args = parse_args(["stats"])
    assert args.command == "stats"


def test_auth_check_parses() -> None:
    args = parse_args(["auth-check"])
    assert args.command == "auth-check"


def test_doctor_parses() -> None:
    args = parse_args(["doctor"])
    assert args.command == "doctor"


def test_version_parses() -> None:
    args = parse_args(["version"])
    assert args.command == "version"


def test_autopilot_daily_parses() -> None:
    args = parse_args(["autopilot", "daily", "--mode", "smoke"])
    assert args.autopilot_command == "daily"
    assert args.mode == "smoke"
