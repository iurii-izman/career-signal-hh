from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import KeywordHit, ScoreDetails, ScoreResult, Vacancy
from .utils import normalize_text, parse_datetime

# Field weight multipliers
FIELD_WEIGHTS = {
    "title": 3.0,
    "skills": 2.0,
    "snippet": 1.5,
    "description": 1.0,
    "employer": 0.5,
}

DECISION_THRESHOLDS = {
    "strong_match": 85,
    "queue": 70,
    "review_later": 50,
    "weak_match": 25,
}


def score_by_preset(vacancy: Vacancy, preset: dict[str, Any]) -> ScoreResult:
    """Score a vacancy against a preset. Returns ScoreResult + stores ScoreDetails."""
    details = compute_score_details(vacancy, preset)
    return _to_score_result(details)


def compute_score_details(vacancy: Vacancy, preset: dict[str, Any]) -> ScoreDetails:
    """Full explainable scoring with field weights and keyword tracking."""
    preset_name = preset.get("_name", "unknown")
    thresholds = preset.get("decision_thresholds", DECISION_THRESHOLDS)
    if isinstance(thresholds, dict):
        thresholds = {**DECISION_THRESHOLDS, **thresholds}

    # --- Field extraction ---
    title = normalize_text(vacancy.name)
    skills_txt = normalize_text(" ".join(vacancy.key_skills))
    snippet = normalize_text(f"{vacancy.snippet_requirement} {vacancy.snippet_responsibility}")
    description = normalize_text(vacancy.description_text or "")
    employer = normalize_text(vacancy.employer_name or "")

    fields = {
        "title": title,
        "skills": skills_txt,
        "snippet": snippet,
        "description": description,
        "employer": employer,
    }

    matched: list[KeywordHit] = []
    excluded: list[KeywordHit] = []
    risk_flags: list[str] = []
    category_scores: dict[str, int] = {}

    # --- Include scoring ---
    include_score = _score_include(preset, fields, matched)
    category_scores["include"] = include_score

    # --- Boost scoring ---
    boost_score = _score_boost(preset, fields, matched)
    category_scores["boost"] = boost_score

    # --- Exclude penalties ---
    exclude_penalty = _score_exclude(preset, fields, excluded, risk_flags)
    category_scores["exclude"] = -exclude_penalty

    # --- Custom penalties ---
    penalty_score = _score_penalties(preset, fields, excluded, risk_flags)
    category_scores["penalties"] = -penalty_score

    # --- Salary bonus ---
    salary_bonus = _score_salary(vacancy, preset)
    category_scores["salary"] = salary_bonus

    # --- Remote bonus ---
    remote_bonus, remote_risk = _score_remote(vacancy, preset)
    category_scores["remote"] = remote_bonus
    if remote_risk:
        risk_flags.extend(remote_risk)
        if remote_bonus < 0:
            category_scores["remote_penalty"] = remote_bonus
            category_scores["remote"] = 0

    # --- Freshness ---
    freshness = _freshness(vacancy.published_at)
    category_scores["freshness"] = freshness

    # --- Total ---
    total = max(
        0,
        min(
            100,
            include_score
            + boost_score
            + salary_bonus
            + remote_bonus
            + freshness
            - exclude_penalty
            - penalty_score,
        ),
    )

    # --- Decision ---
    decision = _compute_decision(total, thresholds)

    # --- Work format ---
    work_flags = _work_flags(vacancy)

    # --- Explanation ---
    explanation = {
        "total_formula": (
            f"include({include_score}) + boost({boost_score}) + "
            f"salary({salary_bonus}) + remote({remote_bonus}) + "
            f"freshness({freshness}) - exclude({exclude_penalty}) - "
            f"penalties({penalty_score}) = {total}"
        ),
        "decision_thresholds": thresholds,
        "preset_name": preset_name,
    }

    return ScoreDetails(
        vacancy_id=vacancy.id,
        preset_name=preset_name,
        total_score=total,
        decision=decision,
        category_scores=category_scores,
        matched_keywords=matched,
        excluded_keywords=excluded,
        risk_flags=risk_flags + ([f"work:{f}" for f in work_flags if f != "remote"]),
        work_format_flags=work_flags,
        explanation=explanation,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )


