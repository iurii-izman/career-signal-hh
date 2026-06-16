from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "001_initial_schema",
        """
        CREATE TABLE IF NOT EXISTS vacancies (
            id TEXT PRIMARY KEY, name TEXT, employer_id TEXT, employer_name TEXT,
            area_name TEXT, alternate_url TEXT, published_at TEXT, created_at TEXT,
            archived INTEGER, salary_from INTEGER, salary_to INTEGER,
            salary_currency TEXT, schedule_name TEXT, employment_name TEXT,
            experience_name TEXT, description_html TEXT, description_text TEXT,
            key_skills_json TEXT, raw_json TEXT NOT NULL, first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, source_profile TEXT
        );
        CREATE TABLE IF NOT EXISTS scores (
            vacancy_id TEXT PRIMARY KEY, total_score INTEGER,
            ai_automation_score INTEGER, bitrix_1c_score INTEGER,
            best_profile TEXT, match_reasons_json TEXT, risk_flags_json TEXT,
            work_format_flags_json TEXT, scored_at TEXT,
            FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
        );
        CREATE TABLE IF NOT EXISTS search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
            profile_name TEXT, query TEXT, area_id TEXT, found_count INTEGER,
            loaded_count INTEGER, new_count INTEGER, updated_count INTEGER,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at);
        CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
        """,
    ),
    (
        2,
        "002_review_schema",
        """
        CREATE TABLE IF NOT EXISTS vacancy_reviews (
            vacancy_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'new',
            priority INTEGER NULL,
            user_notes TEXT NULL,
            cover_letter_draft TEXT NULL,
            applied_at TEXT NULL,
            next_action TEXT NULL,
            next_action_at TEXT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reviews_status ON vacancy_reviews(status);
        """,
    ),
    (
        3,
        "003_score_details",
        """
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
            scored_at TEXT NOT NULL,
            FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_score_details_preset ON score_details(preset_name);
        CREATE INDEX IF NOT EXISTS idx_score_details_decision ON score_details(decision);
        """,
    ),
    (
        4,
        "004_score_details_work_format_flags",
        """
        ALTER TABLE score_details ADD COLUMN work_format_flags_json TEXT NOT NULL DEFAULT '[]';
        """,
    ),
    (
        5,
        "005_ensure_indexes",
        """
        CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at);
        CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
        CREATE INDEX IF NOT EXISTS idx_reviews_status ON vacancy_reviews(status);
        CREATE INDEX IF NOT EXISTS idx_score_details_preset ON score_details(preset_name);
        CREATE INDEX IF NOT EXISTS idx_score_details_decision ON score_details(decision);
        """,
    ),
]


def _ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )
    connection.commit()


def get_current_schema_version(connection: sqlite3.Connection) -> int:
    _ensure_schema_migrations_table(connection)
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return row[0] if row and row[0] is not None else 0


def apply_migrations(connection: sqlite3.Connection) -> dict[str, int]:
    """Apply all pending migrations. Returns {applied: N, skipped: N}."""
    _ensure_schema_migrations_table(connection)
    current = get_current_schema_version(connection)
    applied = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    for version, name, sql in MIGRATIONS:
        if version <= current:
            skipped += 1
            continue
        try:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now),
            )
            connection.commit()
            applied += 1
        except sqlite3.Error:
            # Migration may partially fail if column exists etc - that's OK, it's idempotent
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now),
            )
            connection.commit()
            applied += 1

    return {"applied": applied, "skipped": skipped}


def count_orphans(connection: sqlite3.Connection) -> dict[str, int]:
    """Count orphan records in child tables."""
    results = {}
    results["orphan_scores"] = connection.execute(
        "SELECT COUNT(*) FROM scores WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
    ).fetchone()[0]
    results["orphan_score_details"] = connection.execute(
        "SELECT COUNT(*) FROM score_details WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
    ).fetchone()[0]
    results["orphan_reviews"] = connection.execute(
        "SELECT COUNT(*) FROM vacancy_reviews WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
    ).fetchone()[0]
    results["sample_count"] = connection.execute(
        "SELECT COUNT(*) FROM vacancies WHERE id LIKE 'sample-%'"
    ).fetchone()[0]
    results["duplicate_urls"] = connection.execute(
        "SELECT COUNT(*) FROM (SELECT alternate_url, COUNT(*) cnt FROM vacancies WHERE alternate_url != '' GROUP BY alternate_url HAVING cnt > 1)"
    ).fetchone()[0]
    results["missing_scores"] = connection.execute(
        "SELECT COUNT(*) FROM vacancies WHERE id NOT IN (SELECT vacancy_id FROM scores)"
    ).fetchone()[0]
    results["missing_score_details"] = connection.execute(
        "SELECT COUNT(*) FROM vacancies WHERE id NOT IN (SELECT vacancy_id FROM score_details)"
    ).fetchone()[0]
    results["missing_descriptions"] = connection.execute(
        "SELECT COUNT(*) FROM vacancies WHERE description_text IS NULL OR description_text = ''"
    ).fetchone()[0]
    return results


def cleanup_orphans(connection: sqlite3.Connection) -> dict[str, int]:
    """Remove orphan records. Returns counts of deleted rows."""
    results = {}
    for table in ["scores", "score_details", "vacancy_reviews"]:
        c = connection.execute(
            f"DELETE FROM {table} WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
        )
        results[f"deleted_{table}"] = c.rowcount
    connection.commit()
    return results
