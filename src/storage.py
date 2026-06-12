from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import ScoreResult, Vacancy
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
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
    profile_name TEXT, query TEXT, area_id TEXT, found_count INTEGER,
    loaded_count INTEGER, new_count INTEGER, updated_count INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
"""

VACANCY_COLUMNS = [
    "id", "name", "employer_id", "employer_name", "area_name", "alternate_url",
    "published_at", "created_at", "archived", "salary_from", "salary_to",
    "salary_currency", "schedule_name", "employment_name", "experience_name",
    "description_html", "description_text", "key_skills_json", "raw_json",
    "first_seen_at", "last_seen_at", "source_profile",
]


class Storage:
    def __init__(self, path: str = "data/vacancies.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def vacancy_exists(self, vacancy_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)
            ).fetchone()
        return row is not None

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
                   s.work_format_flags_json, s.scored_at
            FROM vacancies v LEFT JOIN scores s ON s.vacancy_id = v.id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(s.total_score, 0) DESC, v.published_at DESC
        """
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
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