def _score_include(
    preset: dict[str, Any], fields: dict[str, str], matched: list[KeywordHit]
) -> int:
    include = preset.get("include", {})
    any_kw = include.get("any", [])
    all_kw = include.get("all", [])
    title_kw = include.get("title", [])

    total = 0

    # include.any: check all fields
    for kw in any_kw:
        nk = normalize_text(kw)
        for fname, ftext in fields.items():
            if nk in ftext:
                weight = int(10 * FIELD_WEIGHTS.get(fname, 1.0))
                total += weight
                matched.append(KeywordHit(keyword=kw, field=fname, weight=weight, reason="include"))
                break  # one match per keyword

    # include.title: check title only
    for kw in title_kw:
        nk = normalize_text(kw)
        if nk in fields["title"]:
            weight = int(12 * FIELD_WEIGHTS["title"])
            total += weight
            matched.append(KeywordHit(keyword=kw, field="title", weight=weight, reason="include"))
        elif nk in fields["snippet"]:
            weight = int(8 * FIELD_WEIGHTS["snippet"])
            total += weight
            matched.append(KeywordHit(keyword=kw, field="snippet", weight=weight, reason="include"))

    # include.all: ALL must match in full text
    if all_kw:
        full_text = " ".join(fields.values())
        if all(normalize_text(kw) in full_text for kw in all_kw):
            total += 20
            for kw in all_kw:
                matched.append(KeywordHit(keyword=kw, field="any", weight=10, reason="include.all"))

    return min(90, total)


def _score_boost(preset: dict[str, Any], fields: dict[str, str], matched: list[KeywordHit]) -> int:
    boost = preset.get("boost", {})
    total = 0
    for fname, rules in boost.items():
        if fname not in fields:
            continue
        ftext = fields[fname]
        if isinstance(rules, dict):
            for kw, w in rules.items():
                if normalize_text(kw) in ftext:
                    weight = int(w)
                    total += weight
                    matched.append(
                        KeywordHit(keyword=kw, field=fname, weight=weight, reason="boost")
                    )
    return min(30, total)


def _score_exclude(
    preset: dict[str, Any],
    fields: dict[str, str],
    excluded: list[KeywordHit],
    risk_flags: list[str],
) -> int:
    exclude = preset.get("exclude", {})
    any_kw = exclude.get("any", [])
    title_kw = exclude.get("title", [])

    penalty = 0
    full_text = " ".join(fields.values())

    for kw in any_kw:
        nk = normalize_text(kw)
        if nk in fields["title"]:
            penalty += 30
            excluded.append(KeywordHit(keyword=kw, field="title", weight=-30, reason="exclude"))
            risk_flags.append("exclude_match")
        elif nk in full_text:
            penalty += 20
            excluded.append(KeywordHit(keyword=kw, field="text", weight=-20, reason="exclude"))
            if "exclude_match" not in risk_flags:
                risk_flags.append("exclude_match")

    for kw in title_kw:
        nk = normalize_text(kw)
        if nk in fields["title"]:
            penalty += 40
            excluded.append(KeywordHit(keyword=kw, field="title", weight=-40, reason="exclude"))
            risk_flags.append("exclude_title")

    return penalty


