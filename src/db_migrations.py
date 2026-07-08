from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

# ── Helpers ──────────────────────────────────────────────────────────────────


def table_has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if *table* already has *column*."""
    cols = [r[1] for r in connection.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def safe_add_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Add column only when it does not exist yet (fully idempotent)."""
    if not table_has_column(connection, table, column):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def safe_create_index(connection: sqlite3.Connection, index_sql: str) -> None:
    """
    Execute a CREATE INDEX IF NOT EXISTS statement safely.

    *index_sql* must already include IF NOT EXISTS — this helper adds no
    extra logic, it simply documents intent.
    """
    connection.execute(index_sql)


# ── Idempotent error classification ─────────────────────────────────────────

# These patterns signal that the migration was already applied (or an
# equivalent DDL already exists).  We treat them as a no-op success.
_IDEMPOTENT_PATTERNS = re.compile(r"duplicate column name|already exists", re.IGNORECASE)


def _is_idempotent_error(error: sqlite3.Error) -> bool:
    return bool(_IDEMPOTENT_PATTERNS.search(str(error)))


# ── Migration definitions ──────────────────────────────────────────────────

# Every entry is (version, name, sql_or_callable).
# *version* must be globally unique and monotonically increasing.

MigrationFn = Callable[[sqlite3.Connection], None]
MigrationEntry = tuple[int, str, str | MigrationFn]


