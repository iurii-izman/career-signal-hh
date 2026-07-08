"""Tests for SQLite migration system reliability."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src import db_migrations


def _empty_db(path: Path) -> sqlite3.Connection:
    """Return a connection to a fresh SQLite file at *path*."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ── Core migration behaviour ────────────────────────────────────────────────


def test_fresh_db_applies_all_migrations(tmp_path: Path) -> None:
    """A brand-new database should apply every migration successfully."""
    conn = _empty_db(tmp_path / "fresh.sqlite")
    try:
        result = db_migrations.apply_migrations(conn)

        assert result["applied"] == len(db_migrations.MIGRATIONS)
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert len(result["details"]) == len(db_migrations.MIGRATIONS)
        for d in result["details"]:
            assert d["status"] == "applied", f"Migration {d['version']} was not applied"

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "briefing_reports" in tables
        assert "vacancy_events" in tables
        assert "integration_outbox" in tables
        assert "hh_negotiation_messages" in tables
    finally:
        conn.close()


def test_second_run_skips_all_migrations(tmp_path: Path) -> None:
    """After all migrations are applied, a second run should skip everything."""
    conn = _empty_db(tmp_path / "skip.sqlite")
    try:
        # First pass — apply everything
        first = db_migrations.apply_migrations(conn)
        assert first["applied"] == len(db_migrations.MIGRATIONS)

        # Second pass — skip everything
        second = db_migrations.apply_migrations(conn)
        assert second["applied"] == 0
        assert second["skipped"] == len(db_migrations.MIGRATIONS)
        assert second["failed"] == 0
        for d in second["details"]:
            assert d["status"] == "skipped", f"Migration {d['version']} was not skipped"
    finally:
        conn.close()


def test_duplicate_column_does_not_fail(tmp_path: Path) -> None:
    """Migration 004 uses safe_add_column — calling it twice must succeed."""
    conn = _empty_db(tmp_path / "dup_col.sqlite")
    try:
        # Apply all migrations
        first = db_migrations.apply_migrations(conn)
        assert first["failed"] == 0

        # Manually invoke the Migration 004 callable again.
        # Because it uses safe_add_column, it should not raise.
        db_migrations._migration_004_add_work_format_flags(conn)
        db_migrations._migration_004_add_work_format_flags(conn)

        # Verify column still exists and has expected content
        info = conn.execute("PRAGMA table_info(score_details)").fetchall()
        cols = {r[1] for r in info}
        assert "work_format_flags_json" in cols
    finally:
        conn.close()


def test_invalid_sql_fails_and_not_marked_applied(tmp_path: Path) -> None:
    """A migration with invalid SQL must fail and NOT be recorded as applied."""
    conn = _empty_db(tmp_path / "invalid.sqlite")
    try:
        # Inject a bogus migration *after* the real ones
        bogus_version = 999
        bogus_name = "999_bogus_migration"
        original = db_migrations.MIGRATIONS.copy()
        try:
            db_migrations.MIGRATIONS.append(
                (bogus_version, bogus_name, "THIS IS NOT VALID SQL AT ALL")
            )

            result = db_migrations.apply_migrations(conn)

            # The bogus migration must be in the details with status "failed"
            failed_entries = [d for d in result["details"] if d["status"] == "failed"]
            assert len(failed_entries) == 1
            assert failed_entries[0]["version"] == bogus_version
            assert failed_entries[0]["name"] == bogus_name
            assert "error" in failed_entries[0] and failed_entries[0]["error"]
            assert result["failed"] == 1

            # schema_migrations must NOT contain the bogus entry
            rows = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (bogus_version,),
            ).fetchall()
            assert len(rows) == 0, "Bogus migration was recorded!"
        finally:
            db_migrations.MIGRATIONS[:] = original
    finally:
        conn.close()


def test_partial_rollback_on_multi_statement_failure(tmp_path: Path) -> None:
    """When a multi-statement migration fails, earlier DDL in the same
    migration must be rolled back."""
    conn = _empty_db(tmp_path / "partial.sqlite")
    try:
        original = db_migrations.MIGRATIONS.copy()
        try:
            # Replace migrations with a single multi-statement entry where
            # the first statement succeeds and the second fails.
            db_migrations.MIGRATIONS[:] = [
                (
                    100,
                    "100_partial_fail_test",
                    """
                    CREATE TABLE IF NOT EXISTS test_table_a (
                        id INTEGER PRIMARY KEY
                    );
                    THIS IS GARBAGE THAT WILL FAIL;
                    """,
                )
            ]

            result = db_migrations.apply_migrations(conn)

            # Must be failed
            assert result["failed"] == 1
            assert result["applied"] == 0

            # test_table_a must NOT exist (rolled back)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table_a'"
            ).fetchone()
            assert row is None, "test_table_a was not rolled back!"
        finally:
            db_migrations.MIGRATIONS[:] = original
    finally:
        conn.close()


# ── Integrity checks ────────────────────────────────────────────────────────