def _score_penalties(
    preset: dict[str, Any],
    fields: dict[str, str],
    excluded: list[KeywordHit],
    risk_flags: list[str],
) -> int:
    penalties = preset.get("penalties", {})
    total = 0
    for fname, rules in penalties.items():
        if fname not in fields:
            continue
        ftext = fields[fname]
        if isinstance(rules, dict):
            for kw, w in rules.items():
                if normalize_text(kw) in ftext:
                    weight = int(w)
                    total += weight
                    excluded.append(
                        KeywordHit(keyword=kw, field=fname, weight=-weight, reason="penalty")
                    )
                    if not risk_flags or "penalty_match" not in risk_flags:
                        risk_flags.append("penalty_match")
    return total


def _score_salary(vacancy: Vacancy, preset: dict[str, Any]) -> int:
    if not preset.get("salary_as_bonus", True):
        return 0
    bonus = 0
    if vacancy.salary_from or vacancy.salary_to:
        bonus += 5
    if vacancy.salary_currency and vacancy.salary_currency.upper() in ("USD", "EUR"):
        bonus += 2
    # High salary rough bonus
    amount = vacancy.salary_from or vacancy.salary_to or 0
    if amount >= 300000:
        bonus += 3
    elif amount >= 200000:
        bonus += 2
    elif amount >= 100000:
        bonus += 1
    return bonus


def _score_remote(vacancy: Vacancy, preset: dict[str, Any]) -> tuple[int, list[str]]:
    if not preset.get("remote_only", True):
        return 0, []
    schedule = normalize_text(vacancy.schedule_name or "")
    is_remote = "remote" in schedule or "удален" in schedule or "удалён" in schedule
    is_hybrid = "hybrid" in schedule or "гибрид" in schedule
    if is_remote:
        return 10, []
    if is_hybrid:
        return 5, ["hybrid_not_full_remote"]
    # Unknown or onsite
    return -5, ["not_remote"]


def _freshness(published_at: str | None) -> int:
    published = parse_datetime(published_at)
    if not published:
        return 0
    age = max(0, (datetime.now(timezone.utc) - published).days)
    return 10 if age <= 1 else 7 if age <= 3 else 4 if age <= 7 else 1 if age <= 14 else 0


def _work_flags(vacancy: Vacancy) -> list[str]:
    schedule = normalize_text(vacancy.schedule_name or "")
    flags: list[str] = []
    if "удален" in schedule or "remote" in schedule or "удалён" in schedule:
        flags.append("remote")
    if "гибрид" in schedule or "hybrid" in schedule:
        flags.append("hybrid")
    if not flags and ("офис" in schedule or "полный день" in schedule):
        flags.append("onsite")
    return flags or ["unknown"]


def _compute_decision(total: int, thresholds: dict[str, int]) -> str:
    if total >= thresholds.get("strong_match", 85):
        return "strong_match"
    if total >= thresholds.get("queue", 70):
        return "queue"
    if total >= thresholds.get("review_later", 50):
        return "review_later"
    if total >= thresholds.get("weak_match", 25):
        return "weak_match"
    return "auto_hide"


def _to_score_result(details: ScoreDetails) -> ScoreResult:
    """Convert ScoreDetails to legacy ScoreResult for backward compatibility."""
    reasons = [f"{kw.keyword} ({kw.field}, +{kw.weight})" for kw in details.matched_keywords[:6]]
    if details.category_scores.get("freshness", 0):
        reasons.append(f"freshness (+{details.category_scores['freshness']})")
    if details.category_scores.get("salary", 0):
        reasons.append(f"salary (+{details.category_scores['salary']})")
    if details.category_scores.get("remote", 0):
        reasons.append(f"remote (+{details.category_scores['remote']})")

    return ScoreResult(
        vacancy_id=details.vacancy_id,
        total_score=details.total_score,
        ai_automation_score=details.total_score if details.preset_name.startswith("ai") else 0,
        bitrix_1c_score=details.total_score if details.preset_name.startswith("bitrix") else 0,
        best_profile=details.preset_name,
        match_reasons=reasons,
        risk_flags=details.risk_flags,
        work_format_flags=details.work_format_flags,
        scored_at=details.scored_at,
    )
