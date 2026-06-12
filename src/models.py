from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .utils import html_to_text, json_dumps, safe_get


class Vacancy(BaseModel):
    id: str
    name: str = ""
    employer_id: str | None = None
    employer_name: str = ""
    area_name: str = ""
    alternate_url: str = ""
    published_at: str | None = None
    created_at: str | None = None
    archived: bool = False
    salary_from: int | None = None
    salary_to: int | None = None
    salary_currency: str | None = None
    schedule_name: str | None = None
    employment_name: str | None = None
    experience_name: str | None = None
    description_html: str = ""
    description_text: str = ""
    key_skills: list[str] = Field(default_factory=list)
    raw_json: str
    first_seen_at: str
    last_seen_at: str
    source_profile: str | None = None
    snippet_requirement: str = ""
    snippet_responsibility: str = ""

    @classmethod
    def from_hh(
        cls, data: dict[str, Any], source_profile: str | None = None
    ) -> "Vacancy":
        now = datetime.now(timezone.utc).isoformat()
        salary = data.get("salary") or {}
        description = data.get("description") or ""
        snippet = data.get("snippet") or {}
        skills = [
            item.get("name", "")
            for item in (data.get("key_skills") or [])
            if item.get("name")
        ]
        return cls(
            id=str(data.get("id", "")),
            name=data.get("name") or "",
            employer_id=str(safe_get(data, "employer", "id", default="")) or None,
            employer_name=safe_get(data, "employer", "name", default="") or "",
            area_name=safe_get(data, "area", "name", default="") or "",
            alternate_url=data.get("alternate_url") or "",
            published_at=data.get("published_at"),
            created_at=data.get("created_at"),
            archived=bool(data.get("archived", False)),
            salary_from=salary.get("from"),
            salary_to=salary.get("to"),
            salary_currency=salary.get("currency"),
            schedule_name=safe_get(data, "schedule", "name"),
            employment_name=safe_get(data, "employment", "name"),
            experience_name=safe_get(data, "experience", "name"),
            description_html=description,
            description_text=html_to_text(description),
            key_skills=skills,
            raw_json=json_dumps(data),
            first_seen_at=now,
            last_seen_at=now,
            source_profile=source_profile,
            snippet_requirement=html_to_text(snippet.get("requirement")),
            snippet_responsibility=html_to_text(snippet.get("responsibility")),
        )


class ScoreResult(BaseModel):
    vacancy_id: str
    total_score: int
    ai_automation_score: int
    bitrix_1c_score: int
    best_profile: str
    match_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    work_format_flags: list[str] = Field(default_factory=list)
    scored_at: str
