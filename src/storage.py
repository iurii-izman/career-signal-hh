from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import db_migrations  # noqa: E402 — circular-safe, used in __init__
from .models import ScoreDetails, ScoreResult, Vacancy
from .utils import json_dumps, json_loads

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS score_details (
    vacancy_id TEXT PRIMARY KEY,
    preset_name TEXT,
    total_score INTEGER NOT NULL,
    confidence_score INTEGER NOT NULL DEFAULT 0,
    noise_score INTEGER NOT NULL DEFAULT 0,
    decision TEXT NOT NULL,
    category_scores_json TEXT NOT NULL,
    matched_keywords_json TEXT NOT NULL,
    excluded_keywords_json TEXT NOT NULL,
    risk_flags_json TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL DEFAULT '[]',
    work_format_flags_json TEXT NOT NULL DEFAULT '[]',
    explanation_json TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
);
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
    profile_name TEXT, query TEXT, area_id TEXT, found_count INTEGER,
    loaded_count INTEGER, new_count INTEGER, updated_count INTEGER,
    error TEXT
);
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
CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
CREATE INDEX IF NOT EXISTS idx_score_details_preset ON score_details(preset_name);
CREATE INDEX IF NOT EXISTS idx_score_details_decision ON score_details(decision);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON vacancy_reviews(status);
"""

REVIEW_STATUSES = {
    "new",
    "interesting",
    "maybe",
    "rejected",
    "applied",
    "interview",
    "offer",
    "archived",
}

VACANCY_COLUMNS = [
    "id",
    "name",
    "employer_id",
    "employer_name",
    "area_name",
    "alternate_url",
    "published_at",
    "created_at",
    "archived",
    "salary_from",
    "salary_to",
    "salary_currency",
    "schedule_name",
    "employment_name",
    "experience_name",
    "description_html",
    "description_text",
    "key_skills_json",
    "raw_json",
    "first_seen_at",
    "last_seen_at",
    "source_profile",
    "source_query",
]


class Storage:
    def __init__(self, path: str = "data/vacancies.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            db_migrations.apply_migrations(connection)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _require_vacancy(self, vacancy_id: str) -> None:
        if not self.vacancy_exists(vacancy_id):
            raise ValueError(f"Вакансия с id={vacancy_id} не найдена.")

    @staticmethod
    def _validate_review_status(status: str) -> str:
        normalized = status.strip().lower()
        if normalized not in REVIEW_STATUSES:
            allowed = ", ".join(sorted(REVIEW_STATUSES))
            raise ValueError(f"Недопустимый review status={status!r}. Допустимы: {allowed}.")
        return normalized

    def get_review(self, vacancy_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM vacancy_reviews WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()
        if row:
            return dict(row)
        return {
            "vacancy_id": vacancy_id,
            "status": "new",
            "priority": None,
            "user_notes": None,
            "cover_letter_draft": None,
            "applied_at": None,
            "next_action": None,
            "next_action_at": None,
            "updated_at": None,
        }

    def upsert_review(self, vacancy_id: str, **fields: Any) -> dict[str, Any]:
        self._require_vacancy(vacancy_id)
        allowed_fields = {
            "status",
            "priority",
            "user_notes",
            "cover_letter_draft",
            "applied_at",
            "next_action",
            "next_action_at",
        }
        unknown = set(fields) - allowed_fields
        if unknown:
            raise ValueError(f"Неизвестные review-поля: {', '.join(sorted(unknown))}.")
        if "status" in fields:
            fields["status"] = self._validate_review_status(str(fields["status"]))
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO vacancy_reviews (vacancy_id, status, updated_at)
                VALUES (?, 'new', ?)
                ON CONFLICT(vacancy_id) DO NOTHING
                """,
                (vacancy_id, now),
            )
            if fields:
                assignments = ", ".join(f"{field} = ?" for field in fields)
                connection.execute(
                    f"UPDATE vacancy_reviews SET {assignments}, updated_at = ? "
                    "WHERE vacancy_id = ?",
                    [*fields.values(), now, vacancy_id],
                )
        return self.get_review(vacancy_id)

    def set_review_status(self, vacancy_id: str, status: str) -> dict[str, Any]:
        return self.upsert_review(vacancy_id, status=status)

    def set_review_note(self, vacancy_id: str, note: str) -> dict[str, Any]:
        return self.upsert_review(vacancy_id, user_notes=note)

    def mark_applied(self, vacancy_id: str, applied_at: str) -> dict[str, Any]:
        return self.upsert_review(vacancy_id, status="applied", applied_at=applied_at)

    def set_next_action(self, vacancy_id: str, action: str, next_action_at: str) -> dict[str, Any]:
        return self.upsert_review(vacancy_id, next_action=action, next_action_at=next_action_at)

    def vacancy_exists(self, vacancy_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
        return row is not None

    def touch_vacancy(
        self,
        vacancy_id: str,
        source_profile: str | None = None,
        source_query: str | None = None,
    ) -> bool:
        """Update last_seen_at and optionally refresh source attribution fields.

        Returns True if the vacancy exists and was updated, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        updates = ["last_seen_at = ?"]
        params: list[Any] = [now]
        if source_profile is not None:
            updates.append("source_profile = ?")
            params.append(source_profile)
        if source_query is not None:
            updates.append("source_query = ?")
            params.append(source_query)
        params.append(vacancy_id)
        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE vacancies SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            return cursor.rowcount > 0

    def get_vacancy_description(self, vacancy_id: str) -> str | None:
        """Return description_text for a vacancy, or None if not found."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT description_text FROM vacancies WHERE id = ?",
                (vacancy_id,),
            ).fetchone()
        return row["description_text"] if row else None

    def detail_needed(
        self,
        vacancy_id: str,
        *,
        force: bool = False,
        refresh_days: int | None = None,
    ) -> bool:
        """Decide whether a detail API fetch is needed for this vacancy.

        Returns True if:
        - force is True (always refresh)
        - vacancy is new (not in DB)
        - description_text is empty
        - last_seen_at is older than refresh_days
        """
        if force:
            return True

        with self.connect() as connection:
            row = connection.execute(
                "SELECT description_text, last_seen_at FROM vacancies WHERE id = ?",
                (vacancy_id,),
            ).fetchone()

        if row is None:
            return True

        desc = row["description_text"] or ""
        if not desc.strip():
            return True

        if refresh_days is not None and refresh_days > 0:
            last_seen = row["last_seen_at"]
            if last_seen:
                try:
                    last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    return False
                cutoff = datetime.now(timezone.utc) - timedelta(days=refresh_days)
                if last_dt < cutoff:
                    return True

        return False

    def find_by_url(self, url: str) -> str | None:
        """Return vacancy ID for a given alternate_url, or None."""
        if not url:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM vacancies WHERE alternate_url = ?", (url,)
            ).fetchone()
        return row["id"] if row else None

    def upsert_vacancy(self, vacancy: Vacancy) -> bool:
        is_new = not self.vacancy_exists(vacancy.id)
        values = vacancy.model_dump()
        values["archived"] = int(vacancy.archived)
        values["key_skills_json"] = json_dumps(vacancy.key_skills)
        values.pop("key_skills")
        values.pop("snippet_requirement")
        values.pop("snippet_responsibility")
        placeholders = ", ".join("?" for _ in VACANCY_COLUMNS)
        updates = ", ".join(
            f"{column}=excluded.{column}"
            for column in VACANCY_COLUMNS
            if column not in {"id", "first_seen_at"}
        )
        sql = (
            f"INSERT INTO vacancies ({', '.join(VACANCY_COLUMNS)}) "
            f"VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        with self.connect() as connection:
            connection.execute(sql, [values[column] for column in VACANCY_COLUMNS])
        return is_new

    def upsert_score(self, score: ScoreResult) -> None:
        values = score.model_dump()
        values["match_reasons_json"] = json_dumps(values.pop("match_reasons"))
        values["risk_flags_json"] = json_dumps(values.pop("risk_flags"))
        values["work_format_flags_json"] = json_dumps(values.pop("work_format_flags"))
        columns = list(values)
        updates = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "vacancy_id"
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO scores ({', '.join(columns)}) VALUES "
                f"({', '.join('?' for _ in columns)}) "
                f"ON CONFLICT(vacancy_id) DO UPDATE SET {updates}",
                [values[column] for column in columns],
            )

    def upsert_score_details(self, details: ScoreDetails) -> None:
        """Insert or update score_details for a vacancy."""
        values = details.model_dump()
        values["category_scores_json"] = json_dumps(values.pop("category_scores"))
        values["matched_keywords_json"] = json_dumps(
            [kw.model_dump() for kw in details.matched_keywords]
        )
        values.pop("matched_keywords", None)
        values["excluded_keywords_json"] = json_dumps(
            [kw.model_dump() for kw in details.excluded_keywords]
        )
        values.pop("excluded_keywords", None)
        values["risk_flags_json"] = json_dumps(values.pop("risk_flags"))
        values["quality_flags_json"] = json_dumps(values.pop("quality_flags"))
        values["work_format_flags_json"] = json_dumps(values.pop("work_format_flags"))
        values["explanation_json"] = json_dumps(values.pop("explanation"))
        columns = list(values)
        updates = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != "vacancy_id"
        )
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO score_details ({', '.join(columns)}) VALUES "
                f"({', '.join('?' for _ in columns)}) "
                f"ON CONFLICT(vacancy_id) DO UPDATE SET {updates}",
                [values[column] for column in columns],
            )

    def get_score_details(self, vacancy_id: str) -> dict[str, Any] | None:
        """Return score_details row as dict, or None."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM score_details WHERE vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_vacancy(self, vacancy_id: str) -> dict[str, Any] | None:
        """Return a full vacancy row as dict, or None."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_vacancy_full(self, vacancy_id: str) -> dict[str, Any] | None:
        """Return vacancy with scores, score_details, and review joined."""
        with self.connect() as connection:
            row = connection.execute(
                """SELECT v.*, s.total_score, s.best_profile, s.risk_flags_json,
                   s.match_reasons_json, s.work_format_flags_json,
                   sd.decision, sd.preset_name, sd.matched_keywords_json,
                   sd.excluded_keywords_json, sd.category_scores_json,
                   COALESCE(r.status, 'new') review_status,
                   r.priority, r.user_notes, r.applied_at
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                WHERE v.id = ?""",
                (vacancy_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_vacancies_for_rescore(
        self, limit: int | None = None, preset: str | None = None
    ) -> list[dict[str, Any]]:
        """Return vacancies that can be rescored. Optionally filter by source_profile."""
        where = ["COALESCE(v.archived, 0) = 0"]
        params: list[Any] = []
        if preset:
            where.append("v.source_profile = ?")
            params.append(preset)
        sql = "SELECT v.* FROM vacancies v WHERE " + " AND ".join(where)
        sql += " ORDER BY v.last_seen_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def add_search_run(self, run: dict[str, Any]) -> None:
        columns = list(run)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO search_runs ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [run[column] for column in columns],
            )

    def list_vacancies(
        self,
        min_score: int = 0,
        profile: str | None = None,
        days: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where = ["COALESCE(v.archived, 0) = 0", "COALESCE(s.total_score, 0) >= ?"]
        params: list[Any] = [min_score]
        if profile:
            where.append(
                "(s.best_profile = ? OR (? = 'ai_automation' AND s.ai_automation_score >= 15) "
                "OR (? = 'bitrix_1c' AND s.bitrix_1c_score >= 15))"
            )
            params.extend([profile, profile, profile])
        if days is not None:
            where.append("datetime(v.published_at) >= datetime('now', ?)")
            params.append(f"-{days} days")
        sql = f"""
            SELECT v.*, s.total_score, s.ai_automation_score, s.bitrix_1c_score,
                   s.best_profile, s.match_reasons_json, s.risk_flags_json,
                   s.work_format_flags_json, s.scored_at,
                   sd.decision, sd.preset_name,
                   sd.category_scores_json, sd.matched_keywords_json,
                   sd.excluded_keywords_json,
                   COALESCE(r.status, 'new') review_status,
                   r.priority, r.user_notes, r.cover_letter_draft,
                   r.applied_at, r.next_action, r.next_action_at,
                   r.updated_at review_updated_at
            FROM vacancies v LEFT JOIN scores s ON s.vacancy_id = v.id
            LEFT JOIN score_details sd ON sd.vacancy_id = v.id
            LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(s.total_score, 0) DESC, v.published_at DESC
        """
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def list_reviewed_vacancies(
        self,
        status: str | None = None,
        min_score: int = 0,
        limit: int = 30,
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        where = ["COALESCE(s.total_score, 0) >= ?"]
        params: list[Any] = [min_score]
        if status:
            where.append("COALESCE(r.status, 'new') = ?")
            params.append(self._validate_review_status(status))
        if profile:
            where.append(
                "(s.best_profile = ? OR (? = 'ai_automation' AND "
                "s.ai_automation_score >= 15) OR (? = 'bitrix_1c' AND "
                "s.bitrix_1c_score >= 15))"
            )
            params.extend([profile, profile, profile])
        params.append(limit)
        sql = f"""
            SELECT v.id, v.name, v.employer_name, v.area_name, v.alternate_url,
                   COALESCE(s.total_score, 0) total_score, s.best_profile,
                   COALESCE(r.status, 'new') review_status,
                   r.priority, r.user_notes, r.applied_at,
                   r.next_action, r.next_action_at,
                   COALESCE(r.updated_at, v.last_seen_at) review_updated_at
            FROM vacancies v
            LEFT JOIN scores s ON s.vacancy_id = v.id
            LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(r.updated_at, v.last_seen_at) DESC,
                     COALESCE(s.total_score, 0) DESC
            LIMIT ?
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            scalar = connection.execute(
                """SELECT COUNT(*) total,
                   COALESCE(SUM(CASE WHEN datetime(first_seen_at) >= datetime('now','-1 day') THEN 1 ELSE 0 END), 0) new_24h,
                   COALESCE(AVG(COALESCE(total_score,0)), 0) avg_score,
                   COALESCE(SUM(CASE WHEN work_format_flags_json LIKE '%remote%' THEN 1 ELSE 0 END), 0) remote,
                   COALESCE(SUM(CASE WHEN salary_from IS NOT NULL OR salary_to IS NOT NULL THEN 1 ELSE 0 END), 0) with_salary
                   FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id"""
            ).fetchone()
            employers = connection.execute(
                "SELECT employer_name name, COUNT(*) count FROM vacancies "
                "GROUP BY employer_name ORDER BY count DESC LIMIT 10"
            ).fetchall()
            areas = connection.execute(
                "SELECT area_name name, COUNT(*) count FROM vacancies "
                "GROUP BY area_name ORDER BY count DESC LIMIT 10"
            ).fetchall()
            profiles = connection.execute(
                "SELECT best_profile name, COUNT(*) count FROM scores "
                "GROUP BY best_profile ORDER BY count DESC"
            ).fetchall()
        return {
            **dict(scalar),
            "employers": [dict(row) for row in employers],
            "areas": [dict(row) for row in areas],
            "profiles": [dict(row) for row in profiles],
        }

    # ------------------------------------------------------------------
    # Review queue methods
    # ------------------------------------------------------------------

    REVIEW_PROTECTED_STATUSES = {"applied", "interview", "offer"}

    def list_queue(
        self,
        *,
        min_score: int = 0,
        max_score: int | None = None,
        decision: str | None = None,
        decisions: list[str] | None = None,
        preset: str | None = None,
        status: str | None = None,
        limit: int = 20,
        remote_only: bool = False,
        with_salary: bool = False,
        hide_risk: bool = False,
        new_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Flexible queue query with score, decision, preset, status filters."""
        where = ["COALESCE(v.archived, 0) = 0"]
        params: list[Any] = []

        if min_score:
            where.append("COALESCE(s.total_score, 0) >= ?")
            params.append(min_score)

        if max_score is not None:
            where.append("COALESCE(s.total_score, 0) <= ?")
            params.append(max_score)

        if decision:
            where.append("sd.decision = ?")
            params.append(decision)
        elif decisions:
            placeholders = ", ".join("?" for _ in decisions)
            where.append(f"sd.decision IN ({placeholders})")
            params.extend(decisions)

        if preset:
            where.append("(s.best_profile = ? OR sd.preset_name = ?)")
            params.extend([preset, preset])

        if status:
            where.append("COALESCE(r.status, 'new') = ?")
            params.append(self._validate_review_status(status))

        if new_only:
            where.append("COALESCE(r.status, 'new') = 'new'")

        if remote_only:
            where.append("s.work_format_flags_json LIKE '%remote%'")

        if with_salary:
            where.append("(v.salary_from IS NOT NULL OR v.salary_to IS NOT NULL)")

        if hide_risk:
            where.append("(s.risk_flags_json IS NULL OR s.risk_flags_json = '[]')")

        params.append(limit)

        sql = f"""
            SELECT v.id, v.name, v.employer_name, v.area_name, v.alternate_url,
                   v.salary_from, v.salary_to, v.salary_currency,
                   v.schedule_name, v.published_at,
                   COALESCE(s.total_score, 0) total_score,
                   s.best_profile, s.risk_flags_json,
                   COALESCE(sd.decision, 'unknown') decision,
                   COALESCE(r.status, 'new') review_status,
                   r.priority, r.user_notes, r.applied_at,
                   r.next_action, r.next_action_at
            FROM vacancies v
            LEFT JOIN scores s ON s.vacancy_id = v.id
            LEFT JOIN score_details sd ON sd.vacancy_id = v.id
            LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(s.total_score, 0) DESC, v.published_at DESC
            LIMIT ?
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # Data quality -- clusters and employer aliases
    # ------------------------------------------------------------------

    def replace_vacancy_clusters(self, clusters: list[dict]) -> None:
        """Replace all vacancy_clusters rows with *clusters*."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("DELETE FROM vacancy_clusters")
            for c in clusters:
                for vid in c.get("vacancy_ids", []):
                    connection.execute(
                        "INSERT INTO vacancy_clusters"
                        " (cluster_id, vacancy_id, cluster_reason, similarity_score, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            c["cluster_id"],
                            vid,
                            c.get("reason", c.get("cluster_reason", "")),
                            c.get("similarity") or c.get("similarity_score"),
                            now,
                        ),
                    )

    def replace_employer_aliases(self, aliases: dict[str, list[str]]) -> None:
        """Replace employer_aliases table."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("DELETE FROM employer_aliases")
            for canonical, variants in aliases.items():
                for variant in variants:
                    connection.execute(
                        "INSERT OR IGNORE INTO employer_aliases"
                        " (canonical_name, alias, created_at) VALUES (?, ?, ?)",
                        (canonical, variant, now),
                    )

    def get_cluster_for_vacancy(self, vacancy_id: str) -> dict[str, Any] | None:
        """Return cluster info for a vacancy or None."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT vc.*, COUNT(*) OVER (PARTITION BY vc.cluster_id) cluster_size"
                " FROM vacancy_clusters vc WHERE vc.vacancy_id = ?",
                (vacancy_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_clusters_for_vacancies(self, vacancy_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return {vacancy_id: cluster_info} for a batch of IDs."""
        if not vacancy_ids:
            return {}
        placeholders = ", ".join("?" for _ in vacancy_ids)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT vc.*, sub.cnt cluster_size"
                f" FROM vacancy_clusters vc"
                f" JOIN (SELECT cluster_id, COUNT(*) cnt FROM vacancy_clusters"
                f" GROUP BY cluster_id) sub ON sub.cluster_id = vc.cluster_id"
                f" WHERE vc.vacancy_id IN ({placeholders})",
                vacancy_ids,
            ).fetchall()
        return {row["vacancy_id"]: dict(row) for row in rows}

    def list_clusters(self) -> list[dict[str, Any]]:
        """Return all clusters grouped by cluster_id with counts."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT vc.cluster_id, vc.cluster_reason,"
                " COUNT(vc.vacancy_id) vacancy_count,"
                " GROUP_CONCAT(vc.vacancy_id) vacancy_ids,"
                " MAX(vc.similarity_score) similarity"
                " FROM vacancy_clusters vc"
                " GROUP BY vc.cluster_id"
                " ORDER BY vacancy_count DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_employer_aliases(self) -> list[dict[str, Any]]:
        """Return employer alias groups."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT canonical_name, GROUP_CONCAT(alias) aliases"
                " FROM employer_aliases"
                " GROUP BY canonical_name"
                " ORDER BY canonical_name"
            ).fetchall()
        return [dict(row) for row in rows]

    def count_clusters(self) -> int:
        """Return number of distinct clusters."""
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(DISTINCT cluster_id) FROM vacancy_clusters"
            ).fetchone()[0]

    def count_duplicate_vacancies(self) -> int:
        """Return total number of vacancies that belong to any cluster."""
        with self.connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM vacancy_clusters").fetchone()[0]

    def count_employer_aliases(self) -> int:
        """Return number of employer alias groups."""
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(DISTINCT canonical_name) FROM employer_aliases"
            ).fetchone()[0]

    # ── Search Lab analytics ───────────────────────────────────────────────

    def search_term_performance(self, preset_name: str) -> list[dict[str, Any]]:
        """Return per-search-term analytics for a preset.

        For each distinct query in search_runs for this profile,
        join with vacancy scores and reviews to compute quality metrics.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT
                    sr.query AS term,
                    COUNT(DISTINCT sr.id) AS total_runs,
                    MAX(sr.found_count) AS max_found,
                    MAX(sr.loaded_count) AS max_loaded,
                    COUNT(DISTINCT v.id) AS vacancy_count,
                    ROUND(AVG(COALESCE(s.total_score, 0)), 1) AS avg_score,
                    SUM(CASE WHEN sd.decision = 'strong_match' THEN 1 ELSE 0 END) AS strong_count,
                    SUM(CASE WHEN sd.decision = 'queue' THEN 1 ELSE 0 END) AS queue_count,
                    SUM(CASE WHEN COALESCE(r.status, 'new') IN ('rejected', 'archived') THEN 1 ELSE 0 END) AS rejected_count,
                    SUM(CASE WHEN COALESCE(r.status, 'new') IN ('applied', 'interview', 'offer') THEN 1 ELSE 0 END) AS good_outcome_count
                FROM search_runs sr
                LEFT JOIN vacancies v
                  ON v.source_profile = sr.profile_name
                 AND v.source_query = sr.query
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                WHERE sr.profile_name = ?
                  AND sr.query IS NOT NULL AND sr.query != ''
                GROUP BY sr.query
                ORDER BY avg_score DESC, max_found DESC
                """,
                (preset_name,),
            ).fetchall()
        return [dict(r) for r in rows]

    def preset_overlap(self, preset_a: str, preset_b: str) -> dict[str, Any]:
        """Return overlap statistics between two presets."""
        with self.connect() as connection:
            # Total vacancies per preset
            total_a = connection.execute(
                "SELECT COUNT(*) FROM vacancies WHERE source_profile = ?",
                (preset_a,),
            ).fetchone()[0]
            total_b = connection.execute(
                "SELECT COUNT(*) FROM vacancies WHERE source_profile = ?",
                (preset_b,),
            ).fetchone()[0]

            # Overlap (same vacancy id appears in both presets)
            overlap = connection.execute(
                """SELECT COUNT(*) FROM (
                    SELECT id FROM vacancies WHERE source_profile = ?
                    INTERSECT
                    SELECT id FROM vacancies WHERE source_profile = ?
                )""",
                (preset_a, preset_b),
            ).fetchone()[0]

            # Avg scores
            avg_a = (
                connection.execute(
                    """SELECT ROUND(AVG(COALESCE(s.total_score, 0)), 1)
                   FROM vacancies v
                   LEFT JOIN scores s ON s.vacancy_id = v.id
                   WHERE v.source_profile = ?""",
                    (preset_a,),
                ).fetchone()[0]
                or 0
            )

            avg_b = (
                connection.execute(
                    """SELECT ROUND(AVG(COALESCE(s.total_score, 0)), 1)
                   FROM vacancies v
                   LEFT JOIN scores s ON s.vacancy_id = v.id
                   WHERE v.source_profile = ?""",
                    (preset_b,),
                ).fetchone()[0]
                or 0
            )

            # Top keywords per preset (from matched_keywords_json)
            top_keywords = {}
            for label, pname in [("a", preset_a), ("b", preset_b)]:
                kw_rows = connection.execute(
                    """SELECT sd.matched_keywords_json
                       FROM vacancies v
                       JOIN score_details sd ON sd.vacancy_id = v.id
                       WHERE v.source_profile = ?
                       LIMIT 200""",
                    (pname,),
                ).fetchall()

                kw_freq: dict[str, int] = {}
                for row in kw_rows:
                    for kw in json_loads(row["matched_keywords_json"], []):
                        k = kw.get("keyword", "")
                        if k:
                            kw_freq[k] = kw_freq.get(k, 0) + 1
                top_keywords[label] = sorted(kw_freq.items(), key=lambda x: -x[1])[:10]

            # Top employers
            top_employers = {}
            for label, pname in [("a", preset_a), ("b", preset_b)]:
                emp_rows = connection.execute(
                    """SELECT employer_name, COUNT(*) cnt
                       FROM vacancies
                       WHERE source_profile = ? AND employer_name != ''
                       GROUP BY employer_name
                       ORDER BY cnt DESC LIMIT 5""",
                    (pname,),
                ).fetchall()
                top_employers[label] = [(r["employer_name"], r["cnt"]) for r in emp_rows]

        return {
            "total_a": total_a,
            "total_b": total_b,
            "overlap": overlap,
            "unique_a": total_a - overlap,
            "unique_b": total_b - overlap,
            "avg_score_a": avg_a,
            "avg_score_b": avg_b,
            "top_keywords": top_keywords,
            "top_employers": top_employers,
        }

    def high_quality_keywords(self, preset_name: str, min_score: int = 70) -> list[dict[str, Any]]:
        """Return top keywords from high-scoring vacancies for a preset."""
        with self.connect() as connection:
            # Get matched_keywords from score_details of good vacancies
            kw_rows = connection.execute(
                """SELECT sd.matched_keywords_json, v.key_skills_json, v.name
                   FROM vacancies v
                   JOIN score_details sd ON sd.vacancy_id = v.id
                   WHERE v.source_profile = ? AND sd.total_score >= ?
                   ORDER BY sd.total_score DESC
                   LIMIT 100""",
                (preset_name, min_score),
            ).fetchall()

            kw_freq: dict[str, int] = {}
            skill_freq: dict[str, int] = {}
            title_words: dict[str, int] = {}

            for row in kw_rows:
                for kw in json_loads(row["matched_keywords_json"], []):
                    k = kw.get("keyword", "")
                    if k:
                        kw_freq[k] = kw_freq.get(k, 0) + 1
                for sk in json_loads(row["key_skills_json"], []):
                    if sk and len(sk) > 2:
                        skill_freq[sk.lower()] = skill_freq.get(sk.lower(), 0) + 1
                # Simple title word extraction
                title = row["name"] or ""
                for word in title.lower().replace("(", " ").replace(")", " ").split():
                    if len(word) > 3 and word not in (
                        "with",
                        "from",
                        "your",
                        "this",
                        "that",
                        "have",
                    ):
                        title_words[word] = title_words.get(word, 0) + 1

            # Merge and dedupe
            suggestions: list[dict[str, Any]] = []
            for kw, cnt in sorted(kw_freq.items(), key=lambda x: -x[1])[:15]:
                suggestions.append({"keyword": kw, "count": cnt, "source": "matched_keyword"})
            for sk, cnt in sorted(skill_freq.items(), key=lambda x: -x[1])[:10]:
                if sk not in {s["keyword"] for s in suggestions}:
                    suggestions.append({"keyword": sk, "count": cnt, "source": "key_skill"})

        return sorted(suggestions, key=lambda x: -x["count"])

    def bulk_update_review_status(
        self,
        *,
        min_score: int | None = None,
        max_score: int | None = None,
        decision: str | None = None,
        preset: str | None = None,
        status: str | None = None,
        new_status: str = "archived",
        force: bool = False,
    ) -> dict[str, int]:
        """Bulk update review status with protection for applied/interview/offer.

        Returns dict with matched_count, updated_count, skipped_protected_count.
        """
        normalized_new = self._validate_review_status(new_status)

        where = ["COALESCE(v.archived, 0) = 0"]
        params: list[Any] = []

        if min_score is not None:
            where.append("COALESCE(s.total_score, 0) >= ?")
            params.append(min_score)
        if max_score is not None:
            where.append("COALESCE(s.total_score, 0) <= ?")
            params.append(max_score)
        if decision:
            where.append("sd.decision = ?")
            params.append(decision)
        if preset:
            where.append("(s.best_profile = ? OR sd.preset_name = ?)")
            params.extend([preset, preset])
        if status:
            where.append("COALESCE(r.status, 'new') = ?")
            params.append(self._validate_review_status(status))

        protected = self.REVIEW_PROTECTED_STATUSES
        now = datetime.now(timezone.utc).isoformat()

        with self.connect() as connection:
            # Count matched
            count_sql = f"""
                SELECT COUNT(*) FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                WHERE {" AND ".join(where)}
            """
            matched = connection.execute(count_sql, params).fetchone()[0]

            # Count protected
            if not force and protected:
                p_placeholders = ", ".join("?" for _ in protected)
                protected_where = where + [f"COALESCE(r.status, 'new') IN ({p_placeholders})"]
                protected_params = params + list(protected)
                protected_sql = f"""
                    SELECT COUNT(*) FROM vacancies v
                    LEFT JOIN scores s ON s.vacancy_id = v.id
                    LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                    LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                    WHERE {" AND ".join(protected_where)}
                """
                skipped = connection.execute(protected_sql, protected_params).fetchone()[0]
            else:
                skipped = 0

            # Update non-protected
            update_where = list(where)  # copy for modification
            update_params_list: list[Any] = [normalized_new, now] + list(params)
            if not force and protected:
                p_placeholders = ", ".join("?" for _ in protected)
                update_where.append(f"COALESCE(r.status, 'new') NOT IN ({p_placeholders})")
                update_params_list.extend(protected)

            set_clause = "status = ?, updated_at = ?"
            update_sql = f"""
                UPDATE vacancy_reviews
                SET {set_clause}
                WHERE vacancy_id IN (
                    SELECT v.id FROM vacancies v
                    LEFT JOIN scores s ON s.vacancy_id = v.id
                    LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                    LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                    WHERE {" AND ".join(update_where)}
                )
            """
            cursor = connection.execute(update_sql, update_params_list)
            updated = cursor.rowcount

            # For matched vacancies without a review row, insert one
            insert_sql = f"""
                INSERT OR IGNORE INTO vacancy_reviews (vacancy_id, status, updated_at)
                SELECT v.id, ?, ?
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                WHERE {" AND ".join(where)}
            """
            connection.execute(insert_sql, [normalized_new, now] + params)

        return {
            "matched_count": matched,
            "updated_count": updated,
            "skipped_protected_count": skipped,
        }
