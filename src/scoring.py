from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import ScoreResult, Vacancy
from .utils import normalize_text, parse_datetime


def _vacancy_text(vacancy: Vacancy) -> str:
    fields = [
        vacancy.name,
        vacancy.snippet_requirement,
        vacancy.snippet_responsibility,
        vacancy.description_text,
        " ".join(vacancy.key_skills),
        vacancy.employer_name,
        vacancy.schedule_name or "",
        vacancy.employment_name or "",
        vacancy.experience_name or "",
        vacancy.area_name,
    ]
    return normalize_text(" ".join(fields))


def _freshness(published_at: str | None) -> int:
    published = parse_datetime(published_at)
    if not published:
        return 0
    age = max(0, (datetime.now(timezone.utc) - published).days)
    return 10 if age <= 1 else 7 if age <= 3 else 4 if age <= 7 else 1 if age <= 14 else 0


def _work_flags(vacancy: Vacancy, text: str) -> list[str]:
    schedule = normalize_text(vacancy.schedule_name)
    flags: list[str] = []
    if "удален" in schedule or "remote" in schedule or "удален" in text:
        flags.append("remote")
    if "гибрид" in schedule or "hybrid" in schedule or "гибрид" in text:
        flags.append("hybrid")
    if "релокац" in text or "relocation" in text:
        flags.append("relocation")
    if not flags and ("офис" in schedule or "полный день" in schedule):
        flags.append("onsite")
    return flags or ["unknown"]


def score_vacancy(vacancy: Vacancy, rules: dict[str, Any]) -> ScoreResult:
    text = _vacancy_text(vacancy)
    profile_scores: dict[str, int] = {}
    reasons_by_profile: dict[str, list[str]] = {}
    for profile, config in rules.get("profiles", {}).items():
        hits: list[tuple[str, int]] = []
        for keyword, weight in config.get("keywords", {}).items():
            if normalize_text(keyword) in text:
                hits.append((keyword, int(weight)))
        profile_scores[profile] = min(90, sum(weight for _, weight in hits))
        reasons_by_profile[profile] = [
            f"{keyword} (+{weight})" for keyword, weight in sorted(hits, key=lambda x: -x[1])[:6]
        ]

    risk_flags: list[str] = []
    penalty = 0
    for risk_name, config in rules.get("risks", {}).items():
        if any(normalize_text(word) in text for word in config.get("keywords", [])):
            risk_flags.append(risk_name)
            penalty += int(config.get("penalty", 0))

    ai_score = max(0, profile_scores.get("ai_automation", 0) - penalty)
    bitrix_score = max(0, profile_scores.get("bitrix_1c", 0) - penalty)
    freshness = _freshness(vacancy.published_at)
    top_profile_score = max(ai_score, bitrix_score)
    total = min(100, max(0, top_profile_score + freshness))
    if ai_score >= 25 and bitrix_score >= 25 and abs(ai_score - bitrix_score) <= 12:
        best_profile = "mixed"
    elif top_profile_score < 15:
        best_profile = "low_match"
    else:
        best_profile = "ai_automation" if ai_score >= bitrix_score else "bitrix_1c"
    reason_profile = (
        "ai_automation"
        if ai_score >= bitrix_score
        else "bitrix_1c"
    )
    reasons = reasons_by_profile.get(reason_profile, [])
    if freshness:
        reasons.append(f"свежесть (+{freshness})")
    return ScoreResult(
        vacancy_id=vacancy.id,
        total_score=total,
        ai_automation_score=ai_score,
        bitrix_1c_score=bitrix_score,
        best_profile=best_profile,
        match_reasons=reasons,
        risk_flags=risk_flags,
        work_format_flags=_work_flags(vacancy, text),
        scored_at=datetime.now(timezone.utc).isoformat(),
    )