def _migration_004_add_work_format_flags(connection: sqlite3.Connection) -> None:
    safe_add_column(
        connection,
        "score_details",
        "work_format_flags_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )


def _migration_007_add_confidence_noise(connection: sqlite3.Connection) -> None:
    safe_add_column(
        connection,
        "score_details",
        "confidence_score",
        "INTEGER NOT NULL DEFAULT 0",
    )
    safe_add_column(
        connection,
        "score_details",
        "noise_score",
        "INTEGER NOT NULL DEFAULT 0",
    )
    safe_add_column(
        connection,
        "score_details",
        "quality_flags_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )


def _migration_008_add_source_query(connection: sqlite3.Connection) -> None:
    safe_add_column(connection, "vacancies", "source_query", "TEXT")
    safe_create_index(
        connection,
        "CREATE INDEX IF NOT EXISTS idx_vacancies_source_profile_query ON vacancies(source_profile, source_query)",
    )


def _migration_009_add_briefing_reports(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS briefing_reports (
            vacancy_id TEXT NOT NULL,
            lang TEXT NOT NULL DEFAULT 'ru',
            score_total INTEGER NOT NULL DEFAULT 0,
            decision TEXT NOT NULL DEFAULT '',
            report_md TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(vacancy_id, lang),
            FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_briefing_reports_updated
        ON briefing_reports(updated_at DESC);
        """
    )


def _migration_010_add_evented_storage(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS vacancy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vacancy_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            old_status TEXT NULL,
            new_status TEXT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'local',
            FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_vacancy_events_vacancy_created
        ON vacancy_events(vacancy_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_vacancy_events_type_created
        ON vacancy_events(event_type, created_at DESC);

        CREATE TABLE IF NOT EXISTS integration_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            vacancy_id TEXT NULL,
            payload_json TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_integration_outbox_status_target
        ON integration_outbox(status, target, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_integration_outbox_vacancy
        ON integration_outbox(vacancy_id, created_at DESC);
        """
    )


MIGRATIONS: list[MigrationEntry] = [
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
            last_seen_at TEXT NOT NULL, source_profile TEXT, source_query TEXT
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
        _migration_004_add_work_format_flags,
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
    (
        6,
        "006_quality_tables",
        """
        CREATE TABLE IF NOT EXISTS employer_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL,
            alias TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(canonical_name, alias)
        );
        CREATE TABLE IF NOT EXISTS vacancy_clusters (
            cluster_id TEXT NOT NULL,
            vacancy_id TEXT NOT NULL,
            cluster_reason TEXT NOT NULL,
            similarity_score REAL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(cluster_id, vacancy_id)
        );
        CREATE INDEX IF NOT EXISTS idx_employer_aliases_canonical ON employer_aliases(canonical_name);
        CREATE INDEX IF NOT EXISTS idx_vacancy_clusters_vacancy ON vacancy_clusters(vacancy_id);
        CREATE INDEX IF NOT EXISTS idx_vacancy_clusters_cluster ON vacancy_clusters(cluster_id);
        """,
    ),
    (
        7,
        "007_confidence_noise_quality_flags",
        _migration_007_add_confidence_noise,
    ),
    (
        8,
        "008_vacancies_source_query",
        _migration_008_add_source_query,
    ),
    (
        9,
        "009_briefing_reports",
        _migration_009_add_briefing_reports,
    ),
    (
        10,
        "010_evented_storage",
        _migration_010_add_evented_storage,
    ),
]

# ── Schema migrations table ────────────────────────────────────────────────


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


def get_expected_schema_version() -> int:
    """Latest version declared in MIGRATIONS."""
    return MIGRATIONS[-1][0] if MIGRATIONS else 0


# ── Apply / rollback helpers ────────────────────────────────────────────────


def _apply_one_migration(
    connection: sqlite3.Connection, version: int, name: str, sql: str | MigrationFn
) -> None:
    """Execute a single migration.  Raises on unexpected errors."""
    if callable(sql):
        sql(connection)
    else:
        # Wrap multi-statement scripts in an explicit transaction.
        # executescript() issues an implicit COMMIT before running the
        # script, so we embed BEGIN/COMMIT inside the script itself.
        wrapped = f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;"
        try:
            connection.executescript(wrapped)
        except Exception:
            connection.rollback()
            raise


# ── Public API ──────────────────────────────────────────────────────────────


def apply_migrations(connection: sqlite3.Connection) -> dict[str, Any]:
    """
    Apply all pending migrations.

    Returns
    -------
    dict with keys:
        applied : int   — migrations successfully applied *now*
        skipped : int   — migrations already applied (version <= current)
        failed  : int   — migrations that failed with an unexpected error
        details : list  — per-migration status entries
            Each entry: {"version": int, "name": str, "status": str, "error": str|None}
            status is one of: "applied", "skipped", "failed"
    """
    _ensure_schema_migrations_table(connection)
    current = get_current_schema_version(connection)

    applied = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for version, name, sql in MIGRATIONS:
        if version <= current:
            skipped += 1
            details.append({"version": version, "name": name, "status": "skipped", "error": None})
            continue

        try:
            _apply_one_migration(connection, version, name, sql)

            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now),
            )
            connection.commit()
            applied += 1
            details.append({"version": version, "name": name, "status": "applied", "error": None})
        except sqlite3.Error as exc:
            if _is_idempotent_error(exc):
                # Known idempotent case: column already there,
                # index/table already exists.  Treat as success.
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, now),
                )
                connection.commit()
                applied += 1
                details.append(
                    {
                        "version": version,
                        "name": name,
                        "status": "applied",
                        "error": str(exc),
                    }
                )
            else:
                # Unexpected SQLite error — do NOT record migration.
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                failed += 1
                details.append(
                    {
                        "version": version,
                        "name": name,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
        except Exception as exc:
            # Any other unexpected error — do NOT record migration.
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            failed += 1
            details.append(
                {
                    "version": version,
                    "name": name,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return {"applied": applied, "skipped": skipped, "failed": failed, "details": details}


# ── Orphan detection & cleanup ──────────────────────────────────────────────


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
    results["orphan_briefing_reports"] = connection.execute(
        "SELECT COUNT(*) FROM briefing_reports WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
    ).fetchone()[0]
    results["orphan_vacancy_events"] = connection.execute(
        "SELECT COUNT(*) FROM vacancy_events WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
    ).fetchone()[0]
    results["orphan_outbox_vacancy_refs"] = connection.execute(
        "SELECT COUNT(*) FROM integration_outbox"
        " WHERE vacancy_id IS NOT NULL AND vacancy_id NOT IN (SELECT id FROM vacancies)"
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
    for table in ["scores", "score_details", "vacancy_reviews", "briefing_reports", "vacancy_events"]:
        c = connection.execute(
            f"DELETE FROM {table} WHERE vacancy_id NOT IN (SELECT id FROM vacancies)"
        )
        results[f"deleted_{table}"] = c.rowcount
    connection.commit()
    return results


# ── Extended integrity checks ───────────────────────────────────────────────


def check_integrity_extended(connection: sqlite3.Connection) -> dict[str, Any]:
    """
    Run extended integrity checks beyond PRAGMA integrity_check.

    Returns a dict with:
        schema_migrations_exists    : bool
        current_schema_version      : int
        expected_schema_version     : int
        score_details_has_wf_flags  : bool
        missing_indexes             : list[str]
        freelist_pages              : int
        freelist_bytes              : int
        vacuum_recommended          : bool
        pragma_integrity_ok         : bool
    """
    result: dict[str, Any] = {}

    # PRAGMA integrity_check
    row = connection.execute("PRAGMA integrity_check").fetchone()
    result["pragma_integrity_ok"] = row[0] == "ok" if row else False

    # schema_migrations table exists
    try:
        connection.execute("SELECT 1 FROM schema_migrations LIMIT 1")
        result["schema_migrations_exists"] = True
    except sqlite3.OperationalError:
        result["schema_migrations_exists"] = False

    # Schema version
    result["current_schema_version"] = get_current_schema_version(connection)
    result["expected_schema_version"] = get_expected_schema_version()

    # score_details has work_format_flags_json
    result["score_details_has_wf_flags"] = table_has_column(
        connection, "score_details", "work_format_flags_json"
    )

    # Required indexes
    required_indexes = [
        "idx_vacancies_published",
        "idx_scores_total",
        "idx_reviews_status",
        "idx_score_details_preset",
        "idx_score_details_decision",
        "idx_briefing_reports_updated",
        "idx_vacancy_events_vacancy_created",
        "idx_vacancy_events_type_created",
        "idx_integration_outbox_status_target",
        "idx_integration_outbox_vacancy",
    ]
    try:
        existing = [
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        existing = []
    result["missing_indexes"] = [idx for idx in required_indexes if idx not in existing]

    # VACUUM estimate
    freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    result["freelist_pages"] = freelist or 0
    result["freelist_bytes"] = (freelist or 0) * (page_size or 0)
    result["vacuum_recommended"] = (freelist or 0) > 100

    return result