def test_integrity_detects_missing_work_format_flags(tmp_path: Path) -> None:
    """Extended integrity check must report work_format_flags_json as missing
    when the column does not exist."""
    conn = _empty_db(tmp_path / "no_wf.sqlite")
    try:
        # Create minimal tables so index references don't fail
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vacancies (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS scores (vacancy_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS vacancy_reviews (vacancy_id TEXT PRIMARY KEY);
        """)
        conn.commit()

        # Create score_details table *without* the column
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS score_details (
                vacancy_id TEXT PRIMARY KEY,
                preset_name TEXT,
                total_score INTEGER NOT NULL,
                decision TEXT NOT NULL,
                category_scores_json TEXT NOT NULL,
                matched_keywords_json TEXT NOT NULL,
                excluded_keywords_json TEXT NOT NULL,
                risk_flags_json TEXT NOT NULL,
                explanation_json TEXT NOT NULL,
                scored_at TEXT NOT NULL
            );
        """)
        conn.commit()

        # Also create required indexes that exist on relevant tables.
        # Skip indexes referencing columns we didn't create in minimal tables.
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_score_details_preset ON score_details(preset_name);
            CREATE INDEX IF NOT EXISTS idx_score_details_decision ON score_details(decision);
        """)
        conn.commit()

        result = db_migrations.check_integrity_extended(conn)
        assert result["score_details_has_wf_flags"] is False, (
            "Must detect missing work_format_flags_json"
        )
    finally:
        conn.close()


def test_integrity_schema_version_behind(tmp_path: Path) -> None:
    """Extended integrity must report current < expected version."""
    conn = _empty_db(tmp_path / "behind.sqlite")
    try:
        # Apply only the first migration
        db_migrations._ensure_schema_migrations_table(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (1, "001_initial_schema", "2025-01-01T00:00:00+00:00"),
        )
        conn.commit()

        result = db_migrations.check_integrity_extended(conn)
        assert result["current_schema_version"] == 1
        assert result["expected_schema_version"] > 1
    finally:
        conn.close()


# ── Data integrity after migration ──────────────────────────────────────────


def test_no_data_loss_after_migration(tmp_path: Path) -> None:
    """Applying migrations on an existing DB must not lose data."""
    conn = _empty_db(tmp_path / "nodataloss.sqlite")
    try:
        # Apply all migrations fresh
        db_migrations.apply_migrations(conn)

        # Insert test data
        now = "2025-06-15T12:00:00+00:00"
        conn.execute(
            "INSERT INTO vacancies (id, name, raw_json, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test-1", "Test Vacancy", "{}", now, now),
        )
        conn.execute(
            "INSERT INTO scores (vacancy_id, total_score, scored_at) VALUES (?, ?, ?)",
            ("test-1", 85, now),
        )
        conn.execute(
            "INSERT INTO score_details "
            "(vacancy_id, preset_name, total_score, decision, category_scores_json, "
            "matched_keywords_json, excluded_keywords_json, risk_flags_json, "
            "explanation_json, scored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-1", "default", 85, "strong_match", "{}", "[]", "[]", "[]", "{}", now),
        )
        conn.execute(
            "INSERT INTO vacancy_reviews (vacancy_id, status, updated_at) VALUES (?, ?, ?)",
            ("test-1", "interesting", now),
        )
        conn.commit()

        # Re-run migrations (simulates an existing DB)
        result = db_migrations.apply_migrations(conn)
        assert result["failed"] == 0

        # Verify all data is intact
        v = conn.execute("SELECT name FROM vacancies WHERE id='test-1'").fetchone()
        assert v and v["name"] == "Test Vacancy"

        s = conn.execute("SELECT total_score FROM scores WHERE vacancy_id='test-1'").fetchone()
        assert s and s["total_score"] == 85

        sd = conn.execute(
            "SELECT total_score FROM score_details WHERE vacancy_id='test-1'"
        ).fetchone()
        assert sd and sd["total_score"] == 85

        r = conn.execute("SELECT status FROM vacancy_reviews WHERE vacancy_id='test-1'").fetchone()
        assert r and r["status"] == "interesting"
    finally:
        conn.close()


# ── Helpers ─────────────────────────────────────────────────────────────────


def test_table_has_column(tmp_path: Path) -> None:
    conn = _empty_db(tmp_path / "has_col.sqlite")
    try:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()
        assert db_migrations.table_has_column(conn, "t", "a") is True
        assert db_migrations.table_has_column(conn, "t", "b") is False
    finally:
        conn.close()


def test_safe_add_column_idempotent(tmp_path: Path) -> None:
    conn = _empty_db(tmp_path / "safe_add.sqlite")
    try:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()

        db_migrations.safe_add_column(conn, "t", "b", "TEXT NOT NULL DEFAULT 'x'")
        assert db_migrations.table_has_column(conn, "t", "b") is True

        # Second call must not raise
        db_migrations.safe_add_column(conn, "t", "b", "TEXT NOT NULL DEFAULT 'x'")
        assert db_migrations.table_has_column(conn, "t", "b") is True
    finally:
        conn.close()


def test_safe_create_index(tmp_path: Path) -> None:
    conn = _empty_db(tmp_path / "safe_idx.sqlite")
    try:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()
        db_migrations.safe_create_index(conn, "CREATE INDEX IF NOT EXISTS idx_a ON t(a)")
        # Must not raise
        db_migrations.safe_create_index(conn, "CREATE INDEX IF NOT EXISTS idx_a ON t(a)")
        # Verify index exists
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_a'"
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()
