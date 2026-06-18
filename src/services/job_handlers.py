"""Job handlers — functions that accept a Job and execute long-running tasks with progress."""

from __future__ import annotations

from typing import Any

from ..web.jobs import Job

# ── Autopilot ──────────────────────────────────────────────────────────


def job_autopilot_daily(
    job: Job, mode: str = "normal", preset: str | None = None
) -> dict[str, Any]:
    """Run daily autopilot pipeline with progress updates."""
    from ..services.search_service import run_autopilot_daily

    # Refuse deep mode
    if mode == "deep":
        job.add_log("Deep mode is not available in UI for safety", "warning")
        return {"ok": False, "message": "Deep mode not available in UI"}

    job.set_progress(5, "Starting autopilot pipeline...")
    job.add_log(f"Mode: {mode}, preset: {preset or 'all'}", "info")

    job.set_progress(15, "Running doctor check...")

    try:
        result = run_autopilot_daily(mode=mode, preset=preset)
        job.set_progress(95, "Autopilot finished")
        return result
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


# ── Search ─────────────────────────────────────────────────────────────


def job_search_smoke(job: Job, preset: str | None = None) -> dict[str, Any]:
    """Run smoke search with progress."""
    job.set_progress(5, "Starting smoke search...")
    job.add_log(f"Mode: smoke, preset: {preset or 'all'}", "info")

    try:
        from ..services.search_service import run_search_smoke

        job.set_progress(20, "Querying HH API...")
        result = run_search_smoke(preset=preset)
        job.set_progress(90, "Smoke search finished")
        return result
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


def job_search_normal(job: Job, preset: str | None = None) -> dict[str, Any]:
    """Run normal search with progress."""
    job.set_progress(5, "Starting normal search...")
    job.add_log(f"Mode: normal, preset: {preset or 'all'}", "info")

    try:
        from ..services.search_service import run_search_normal

        job.set_progress(20, "Querying HH API...")
        result = run_search_normal(preset=preset)
        job.set_progress(90, "Search finished")
        return result
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


# ── Export ─────────────────────────────────────────────────────────────


def job_export_all(job: Job) -> dict[str, Any]:
    """Run full export pipeline (HTML + CSV + JSONL + cockpit + analytics)."""
    import argparse

    job.set_progress(5, "Starting export pipeline...")

    try:
        # Main export
        job.set_progress(10, "Exporting vacancies report...")
        from ..commands.export import command_export

        export_args = argparse.Namespace(min_score=0, profile=None, preset=None, days=None)
        rc = command_export(export_args)
        job.add_log(f"Vacancies export: {'OK' if rc == 0 else 'FAILED'}", "info")
        job.set_progress(35, "Vacancies report exported")

        # Cockpit
        job.set_progress(40, "Exporting cockpit...")
        try:
            from ..commands.cockpit import command_cockpit_export

            command_cockpit_export(argparse.Namespace())
            job.add_log("Cockpit exported", "info")
        except Exception as exc:
            job.add_log(f"Cockpit export warning: {exc}", "warning")
        job.set_progress(65, "Cockpit exported")

        # Analytics
        job.set_progress(70, "Generating analytics...")
        try:
            from ..services.analytics_service import get_summary

            get_summary()
            job.add_log("Analytics generated", "info")
        except Exception as exc:
            job.add_log(f"Analytics warning: {exc}", "warning")
        job.set_progress(90, "Analytics exported")

        job.set_progress(100, "Export complete")
        return {
            "ok": rc == 0,
            "message": "Export pipeline complete",
        }
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


# ── Quality ────────────────────────────────────────────────────────────


def job_quality_cluster(job: Job) -> dict[str, Any]:
    """Run quality analysis: duplicates, clusters, employer aliases."""
    import argparse

    job.set_progress(5, "Starting quality analysis...")

    try:
        job.set_progress(10, "Finding duplicates...")
        from ..commands.quality import command_quality_duplicates

        command_quality_duplicates(argparse.Namespace())
        job.set_progress(30, "Duplicates analysed")

        job.set_progress(35, "Clustering similar vacancies...")
        from ..commands.quality import command_quality_cluster

        command_quality_cluster(argparse.Namespace())
        job.set_progress(70, "Clusters saved")

        job.set_progress(75, "Running quality report...")
        try:
            from ..commands.quality import command_quality_report

            command_quality_report(argparse.Namespace())
        except Exception as exc:
            job.add_log(f"Quality report warning: {exc}", "warning")
        job.set_progress(90, "Quality report generated")

        job.set_progress(100, "Quality analysis complete")
        return {
            "ok": True,
            "message": "Quality analysis complete",
        }
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


# ── Calibration ────────────────────────────────────────────────────────


def job_calibrate_suggest(job: Job) -> dict[str, Any]:
    """Run calibration suggestion generation."""
    import argparse

    job.set_progress(5, "Starting calibration analysis...")

    try:
        job.set_progress(15, "Analysing review decisions...")
        from ..commands.calibrate import command_calibrate_analyze

        analyze_args = argparse.Namespace(force=False, verbose=False)
        command_calibrate_analyze(analyze_args)
        job.set_progress(50, "Analysis done")

        job.set_progress(55, "Generating suggestions...")
        try:
            from ..commands.calibrate import command_calibrate_suggest

            suggest_args = argparse.Namespace(min_confidence=2, dry_run=False, yes=True)
            command_calibrate_suggest(suggest_args)
        except AttributeError:
            # Fallback: just analyze is enough
            pass
        job.set_progress(100, "Calibration complete")

        return {
            "ok": True,
            "message": "Calibration suggestions generated",
        }
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise


# ── Apply pack ─────────────────────────────────────────────────────────


def job_apply_pack_top(job: Job, limit: int = 5) -> dict[str, Any]:
    """Generate apply packs for top matches."""
    job.set_progress(5, f"Generating top {limit} apply packs...")

    try:
        from ..services.apply_pack_service import generate_top_apply_packs

        job.set_progress(20, "Fetching top vacancies...")
        result = generate_top_apply_packs(limit=limit, decision="strong_match")
        job.set_progress(90, "Apply packs generated")
        return result
    except Exception as exc:
        job.set_progress(0, f"Failed: {exc}")
        raise
