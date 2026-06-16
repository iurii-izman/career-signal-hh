from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import ScoreDetails, ScoreResult, Vacancy
from .utils import json_dumps

SCHEMA = """
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
]


class Storage:
    def __init__(self, path: str = "data/vacancies.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        self.ensure_review_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def ensure_review_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
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
                CREATE INDEX IF NOT EXISTS idx_reviews_status
                ON vacancy_reviews(status);
                """
            )

    def _require_vacancy(self, vacancy_id: str) -> None:
        if not self.vacancy_exists(vacancy_id):
            raise ValueError(f"Вакансия с id={vacancy_id} не найдена.")

    @staticmethod
    def _validate_review_status(status: str) -> str:
        normalized = status.strip().lower()
        if normalized not in REVIEW_STATUSES:
            allowed = ", ".join(sorted(REVIEW_STATUSES))
            raise ValueError(
                f"Недопустимый review status={status!r}. Допустимы: {allowed}."
            )
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

    def set_next_action(
        self, vacancy_id: str, action: str, next_action_at: str
    ) -> dict[str, Any]:
        return self.upsert_review(
            vacancy_id, next_action=action, next_action_at=next_action_at
        )

    def vacancy_exists(self, vacancy_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
        return row is not None

    def touch_vacancy(self, vacancy_id: str) -> bool:
        """Update last_seen_at for an existing vacancy without touching other fields.

        Returns True if the vacancy exists and was updated, False otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE vacancies SET last_seen_at = ? WHERE id = ?",
                (now, vacancy_id),
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
            f"{column}=excluded.{column}"
            for column in columns
            if column != "vacancy_id"
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
        from .models import ScoreDetails

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
        values["explanation_json"] = json_dumps(values.pop("explanation"))
        columns = list(values)
        updates = ", ".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column != "vacancy_id"
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
                protected_where = where + [
                    f"COALESCE(r.status, 'new') IN ({p_placeholders})"
                ]
                protected_params = params + list(protected)
                protected_sql = f"""
                    SELECT COUNT(*) FROM vacancies v
                    LEFT JOIN scores s ON s.vacancy_id = v.id
                    LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                    LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                    WHERE {" AND ".join(protected_where)}
                """
                skipped = connection.execute(
                    protected_sql, protected_params
                ).fetchone()[0]
            else:
                skipped = 0

            # Update non-protected
            update_where = list(where)  # copy for modification
            update_params_list: list[Any] = [normalized_new, now] + list(params)
            if not force and protected:
                p_placeholders = ", ".join("?" for _ in protected)
                update_where.append(
                    f"COALESCE(r.status, 'new') NOT IN ({p_placeholders})"
                )
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
