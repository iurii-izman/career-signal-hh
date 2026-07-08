from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from . import db_migrations  # noqa: E402 — circular-safe, used in __init__
from .models import ScoreDetails, ScoreResult, Vacancy
from .utils import json_dumps, json_loads, safe_get

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
CREATE TABLE IF NOT EXISTS oauth_tokens_meta (
    provider TEXT PRIMARY KEY,
    account_id TEXT NULL,
    account_email TEXT NULL,
    token_type TEXT NULL,
    scope TEXT NULL,
    storage_backend TEXT NOT NULL DEFAULT 'keyring',
    access_token_present INTEGER NOT NULL DEFAULT 0,
    refresh_token_present INTEGER NOT NULL DEFAULT 0,
    access_token_hint TEXT NULL,
    refresh_token_hint TEXT NULL,
    obtained_at TEXT NULL,
    expires_at TEXT NULL,
    last_refresh_at TEXT NULL,
    last_sync_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hh_profiles (
    id TEXT PRIMARY KEY,
    email TEXT NULL,
    first_name TEXT NULL,
    last_name TEXT NULL,
    middle_name TEXT NULL,
    is_applicant INTEGER NULL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hh_resumes (
    id TEXT PRIMARY KEY,
    title TEXT NULL,
    status TEXT NULL,
    url TEXT NULL,
    alternate_url TEXT NULL,
    updated_at_remote TEXT NULL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hh_negotiations (
    id TEXT PRIMARY KEY,
    vacancy_id TEXT NULL,
    resume_id TEXT NULL,
    status TEXT NULL,
    unread_messages INTEGER NULL,
    updated_at_remote TEXT NULL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hh_negotiation_messages (
    negotiation_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    created_at_remote TEXT NULL,
    author_participant_type TEXT NULL,
    message_state TEXT NULL,
    text TEXT NULL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (negotiation_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_vacancies_published ON vacancies(published_at);
CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
CREATE INDEX IF NOT EXISTS idx_score_details_preset ON score_details(preset_name);
CREATE INDEX IF NOT EXISTS idx_score_details_decision ON score_details(decision);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON vacancy_reviews(status);
CREATE INDEX IF NOT EXISTS idx_briefing_reports_updated ON briefing_reports(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancy_events_vacancy_created
ON vacancy_events(vacancy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vacancy_events_type_created
ON vacancy_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_integration_outbox_status_target
ON integration_outbox(status, target, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_integration_outbox_vacancy
ON integration_outbox(vacancy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hh_resumes_updated
ON hh_resumes(updated_at_remote DESC, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_hh_negotiations_status
ON hh_negotiations(status, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_hh_negotiations_vacancy
ON hh_negotiations(vacancy_id, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_hh_negotiation_messages_negotiation
ON hh_negotiation_messages(negotiation_id, created_at_remote DESC);
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

OUTBOX_TARGET_EXTERNAL_SYNC = "external_sync"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if len(normalized) > 5 and normalized[-5] in {"+", "-"} and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


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

    def get_oauth_meta(self, provider: str = "hh_user_oauth") -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_tokens_meta WHERE provider = ?",
                (provider,),
            ).fetchone()
        return dict(row) if row else None

    def save_oauth_meta(self, provider: str, meta: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        current = self.get_oauth_meta(provider)
        created_at = current.get("created_at", now) if current else now
        payload = {
            "provider": provider,
            "account_id": meta.get("account_id"),
            "account_email": meta.get("account_email"),
            "token_type": meta.get("token_type"),
            "scope": meta.get("scope"),
            "storage_backend": meta.get("storage_backend", "keyring"),
            "access_token_present": 1 if meta.get("access_token_present") else 0,
            "refresh_token_present": 1 if meta.get("refresh_token_present") else 0,
            "access_token_hint": meta.get("access_token_hint"),
            "refresh_token_hint": meta.get("refresh_token_hint"),
            "obtained_at": meta.get("obtained_at"),
            "expires_at": meta.get("expires_at"),
            "last_refresh_at": meta.get("last_refresh_at"),
            "last_sync_at": meta.get("last_sync_at"),
            "last_error": meta.get("last_error"),
            "created_at": created_at,
            "updated_at": now,
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_tokens_meta (
                    provider, account_id, account_email, token_type, scope,
                    storage_backend, access_token_present, refresh_token_present,
                    access_token_hint, refresh_token_hint, obtained_at, expires_at,
                    last_refresh_at, last_sync_at, last_error, created_at, updated_at
                )
                VALUES (
                    :provider, :account_id, :account_email, :token_type, :scope,
                    :storage_backend, :access_token_present, :refresh_token_present,
                    :access_token_hint, :refresh_token_hint, :obtained_at, :expires_at,
                    :last_refresh_at, :last_sync_at, :last_error, :created_at, :updated_at
                )
                ON CONFLICT(provider) DO UPDATE SET
                    account_id=excluded.account_id,
                    account_email=excluded.account_email,
                    token_type=excluded.token_type,
                    scope=excluded.scope,
                    storage_backend=excluded.storage_backend,
                    access_token_present=excluded.access_token_present,
                    refresh_token_present=excluded.refresh_token_present,
                    access_token_hint=excluded.access_token_hint,
                    refresh_token_hint=excluded.refresh_token_hint,
                    obtained_at=excluded.obtained_at,
                    expires_at=excluded.expires_at,
                    last_refresh_at=excluded.last_refresh_at,
                    last_sync_at=excluded.last_sync_at,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        saved = self.get_oauth_meta(provider)
        return saved or payload

    def clear_oauth_meta(self, provider: str = "hh_user_oauth") -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM oauth_tokens_meta WHERE provider = ?",
                (provider,),
            )

    def save_hh_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(profile.get("id") or "me")
        synced_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "id": profile_id,
            "email": profile.get("email"),
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "middle_name": profile.get("middle_name"),
            "is_applicant": None
            if profile.get("is_applicant") is None
            else int(bool(profile.get("is_applicant"))),
            "raw_json": json_dumps(profile),
            "synced_at": synced_at,
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO hh_profiles (
                    id, email, first_name, last_name, middle_name, is_applicant, raw_json, synced_at
                )
                VALUES (:id, :email, :first_name, :last_name, :middle_name, :is_applicant, :raw_json, :synced_at)
                ON CONFLICT(id) DO UPDATE SET
                    email=excluded.email,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    middle_name=excluded.middle_name,
                    is_applicant=excluded.is_applicant,
                    raw_json=excluded.raw_json,
                    synced_at=excluded.synced_at
                """,
                payload,
            )
        return payload

    def save_hh_resumes(self, resumes: list[dict[str, Any]]) -> int:
        synced_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            for resume in resumes:
                connection.execute(
                    """
                    INSERT INTO hh_resumes (
                        id, title, status, url, alternate_url, updated_at_remote, raw_json, synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        status=excluded.status,
                        url=excluded.url,
                        alternate_url=excluded.alternate_url,
                        updated_at_remote=excluded.updated_at_remote,
                        raw_json=excluded.raw_json,
                        synced_at=excluded.synced_at
                    """,
                    (
                        str(resume.get("id") or ""),
                        resume.get("title"),
                        resume.get("status", {}).get("id")
                        if isinstance(resume.get("status"), dict)
                        else resume.get("status"),
                        resume.get("url"),
                        resume.get("alternate_url"),
                        resume.get("updated_at"),
                        json_dumps(resume),
                        synced_at,
                    ),
                )
        return len(resumes)

    def save_hh_negotiations(self, negotiations: list[dict[str, Any]]) -> int:
        synced_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            for negotiation in negotiations:
                unread_messages = safe_get(negotiation, "counters", "unread")
                if unread_messages is None:
                    unread_messages = safe_get(negotiation, "counters", "unread_messages")
                connection.execute(
                    """
                    INSERT INTO hh_negotiations (
                        id, vacancy_id, resume_id, status, unread_messages, updated_at_remote, raw_json, synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        vacancy_id=excluded.vacancy_id,
                        resume_id=excluded.resume_id,
                        status=excluded.status,
                        unread_messages=excluded.unread_messages,
                        updated_at_remote=excluded.updated_at_remote,
                        raw_json=excluded.raw_json,
                        synced_at=excluded.synced_at
                    """,
                    (
                        str(negotiation.get("id") or ""),
                        safe_get(negotiation, "vacancy", "id") or negotiation.get("vacancy_id"),
                        safe_get(negotiation, "resume", "id") or negotiation.get("resume_id"),
                        safe_get(negotiation, "state", "id")
                        or negotiation.get("state")
                        or negotiation.get("status"),
                        unread_messages,
                        negotiation.get("updated_at"),
                        json_dumps(negotiation),
                        synced_at,
                    ),
                )
        return len(negotiations)

    def save_hh_negotiation_messages(
        self,
        negotiation_id: str,
        messages: list[dict[str, Any]],
    ) -> int:
        synced_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            for message in messages:
                connection.execute(
                    """
                    INSERT INTO hh_negotiation_messages (
                        negotiation_id, message_id, created_at_remote, author_participant_type,
                        message_state, text, raw_json, synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(negotiation_id, message_id) DO UPDATE SET
                        created_at_remote=excluded.created_at_remote,
                        author_participant_type=excluded.author_participant_type,
                        message_state=excluded.message_state,
                        text=excluded.text,
                        raw_json=excluded.raw_json,
                        synced_at=excluded.synced_at
                    """,
                    (
                        negotiation_id,
                        str(message.get("id") or ""),
                        message.get("created_at"),
                        safe_get(message, "author", "participant_type"),
                        safe_get(message, "state", "id") or message.get("type"),
                        message.get("text"),
                        json_dumps(message),
                        synced_at,
                    ),
                )
        return len(messages)

    def mark_oauth_sync(self, provider: str = "hh_user_oauth") -> None:
        meta = self.get_oauth_meta(provider)
        if not meta:
            return
        meta["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        self.save_oauth_meta(provider, meta)

    def get_hh_sync_summary(self) -> dict[str, Any]:
        with self.connect() as connection:
            profile_count = connection.execute("SELECT COUNT(*) FROM hh_profiles").fetchone()[0]
            resume_count = connection.execute("SELECT COUNT(*) FROM hh_resumes").fetchone()[0]
            negotiation_count = connection.execute(
                "SELECT COUNT(*) FROM hh_negotiations"
            ).fetchone()[0]
            message_count = connection.execute(
                "SELECT COUNT(*) FROM hh_negotiation_messages"
            ).fetchone()[0]
            active_negotiations = connection.execute(
                "SELECT COUNT(*) FROM hh_negotiations WHERE status IS NOT NULL AND status != ''"
            ).fetchone()[0]
            negotiations_with_messages = connection.execute(
                "SELECT COUNT(DISTINCT negotiation_id) FROM hh_negotiation_messages"
            ).fetchone()[0]
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT
                        n.id AS negotiation_id,
                        n.vacancy_id,
                        n.resume_id,
                        n.status,
                        n.unread_messages,
                        n.updated_at_remote,
                        n.synced_at,
                        v.id AS local_vacancy_id,
                        v.name AS local_vacancy_name,
                        v.last_seen_at AS local_vacancy_last_seen_at,
                        r.status AS review_status,
                        r.updated_at AS review_updated_at,
                        r.next_action,
                        r.next_action_at,
                        r.applied_at
                    FROM hh_negotiations n
                    LEFT JOIN vacancies v ON v.id = n.vacancy_id
                    LEFT JOIN vacancy_reviews r ON r.vacancy_id = n.vacancy_id
                    ORDER BY COALESCE(n.updated_at_remote, n.synced_at) DESC, n.id DESC
                    """
                ).fetchall()
            ]
            review_status_rows = connection.execute(
                """
                SELECT COALESCE(r.status, 'new') AS review_status, COUNT(*) AS count
                FROM hh_negotiations n
                JOIN vacancies v ON v.id = n.vacancy_id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                GROUP BY COALESCE(r.status, 'new')
                """
            ).fetchall()
        now = datetime.now(timezone.utc)
        matched_count = 0
        unmatched_count = 0
        matched_without_review = 0
        matched_remote_newer_than_review = 0
        matched_review_newer_than_remote = 0
        unread_total = 0
        negotiations_with_unread_messages = 0
        remote_updated_last_7d = 0
        remote_updated_last_30d = 0
        newest_remote_updated_at: datetime | None = None
        oldest_remote_updated_at: datetime | None = None
        matched_sample: list[dict[str, Any]] = []
        unmatched_sample: list[dict[str, Any]] = []

        for row in rows:
            unread = int(row.get("unread_messages") or 0)
            remote_updated_at = _parse_dt(row.get("updated_at_remote"))
            review_updated_at = _parse_dt(row.get("review_updated_at"))
            local_vacancy_id = row.get("local_vacancy_id")
            review_status = row.get("review_status") or "new"

            if unread > 0:
                unread_total += unread
                negotiations_with_unread_messages += 1
            if remote_updated_at is not None:
                if newest_remote_updated_at is None or remote_updated_at > newest_remote_updated_at:
                    newest_remote_updated_at = remote_updated_at
                if oldest_remote_updated_at is None or remote_updated_at < oldest_remote_updated_at:
                    oldest_remote_updated_at = remote_updated_at
                if remote_updated_at >= now - timedelta(days=7):
                    remote_updated_last_7d += 1
                if remote_updated_at >= now - timedelta(days=30):
                    remote_updated_last_30d += 1

            item = {
                "negotiation_id": row["negotiation_id"],
                "vacancy_id": row.get("vacancy_id"),
                "status": row.get("status"),
                "unread_messages": unread,
                "updated_at_remote": row.get("updated_at_remote"),
                "review_status": review_status,
                "review_updated_at": row.get("review_updated_at"),
                "next_action": row.get("next_action"),
                "next_action_at": row.get("next_action_at"),
                "applied_at": row.get("applied_at"),
            }

            if local_vacancy_id:
                matched_count += 1
                no_review = row.get("review_status") in (None, "", "new")
                if no_review:
                    matched_without_review += 1
                if remote_updated_at is not None and review_updated_at is not None:
                    if remote_updated_at > review_updated_at:
                        matched_remote_newer_than_review += 1
                    elif review_updated_at > remote_updated_at:
                        matched_review_newer_than_remote += 1
                elif remote_updated_at is not None and no_review:
                    matched_remote_newer_than_review += 1

                if len(matched_sample) < 10:
                    matched_sample.append(
                        {
                            **item,
                            "vacancy_name": row.get("local_vacancy_name"),
                            "needs_attention": bool(
                                unread > 0
                                or no_review
                                or (
                                    remote_updated_at is not None
                                    and review_updated_at is not None
                                    and remote_updated_at > review_updated_at
                                )
                            ),
                        }
                    )
            else:
                unmatched_count += 1
                if len(unmatched_sample) < 10:
                    unmatched_sample.append(item)

        review_status_counts = {
            str(row["review_status"]): int(row["count"])
            for row in review_status_rows
        }
        return {
            "profiles": profile_count,
            "resumes": resume_count,
            "negotiations": negotiation_count,
            "messages": message_count,
            "negotiations_with_status": active_negotiations,
            "negotiations_with_messages": negotiations_with_messages,
            "negotiations_with_unread_messages": negotiations_with_unread_messages,
            "unread_messages_total": unread_total,
            "negotiations_matched_local_vacancies": matched_count,
            "negotiations_unmatched_local_vacancies": unmatched_count,
            "matched_without_review": matched_without_review,
            "matched_remote_newer_than_review": matched_remote_newer_than_review,
            "matched_review_newer_than_remote": matched_review_newer_than_remote,
            "review_status_counts": review_status_counts,
            "freshness": {
                "newest_remote_updated_at": (
                    newest_remote_updated_at.isoformat() if newest_remote_updated_at else None
                ),
                "oldest_remote_updated_at": (
                    oldest_remote_updated_at.isoformat() if oldest_remote_updated_at else None
                ),
                "remote_updated_last_7d": remote_updated_last_7d,
                "remote_updated_last_30d": remote_updated_last_30d,
            },
            "matched_sample": matched_sample,
            "unmatched_sample": unmatched_sample,
        }

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

    @staticmethod
    def _review_default(vacancy_id: str) -> dict[str, Any]:
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

    @staticmethod
    def _vacancy_exists_in_connection(connection: sqlite3.Connection, vacancy_id: str) -> bool:
        row = connection.execute("SELECT 1 FROM vacancies WHERE id = ?", (vacancy_id,)).fetchone()
        return row is not None

    def _require_vacancy_in_connection(
        self, connection: sqlite3.Connection, vacancy_id: str
    ) -> None:
        if not self._vacancy_exists_in_connection(connection, vacancy_id):
            raise ValueError(f"Вакансия с id={vacancy_id} не найдена.")

    def _get_review_in_connection(
        self, connection: sqlite3.Connection, vacancy_id: str
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM vacancy_reviews WHERE vacancy_id = ?",
            (vacancy_id,),
        ).fetchone()
        return dict(row) if row else self._review_default(vacancy_id)

    @staticmethod
    def _trimmed_note_preview(note: str | None, limit: int = 120) -> str | None:
        if note is None:
            return None
        normalized = " ".join(note.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."

    def _build_outbox_payload(
        self,
        connection: sqlite3.Connection,
        vacancy_id: str,
        *,
        event_type: str,
        created_at: str,
        source: str,
        payload: dict[str, Any],
        old_status: str | None,
        new_status: str | None,
    ) -> dict[str, Any]:
        vacancy = connection.execute(
            """
            SELECT id, name, employer_name, area_name, alternate_url, published_at,
                   salary_from, salary_to, salary_currency, schedule_name,
                   employment_name, experience_name
            FROM vacancies
            WHERE id = ?
            """,
            (vacancy_id,),
        ).fetchone()
        review = self._get_review_in_connection(connection, vacancy_id)
        briefing = connection.execute(
            """
            SELECT vacancy_id, lang, score_total, decision, created_at, updated_at
            FROM briefing_reports
            WHERE vacancy_id = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (vacancy_id,),
        ).fetchone()

        review_snapshot = {
            "status": review.get("status"),
            "priority": review.get("priority"),
            "user_notes_preview": self._trimmed_note_preview(review.get("user_notes")),
            "applied_at": review.get("applied_at"),
            "next_action": review.get("next_action"),
            "next_action_at": review.get("next_action_at"),
            "updated_at": review.get("updated_at"),
        }
        briefing_snapshot = None
        if briefing:
            briefing_snapshot = {
                "lang": briefing["lang"],
                "score_total": briefing["score_total"],
                "decision": briefing["decision"],
                "created_at": briefing["created_at"],
                "updated_at": briefing["updated_at"],
            }

        return {
            "payload_version": "1.0",
            "source": "career-signal-hh",
            "event_type": event_type,
            "emitted_at": created_at,
            "emission_source": source,
            "vacancy": dict(vacancy) if vacancy else {"id": vacancy_id},
            "review": review_snapshot,
            "briefing": briefing_snapshot,
            "event": {
                "old_status": old_status,
                "new_status": new_status,
                "payload": payload,
            },
        }

    def _record_event(
        self,
        connection: sqlite3.Connection,
        vacancy_id: str,
        *,
        event_type: str,
        source: str,
        payload: dict[str, Any],
        old_status: str | None = None,
        new_status: str | None = None,
        enqueue_outbox: bool = False,
        target: str = OUTBOX_TARGET_EXTERNAL_SYNC,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        payload_json = json_dumps(payload)
        connection.execute(
            """
            INSERT INTO vacancy_events (
                vacancy_id, event_type, old_status, new_status,
                payload_json, created_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (vacancy_id, event_type, old_status, new_status, payload_json, created_at, source),
        )
        if not enqueue_outbox:
            return

        outbox_payload = self._build_outbox_payload(
            connection,
            vacancy_id,
            event_type=event_type,
            created_at=created_at,
            source=source,
            payload=payload,
            old_status=old_status,
            new_status=new_status,
        )
        outbox_payload_json = json_dumps(outbox_payload)
        connection.execute(
            """
            INSERT INTO integration_outbox (
                event_type, vacancy_id, payload_json, target,
                status, attempts, last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'pending', 0, NULL, ?, ?)
            """,
            (event_type, vacancy_id, outbox_payload_json, target, created_at, created_at),
        )

    def _emit_review_events(
        self,
        connection: sqlite3.Connection,
        vacancy_id: str,
        *,
        before: dict[str, Any],
        after: dict[str, Any],
        changed_fields: set[str],
    ) -> None:
        if "status" in changed_fields:
            old_status = before.get("status")
            new_status = after.get("status")
            status_event_type = "review_applied" if new_status == "applied" else "review_status_changed"
            status_payload = {
                "status": new_status,
                "applied_at": after.get("applied_at"),
            }
            self._record_event(
                connection,
                vacancy_id,
                event_type=status_event_type,
                source="review",
                payload=status_payload,
                old_status=old_status,
                new_status=new_status,
                enqueue_outbox=True,
            )

        if "user_notes" in changed_fields:
            self._record_event(
                connection,
                vacancy_id,
                event_type="review_note_updated",
                source="review",
                payload={
                    "has_note": bool(after.get("user_notes")),
                    "note_length": len(after.get("user_notes") or ""),
                },
            )

        if {"next_action", "next_action_at"} & changed_fields:
            self._record_event(
                connection,
                vacancy_id,
                event_type="review_next_action_set",
                source="review",
                payload={
                    "next_action": after.get("next_action"),
                    "next_action_at": after.get("next_action_at"),
                },
                old_status=before.get("status"),
                new_status=after.get("status"),
                enqueue_outbox=True,
            )

        if "cover_letter_draft" in changed_fields:
            had_before = bool(before.get("cover_letter_draft"))
            has_after = bool(after.get("cover_letter_draft"))
            event_type = "review_draft_saved" if has_after else "review_draft_cleared"
            self._record_event(
                connection,
                vacancy_id,
                event_type=event_type,
                source="apply_pack",
                payload={
                    "had_draft_before": had_before,
                    "has_draft_after": has_after,
                    "draft_length": len(after.get("cover_letter_draft") or ""),
                },
                old_status=before.get("status"),
                new_status=after.get("status"),
                enqueue_outbox=has_after,
            )

    def _update_review_in_connection(
        self,
        connection: sqlite3.Connection,
        vacancy_id: str,
        **fields: Any,
    ) -> dict[str, Any]:
        self._require_vacancy_in_connection(connection, vacancy_id)
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

        before = self._get_review_in_connection(connection, vacancy_id)
        now = datetime.now(timezone.utc).isoformat()
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
        after = self._get_review_in_connection(connection, vacancy_id)
        changed_fields = {
            field
            for field in allowed_fields
            if before.get(field) != after.get(field)
        }
        if changed_fields:
            self._emit_review_events(
                connection,
                vacancy_id,
                before=before,
                after=after,
                changed_fields=changed_fields,
            )
        return after

    def get_review(self, vacancy_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            return self._get_review_in_connection(connection, vacancy_id)

    def upsert_review(self, vacancy_id: str, **fields: Any) -> dict[str, Any]:
        with self.connect() as connection:
            return self._update_review_in_connection(connection, vacancy_id, **fields)

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

    def get_briefing_report(self, vacancy_id: str, lang: str = "ru") -> dict[str, Any] | None:
        """Return saved briefing report for a vacancy/lang pair."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM briefing_reports WHERE vacancy_id = ? AND lang = ?",
                (vacancy_id, lang),
            ).fetchone()
        return dict(row) if row else None

    def list_briefing_reports(
        self, *, vacancy_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return latest saved briefing reports."""
        sql = "SELECT * FROM briefing_reports"
        params: list[Any] = []
        if vacancy_id:
            sql += " WHERE vacancy_id = ?"
            params.append(vacancy_id)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def upsert_briefing_report(
        self,
        vacancy_id: str,
        *,
        lang: str,
        score_total: int,
        decision: str,
        report_md: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert or update a saved briefing artifact."""
        with self.connect() as connection:
            self._require_vacancy_in_connection(connection, vacancy_id)
            before = connection.execute(
                "SELECT 1 FROM briefing_reports WHERE vacancy_id = ? AND lang = ?",
                (vacancy_id, lang),
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            payload_json = json_dumps(payload)
            connection.execute(
                """
                INSERT INTO briefing_reports (
                    vacancy_id, lang, score_total, decision,
                    report_md, payload_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vacancy_id, lang) DO UPDATE SET
                    score_total = excluded.score_total,
                    decision = excluded.decision,
                    report_md = excluded.report_md,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    vacancy_id,
                    lang,
                    score_total,
                    decision,
                    report_md,
                    payload_json,
                    now,
                    now,
                ),
            )
            self._record_event(
                connection,
                vacancy_id,
                event_type="briefing_saved",
                source="briefing",
                payload={
                    "lang": lang,
                    "score_total": score_total,
                    "decision": decision,
                    "is_new": before is None,
                },
                old_status=self._get_review_in_connection(connection, vacancy_id).get("status"),
                new_status=self._get_review_in_connection(connection, vacancy_id).get("status"),
                enqueue_outbox=True,
            )
            row = connection.execute(
                "SELECT * FROM briefing_reports WHERE vacancy_id = ? AND lang = ?",
                (vacancy_id, lang),
            ).fetchone()
        return dict(row) if row else {}

    def list_vacancy_events(
        self,
        vacancy_id: str,
        *,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest vacancy events for a vacancy."""
        sql = "SELECT * FROM vacancy_events WHERE vacancy_id = ?"
        params: list[Any] = [vacancy_id]
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def record_vacancy_event(
        self,
        vacancy_id: str,
        *,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
        old_status: str | None = None,
        new_status: str | None = None,
        enqueue_outbox: bool = False,
        target: str = OUTBOX_TARGET_EXTERNAL_SYNC,
    ) -> None:
        with self.connect() as connection:
            self._require_vacancy_in_connection(connection, vacancy_id)
            self._record_event(
                connection,
                vacancy_id,
                event_type=event_type,
                source=source,
                payload=payload or {},
                old_status=old_status,
                new_status=new_status,
                enqueue_outbox=enqueue_outbox,
                target=target,
            )

    def list_outbox_entries(
        self,
        *,
        outbox_id: int | None = None,
        status: str | None = None,
        target: str | None = None,
        vacancy_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return integration outbox entries ordered oldest-first within status."""
        where: list[str] = []
        params: list[Any] = []
        if outbox_id is not None:
            where.append("id = ?")
            params.append(outbox_id)
        if status:
            where.append("status = ?")
            params.append(status)
        if target:
            where.append("target = ?")
            params.append(target)
        if vacancy_id:
            where.append("vacancy_id = ?")
            params.append(vacancy_id)
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)

        sql = "SELECT * FROM integration_outbox"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def get_outbox_entry(self, outbox_id: int) -> dict[str, Any] | None:
        """Return a single integration outbox row by id."""
        rows = self.list_outbox_entries(outbox_id=outbox_id, limit=1)
        return rows[0] if rows else None

    def update_outbox_delivery_attempt(
        self,
        outbox_id: int,
        *,
        status: str,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        """Increment attempts and persist the latest delivery result."""
        allowed_statuses = {"pending", "sent", "failed"}
        normalized_status = status.strip().lower()
        if normalized_status not in allowed_statuses:
            allowed = ", ".join(sorted(allowed_statuses))
            raise ValueError(f"Недопустимый outbox status={status!r}. Допустимы: {allowed}.")

        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE integration_outbox
                SET status = ?,
                    attempts = attempts + 1,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (normalized_status, last_error, now, outbox_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Outbox entry id={outbox_id} не найдена.")
            row = connection.execute(
                "SELECT * FROM integration_outbox WHERE id = ?",
                (outbox_id,),
            ).fetchone()
        return dict(row) if row else {}

    def mark_outbox_pending(self, outbox_id: int) -> dict[str, Any]:
        """Reset an outbox row to pending without incrementing attempts."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE integration_outbox
                SET status = 'pending',
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, outbox_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Outbox entry id={outbox_id} не найдена.")
            row = connection.execute(
                "SELECT * FROM integration_outbox WHERE id = ?",
                (outbox_id,),
            ).fetchone()
        return dict(row) if row else {}

    def summarize_outbox(self, *, target: str | None = None) -> dict[str, Any]:
        """Return status counters and oldest pending/failed timestamps."""
        where = ""
        params: list[Any] = []
        if target:
            where = " WHERE target = ?"
            params.append(target)
        with self.connect() as connection:
            counts_rows = connection.execute(
                f"""
                SELECT status, COUNT(*) AS total
                FROM integration_outbox
                {where}
                GROUP BY status
                """,
                params,
            ).fetchall()
            total = connection.execute(
                f"SELECT COUNT(*) FROM integration_outbox{where}",
                params,
            ).fetchone()[0]
            oldest_pending = connection.execute(
                f"""
                SELECT created_at
                FROM integration_outbox
                {where + (' AND' if where else ' WHERE')} status = 'pending'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
            oldest_failed = connection.execute(
                f"""
                SELECT updated_at
                FROM integration_outbox
                {where + (' AND' if where else ' WHERE')} status = 'failed'
                ORDER BY updated_at ASC, id ASC
                LIMIT 1
                """,
                params,
            ).fetchone()

        counts = {row["status"]: int(row["total"]) for row in counts_rows}
        return {
            "total": int(total or 0),
            "counts": counts,
            "oldest_pending_at": oldest_pending["created_at"] if oldest_pending else None,
            "oldest_failed_at": oldest_failed["updated_at"] if oldest_failed else None,
        }

    def get_operational_metrics(
        self,
        *,
        queue_score: int = 70,
        strong_score: int = 85,
        recent_limit: int = 12,
        attention_limit: int = 5,
    ) -> dict[str, Any]:
        """Return dashboard/cockpit aggregates based on queue, events, briefings, and outbox."""
        with self.connect() as connection:
            pipeline_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS sourced,
                    SUM(CASE WHEN s.vacancy_id IS NOT NULL THEN 1 ELSE 0 END) AS scored,
                    SUM(CASE WHEN sd.decision IN ('strong_match', 'queue', 'review_later') THEN 1 ELSE 0 END) AS shortlisted,
                    SUM(CASE WHEN br.vacancy_id IS NOT NULL THEN 1 ELSE 0 END) AS briefed,
                    SUM(CASE WHEN r.cover_letter_draft IS NOT NULL AND TRIM(r.cover_letter_draft) != '' THEN 1 ELSE 0 END) AS drafted,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'applied' THEN 1 ELSE 0 END) AS applied,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'interview' THEN 1 ELSE 0 END) AS interview,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'offer' THEN 1 ELSE 0 END) AS offer
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                LEFT JOIN (
                    SELECT vacancy_id, MAX(updated_at) AS updated_at
                    FROM briefing_reports
                    GROUP BY vacancy_id
                ) br ON br.vacancy_id = v.id
                """
            ).fetchone()

            queue_row = connection.execute(
                """
                SELECT
                    SUM(CASE
                        WHEN COALESCE(s.total_score, 0) >= ? AND COALESCE(r.status, 'new') = 'new'
                        THEN 1 ELSE 0 END
                    ) AS pending_new,
                    SUM(CASE
                        WHEN sd.decision = 'strong_match' AND COALESCE(r.status, 'new') = 'new'
                        THEN 1 ELSE 0 END
                    ) AS strong_new,
                    SUM(CASE
                        WHEN sd.decision = 'strong_match'
                             AND COALESCE(r.status, 'new') IN ('new', 'interesting', 'maybe')
                             AND br.vacancy_id IS NULL
                        THEN 1 ELSE 0 END
                    ) AS missing_briefing,
                    SUM(CASE
                        WHEN COALESCE(r.status, 'new') = 'interesting'
                             AND (r.cover_letter_draft IS NULL OR TRIM(r.cover_letter_draft) = '')
                        THEN 1 ELSE 0 END
                    ) AS interesting_without_draft,
                    SUM(CASE
                        WHEN COALESCE(r.status, 'new') IN ('applied', 'interview')
                             AND (r.next_action_at IS NULL OR date(r.next_action_at) <= date('now'))
                        THEN 1 ELSE 0 END
                    ) AS follow_up_due,
                    SUM(CASE
                        WHEN COALESCE(s.total_score, 0) >= ?
                             AND sd.risk_flags_json IS NOT NULL
                             AND sd.risk_flags_json != '[]'
                        THEN 1 ELSE 0 END
                    ) AS risky_queue,
                    SUM(CASE
                        WHEN COALESCE(s.total_score, 0) >= ?
                             AND (v.salary_from IS NOT NULL OR v.salary_to IS NOT NULL)
                        THEN 1 ELSE 0 END
                    ) AS with_salary,
                    SUM(CASE
                        WHEN COALESCE(s.total_score, 0) >= ?
                             AND s.work_format_flags_json LIKE '%remote%'
                        THEN 1 ELSE 0 END
                    ) AS remote_queue
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                LEFT JOIN (
                    SELECT vacancy_id
                    FROM briefing_reports
                    GROUP BY vacancy_id
                ) br ON br.vacancy_id = v.id
                """,
                (queue_score, queue_score, queue_score, queue_score),
            ).fetchone()

            status_rows = connection.execute(
                """
                SELECT COALESCE(r.status, 'new') AS status, COUNT(*) AS count
                FROM vacancies v
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                GROUP BY COALESCE(r.status, 'new')
                ORDER BY count DESC, status ASC
                """
            ).fetchall()

            risk_buckets = [
                {
                    "key": "exclude_match",
                    "label": "Exclude match",
                    "count": connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM score_details sd
                        LEFT JOIN scores s ON s.vacancy_id = sd.vacancy_id
                        WHERE COALESCE(s.total_score, sd.total_score, 0) >= ?
                          AND sd.risk_flags_json LIKE '%exclude_match%'
                        """,
                        (queue_score,),
                    ).fetchone()[0],
                },
                {
                    "key": "penalty_match",
                    "label": "Penalty match",
                    "count": connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM score_details sd
                        LEFT JOIN scores s ON s.vacancy_id = sd.vacancy_id
                        WHERE COALESCE(s.total_score, sd.total_score, 0) >= ?
                          AND sd.risk_flags_json LIKE '%penalty_match%'
                        """,
                        (queue_score,),
                    ).fetchone()[0],
                },
                {
                    "key": "exclude_title",
                    "label": "Exclude in title",
                    "count": connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM score_details sd
                        LEFT JOIN scores s ON s.vacancy_id = sd.vacancy_id
                        WHERE COALESCE(s.total_score, sd.total_score, 0) >= ?
                          AND sd.risk_flags_json LIKE '%exclude_title%'
                        """,
                        (queue_score,),
                    ).fetchone()[0],
                },
                {
                    "key": "remote_unclear",
                    "label": "Remote unclear",
                    "count": connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM score_details sd
                        LEFT JOIN scores s ON s.vacancy_id = sd.vacancy_id
                        WHERE COALESCE(s.total_score, sd.total_score, 0) >= ?
                          AND sd.quality_flags_json LIKE '%remote_unclear%'
                        """,
                        (queue_score,),
                    ).fetchone()[0],
                },
                {
                    "key": "work_format",
                    "label": "Onsite or hybrid",
                    "count": connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM score_details sd
                        LEFT JOIN scores s ON s.vacancy_id = sd.vacancy_id
                        WHERE COALESCE(s.total_score, sd.total_score, 0) >= ?
                          AND sd.risk_flags_json LIKE '%work:%'
                        """,
                        (queue_score,),
                    ).fetchone()[0],
                },
            ]

            preset_rows = connection.execute(
                """
                SELECT
                    COALESCE(sd.preset_name, s.best_profile, v.source_profile, 'unknown') AS preset,
                    COUNT(*) AS total,
                    ROUND(AVG(COALESCE(s.total_score, sd.total_score, 0)), 1) AS avg_score,
                    SUM(CASE WHEN sd.decision = 'strong_match' THEN 1 ELSE 0 END) AS strong,
                    SUM(CASE WHEN sd.decision = 'queue' THEN 1 ELSE 0 END) AS queue,
                    SUM(CASE WHEN br.vacancy_id IS NOT NULL THEN 1 ELSE 0 END) AS briefed,
                    SUM(CASE WHEN r.cover_letter_draft IS NOT NULL AND TRIM(r.cover_letter_draft) != '' THEN 1 ELSE 0 END) AS drafted,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'applied' THEN 1 ELSE 0 END) AS applied,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'interview' THEN 1 ELSE 0 END) AS interview,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'offer' THEN 1 ELSE 0 END) AS offer,
                    SUM(CASE WHEN COALESCE(r.status, 'new') = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                    SUM(CASE WHEN sd.risk_flags_json IS NOT NULL AND sd.risk_flags_json != '[]' THEN 1 ELSE 0 END) AS risky
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                LEFT JOIN (
                    SELECT vacancy_id
                    FROM briefing_reports
                    GROUP BY vacancy_id
                ) br ON br.vacancy_id = v.id
                GROUP BY preset
                ORDER BY strong DESC, applied DESC, avg_score DESC, total DESC
                """
            ).fetchall()

            recent_rows = connection.execute(
                """
                SELECT
                    e.created_at,
                    e.event_type,
                    e.vacancy_id,
                    e.old_status,
                    e.new_status,
                    e.source,
                    v.name,
                    v.employer_name
                FROM vacancy_events e
                JOIN vacancies v ON v.id = e.vacancy_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ?
                """,
                (recent_limit,),
            ).fetchall()

            briefing_needed_rows = connection.execute(
                """
                SELECT
                    'briefing_needed' AS kind,
                    v.id,
                    v.name,
                    v.employer_name,
                    COALESCE(s.total_score, sd.total_score, 0) AS total_score,
                    COALESCE(sd.decision, 'unknown') AS decision,
                    COALESCE(r.status, 'new') AS review_status,
                    NULL AS next_action_at
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                LEFT JOIN (
                    SELECT vacancy_id
                    FROM briefing_reports
                    GROUP BY vacancy_id
                ) br ON br.vacancy_id = v.id
                WHERE sd.decision = 'strong_match'
                  AND COALESCE(r.status, 'new') IN ('new', 'interesting', 'maybe')
                  AND br.vacancy_id IS NULL
                ORDER BY COALESCE(s.total_score, sd.total_score, 0) DESC, v.published_at DESC
                LIMIT ?
                """,
                (attention_limit,),
            ).fetchall()

            follow_up_rows = connection.execute(
                """
                SELECT
                    'follow_up_due' AS kind,
                    v.id,
                    v.name,
                    v.employer_name,
                    COALESCE(s.total_score, 0) AS total_score,
                    COALESCE(sd.decision, 'unknown') AS decision,
                    COALESCE(r.status, 'new') AS review_status,
                    r.next_action_at
                FROM vacancies v
                JOIN vacancy_reviews r ON r.vacancy_id = v.id
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                WHERE COALESCE(r.status, 'new') IN ('applied', 'interview')
                  AND (r.next_action_at IS NULL OR date(r.next_action_at) <= date('now'))
                ORDER BY COALESCE(r.next_action_at, r.applied_at, v.last_seen_at) ASC
                LIMIT ?
                """,
                (attention_limit,),
            ).fetchall()

            briefing_summary = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT vacancy_id) AS saved,
                    SUM(CASE WHEN date(updated_at) >= date('now', '-7 day') THEN 1 ELSE 0 END) AS updated_7d
                FROM briefing_reports
                """
            ).fetchone()

        outbox = self.summarize_outbox()
        counts = outbox.get("counts", {})
        attention_rows = [dict(row) for row in briefing_needed_rows] + [
            dict(row) for row in follow_up_rows
        ]
        attention_rows.sort(
            key=lambda row: (
                0 if row.get("kind") == "follow_up_due" else 1,
                -(row.get("total_score") or 0),
                row.get("next_action_at") or "",
            )
        )

        return {
            "pipeline": {
                key: int((pipeline_row[key] or 0) if pipeline_row is not None else 0)
                for key in (
                    "sourced",
                    "scored",
                    "shortlisted",
                    "briefed",
                    "drafted",
                    "applied",
                    "interview",
                    "offer",
                )
            },
            "queue_health": {
                **{
                    key: int((queue_row[key] or 0) if queue_row is not None else 0)
                    for key in (
                        "pending_new",
                        "strong_new",
                        "missing_briefing",
                        "interesting_without_draft",
                        "follow_up_due",
                        "risky_queue",
                        "with_salary",
                        "remote_queue",
                    )
                },
                "outbox_pending": int(counts.get("pending", 0)),
                "outbox_failed": int(counts.get("failed", 0)),
            },
            "status_buckets": [dict(row) for row in status_rows],
            "risk_buckets": [
                {**bucket, "count": int(bucket["count"] or 0)} for bucket in risk_buckets
            ],
            "preset_performance": [dict(row) for row in preset_rows],
            "recent_activity": [dict(row) for row in recent_rows],
            "attention_items": attention_rows[: attention_limit * 2],
            "briefing_summary": {
                "saved": int((briefing_summary["saved"] or 0) if briefing_summary else 0),
                "updated_7d": int(
                    (briefing_summary["updated_7d"] or 0) if briefing_summary else 0
                ),
            },
            "outbox_summary": outbox,
        }

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

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT v.id, COALESCE(r.status, 'new') current_status
                FROM vacancies v
                LEFT JOIN scores s ON s.vacancy_id = v.id
                LEFT JOIN score_details sd ON sd.vacancy_id = v.id
                LEFT JOIN vacancy_reviews r ON r.vacancy_id = v.id
                WHERE {" AND ".join(where)}
                """,
                params,
            ).fetchall()

            matched = len(rows)
            skipped = 0
            updated = 0

            for row in rows:
                current_status = row["current_status"] or "new"
                if not force and current_status in protected:
                    skipped += 1
                    continue
                if current_status == normalized_new:
                    continue
                self._update_review_in_connection(connection, row["id"], status=normalized_new)
                updated += 1

        return {
            "matched_count": matched,
            "updated_count": updated,
            "skipped_protected_count": skipped,
        }
