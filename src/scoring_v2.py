from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import ScoreResult, Vacancy
from .utils import normalize_text


def score_by_preset(vacancy: Vacancy, preset: dict[str, Any]) -> ScoreResult:
    """Score a vacancy against a search preset.

    Uses include/exclude/boost/penalties from the preset.
    Salary adds up to 10 bonus points when salary_as_bonus is true.
    """
    text = _vacancy_search_text(vacancy)
    title = normalize_text(vacancy.name)
    skills_text = normalize_text(" ".join(vacancy.key_skills))
    desc = normalize_text(vacancy.description_text or "")

    # --- Base score from include matches ---
    base_score = _compute_include_score(text, title, preset)

    # --- Exclude penalties (check against full text for any, title for title) ---
    exclude_penalty = _compute_exclude_penalty(text, title, preset)

    # --- Boost (per-field) ---
    boost = _compute_boost(title, skills_text, desc, preset)

    # --- Custom penalties (per-field) ---
    custom_penalty = _compute_custom_penalties(title, desc, preset)

    # --- Salary bonus ---
    salary_bonus = _compute_salary_bonus(vacancy, preset)

    # --- Freshness ---
    freshness = _freshness(vacancy.published_at)

    total = max(
        0,
        min(
            100,
            base_score
            + boost
            + salary_bonus
            + freshness
            - exclude_penalty
            - custom_penalty,
        ),
    )

    # Determine best_profile (use preset name)
    profile_name = preset.get("_name", "unknown")

    return ScoreResult(
        vacancy_id=vacancy.id,
        total_score=total,
        ai_automation_score=total if profile_name.startswith("ai") else 0,
        bitrix_1c_score=total if profile_name.startswith("bitrix") else 0,
        best_profile=profile_name,
        match_reasons=_build_reasons(
            base_score, boost, salary_bonus, freshness, exclude_penalty, custom_penalty
        ),
        risk_flags=_build_risk_flags(exclude_penalty, custom_penalty),
        work_format_flags=_work_flags(vacancy, text),
        scored_at=datetime.now(timezone.utc).isoformat(),
    )


def _vacancy_search_text(vacancy: Vacancy) -> str:
    fields = [
        vacancy.name,
        vacancy.snippet_requirement,
        vacancy.snippet_responsibility,
        vacancy.description_text,
        " ".join(vacancy.key_skills),
        vacancy.employer_name,
    ]
    return normalize_text(" ".join(f for f in fields if f))


def _compute_include_score(text: str, title: str, preset: dict[str, Any]) -> int:
    """Score based on include.any (full text), include.title (title only), include.all (full text)."""
    include = preset.get("include", {})
    any_keywords = include.get("any", [])
    all_keywords = include.get("all", [])
    title_keywords = include.get("title", [])

    score = 0
    for kw in any_keywords:
        nk = normalize_text(kw)
        if nk in text:
            score += 15
    for kw in title_keywords:
        nk = normalize_text(kw)
        if nk in title:
            score += 15

    if all_keywords:
        all_matched = all(normalize_text(kw) in text for kw in all_keywords)
        if all_matched:
            score += 25

    return min(90, score)


def _compute_exclude_penalty(text: str, title: str, preset: dict[str, Any]) -> int:
    """Penalty for exclude matches. any checks full text, title checks title."""
    exclude = preset.get("exclude", {})
    any_keywords = exclude.get("any", [])
    title_keywords = exclude.get("title", [])

    penalty = 0
    for kw in any_keywords:
        nk = normalize_text(kw)
        if nk in text:
            penalty += 30
    for kw in title_keywords:
        nk = normalize_text(kw)
        if nk in title:
            penalty += 40
    return penalty


def _compute_boost(
    title: str, skills_text: str, desc: str, preset: dict[str, Any]
) -> int:
    """Compute bonus points from boost rules."""
    boost = preset.get("boost", {})
    total = 0

    for field_name, field_text in [
        ("title", title),
        ("skills", skills_text),
        ("description", desc),
    ]:
        rules = boost.get(field_name, {})
        if isinstance(rules, dict):
            for kw, weight in rules.items():
                if normalize_text(kw) in field_text:
                    total += int(weight)
    return min(30, total)


def _compute_custom_penalties(title: str, desc: str, preset: dict[str, Any]) -> int:
    """Compute custom penalties."""
    penalties = preset.get("penalties", {})
    total = 0

    for field_name, field_text in [("title", title), ("description", desc)]:
        rules = penalties.get(field_name, {})
        if isinstance(rules, dict):
            for kw, weight in rules.items():
                if normalize_text(kw) in field_text:
                    total += int(weight)
    return total


def _compute_salary_bonus(vacancy: Vacancy, preset: dict[str, Any]) -> int:
    """Add bonus for vacancies with salary when salary_as_bonus is true."""
    if not preset.get("salary_as_bonus", True):
        return 0
    if vacancy.salary_from or vacancy.salary_to:
        return 5
    return 0


def _freshness(published_at: str | None) -> int:
    from .utils import parse_datetime

    published = parse_datetime(published_at)
    if not published:
        return 0
    age = max(0, (datetime.now(timezone.utc) - published).days)
    return (
        10 if age <= 1 else 7 if age <= 3 else 4 if age <= 7 else 1 if age <= 14 else 0
    )


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


def _build_reasons(
    base: int, boost: int, salary: int, freshness: int, excl: int, pen: int
) -> list[str]:
    reasons: list[str] = []
    if base:
        reasons.append(f"include matches (+{base})")
    if boost:
        reasons.append(f"boost (+{boost})")
    if salary:
        reasons.append(f"salary (+{salary})")
    if freshness:
        reasons.append(f"freshness (+{freshness})")
    if excl:
        reasons.append(f"excludes (-{excl})")
    if pen:
        reasons.append(f"penalties (-{pen})")
    return reasons


def _build_risk_flags(excl: int, pen: int) -> list[str]:
    flags: list[str] = []
    if excl:
        flags.append("exclude_match")
    if pen:
        flags.append("penalty_match")
    return flags
