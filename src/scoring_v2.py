"""Scoring engine v2 — field-aware, confidence-calibrated with safe matching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .matching import safe_keyword_match
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
    """Full explainable scoring with field weights, safe matching, confidence & noise."""
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
    quality_flags: list[str] = []
    category_scores: dict[str, int] = {}

    # --- Include scoring ---
    include_score = _score_include(preset, fields, matched, quality_flags)
    category_scores["include"] = include_score

    # --- Boost scoring ---
    boost_score = _score_boost(preset, fields, matched, quality_flags)
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

    # --- Quality flags ---
    _set_quality_flags(vacancy, fields, matched, excluded, risk_flags, quality_flags)

    # --- Confidence score ---
    confidence = _compute_confidence(fields, matched, quality_flags, total)

    # --- Noise score ---
    noise = _compute_noise(excluded, risk_flags, quality_flags)

    # --- Decision (adjusted by confidence/noise) ---
    decision = _compute_decision(total, confidence, noise, thresholds)

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
        "confidence_breakdown": _confidence_breakdown(fields, matched, quality_flags),
        "noise_breakdown": _noise_breakdown(excluded, risk_flags, quality_flags),
        "decision_logic": f"total={total}, confidence={confidence}, noise={noise} → {decision}",
        "decision_thresholds": thresholds,
        "preset_name": preset_name,
    }

    return ScoreDetails(
        vacancy_id=vacancy.id,
        preset_name=preset_name,
        total_score=total,
        confidence_score=confidence,
        noise_score=noise,
        decision=decision,
        category_scores=category_scores,
        matched_keywords=matched,
        excluded_keywords=excluded,
        risk_flags=risk_flags + ([f"work:{f}" for f in work_flags if f != "remote"]),
        quality_flags=quality_flags,
        work_format_flags=work_flags,
        explanation=explanation,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Quality flags
# ═══════════════════════════════════════════════════════════════════════════


def _set_quality_flags(
    vacancy: Vacancy,
    fields: dict[str, str],
    matched: list[KeywordHit],
    excluded: list[KeywordHit],
    risk_flags: list[str],
    quality_flags: list[str],
) -> None:
    """Set quality flags based on match characteristics."""
    title_matches = [kw for kw in matched if kw.field == "title"]
    skills_matches = [kw for kw in matched if kw.field == "skills"]
    desc_only = [
        kw
        for kw in matched
        if kw.field == "description" and kw.field != "title" and kw.field != "skills"
    ]

    if title_matches:
        quality_flags.append("title_match")
    if skills_matches:
        quality_flags.append("skills_match")
    if not title_matches and not skills_matches and matched:
        quality_flags.append("description_only_match")
    if not vacancy.description_text or not vacancy.description_text.strip():
        quality_flags.append("missing_description")
    if not vacancy.salary_from and not vacancy.salary_to:
        quality_flags.append("missing_salary")
    # Remote flags
    schedule = normalize_text(vacancy.schedule_name or "")
    if "remote" in schedule or "удален" in schedule or "удалён" in schedule:
        quality_flags.append("remote_confirmed")
    elif not schedule:
        quality_flags.append("remote_unclear")
    if len(excluded) >= 3:
        quality_flags.append("many_excludes")
    # Weak title relevance
    if not title_matches and matched:
        quality_flags.append("weak_title_relevance")


# ═══════════════════════════════════════════════════════════════════════════
# Confidence computation
# ═══════════════════════════════════════════════════════════════════════════


def _compute_confidence(
    fields: dict[str, str],
    matched: list[KeywordHit],
    quality_flags: list[str],
    total_score: int,
) -> int:
    """Compute confidence score 0-100 based on match quality."""
    base = 50  # neutral

    # Title match is a strong signal
    title_matches = [kw for kw in matched if kw.field == "title"]
    skills_matches = [kw for kw in matched if kw.field == "skills"]

    if title_matches:
        base += 25
    if skills_matches:
        base += 15
    if title_matches and skills_matches:
        base += 10  # combined bonus

    # Penalize description-only matches
    if "description_only_match" in quality_flags:
        base -= 20
    if "missing_description" in quality_flags:
        base -= 10
    if "weak_title_relevance" in quality_flags:
        base -= 15

    # More keyword matches = higher confidence
    if len(matched) >= 5:
        base += 10
    elif len(matched) >= 3:
        base += 5

    # Score-correlated boost
    if total_score >= 80:
        base += 10
    elif total_score >= 60:
        base += 5

    return max(0, min(100, base))


def _confidence_breakdown(
    fields: dict[str, str],
    matched: list[KeywordHit],
    quality_flags: list[str],
) -> str:
    """Human-readable confidence breakdown."""
    parts = ["base=50"]
    title_matches = [kw for kw in matched if kw.field == "title"]
    skills_matches = [kw for kw in matched if kw.field == "skills"]
    if title_matches:
        parts.append("title_match=+25")
    if skills_matches:
        parts.append("skills_match=+15")
    if title_matches and skills_matches:
        parts.append("combined=+10")
    if "description_only_match" in quality_flags:
        parts.append("desc_only=-20")
    if "weak_title_relevance" in quality_flags:
        parts.append("weak_title=-15")
    return ", ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Noise computation
# ═══════════════════════════════════════════════════════════════════════════


def _compute_noise(
    excluded: list[KeywordHit],
    risk_flags: list[str],
    quality_flags: list[str],
) -> int:
    """Compute noise score 0-100 (higher = more noise/suspicion)."""
    noise = 0

    # Each excluded keyword adds noise
    noise += len(excluded) * 10

    # Risk flags
    if "exclude_match" in risk_flags:
        noise += 15
    if "exclude_title" in risk_flags:
        noise += 20
    if "penalty_match" in risk_flags:
        noise += 10

    # Quality flags that indicate noise
    if "many_excludes" in quality_flags:
        noise += 15
    if "missing_description" in quality_flags:
        noise += 10
    if "remote_unclear" in quality_flags:
        noise += 5

    return max(0, min(100, noise))


def _noise_breakdown(
    excluded: list[KeywordHit],
    risk_flags: list[str],
    quality_flags: list[str],
) -> str:
    """Human-readable noise breakdown."""
    parts = []
    if excluded:
        parts.append(f"excludes={len(excluded)}x10")
    if "exclude_title" in risk_flags:
        parts.append("exclude_title=+20")
    if "many_excludes" in quality_flags:
        parts.append("many_excludes=+15")
    return ", ".join(parts) if parts else "clean"


# ═══════════════════════════════════════════════════════════════════════════
# Decision (confidence/noise-adjusted)
# ═══════════════════════════════════════════════════════════════════════════


def _compute_decision(
    total: int,
    confidence: int,
    noise: int,
    thresholds: dict[str, int],
) -> str:
    """Compute decision considering total_score, confidence, and noise.

    Confidence/noise adjustment:
    - High score but low confidence → downgrade to review_later
    - High noise → boost the effective threshold for strong_match
    """
    # Noise-adjusted threshold: each 10 noise points raise threshold by 2
    noise_penalty = noise // 5  # up to 20 points
    adjusted_total = total - noise_penalty

    if confidence < 30 and total >= thresholds.get("strong_match", 85):
        return "review_later"  # Don't trust high score with low confidence
    if confidence < 20 and total >= thresholds.get("queue", 70):
        return "review_later"

    if adjusted_total >= thresholds.get("strong_match", 85):
        return "strong_match"
    if adjusted_total >= thresholds.get("queue", 70):
        return "queue"
    if adjusted_total >= thresholds.get("review_later", 50):
        return "review_later"
    if adjusted_total >= thresholds.get("weak_match", 25):
        return "weak_match"
    return "auto_hide"


# ═══════════════════════════════════════════════════════════════════════════
# Scoring functions (now using safe matching)
# ═══════════════════════════════════════════════════════════════════════════


def _score_include(
    preset: dict[str, Any],
    fields: dict[str, str],
    matched: list[KeywordHit],
    quality_flags: list[str],
) -> int:
    include = preset.get("include", {})
    any_kw = include.get("any", [])
    all_kw = include.get("all", [])
    title_kw = include.get("title", [])

    total = 0
    matched_keywords: set[str] = set()  # Prevent duplicate hits

    # include.any: check all fields using safe matching
    for kw in any_kw:
        if kw in matched_keywords:
            continue
        for fname, ftext in fields.items():
            ok, match_type = safe_keyword_match(kw, ftext)
            if ok:
                weight = int(10 * FIELD_WEIGHTS.get(fname, 1.0))
                total += weight
                matched.append(
                    KeywordHit(
                        keyword=kw,
                        field=fname,
                        weight=weight,
                        reason=f"include.{match_type}",
                    )
                )
                matched_keywords.add(kw)
                break

    # include.title: only title/snippet
    for kw in title_kw:
        if kw in matched_keywords:
            continue
        for fname in ("title", "snippet"):
            ftext = fields.get(fname, "")
            ok, match_type = safe_keyword_match(kw, ftext)
            if ok:
                weight = (
                    int(12 * FIELD_WEIGHTS.get(fname, 1.0))
                    if fname == "title"
                    else int(8 * FIELD_WEIGHTS["snippet"])
                )
                total += weight
                matched.append(
                    KeywordHit(
                        keyword=kw,
                        field=fname,
                        weight=weight,
                        reason=f"include.{match_type}",
                    )
                )
                matched_keywords.add(kw)
                break

    # include.all: ALL keywords must match somewhere
    if all_kw:
        full_text = " ".join(fields.values())
        if all(safe_keyword_match(kw, full_text)[0] for kw in all_kw):
            total += 20
            for kw in all_kw:
                if kw not in matched_keywords:
                    matched.append(
                        KeywordHit(keyword=kw, field="any", weight=10, reason="include.all")
                    )
                    matched_keywords.add(kw)

    return min(90, total)


def _score_boost(
    preset: dict[str, Any],
    fields: dict[str, str],
    matched: list[KeywordHit],
    quality_flags: list[str],
) -> int:
    boost = preset.get("boost", {})
    total = 0
    for fname, rules in boost.items():
        if fname not in fields:
            continue
        ftext = fields[fname]
        if isinstance(rules, dict):
            for kw, w in rules.items():
                ok, match_type = safe_keyword_match(kw, ftext)
                if ok:
                    weight = int(w)
                    total += weight
                    matched.append(
                        KeywordHit(
                            keyword=kw,
                            field=fname,
                            weight=weight,
                            reason=f"boost.{match_type}",
                        )
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
        ok, match_type = safe_keyword_match(kw, fields["title"])
        if ok:
            penalty += 30
            excluded.append(
                KeywordHit(
                    keyword=kw,
                    field="title",
                    weight=-30,
                    reason=f"exclude.{match_type}",
                )
            )
            risk_flags.append("exclude_match")
        else:
            ok2, mt2 = safe_keyword_match(kw, full_text)
            if ok2:
                penalty += 20
                excluded.append(
                    KeywordHit(
                        keyword=kw,
                        field="text",
                        weight=-20,
                        reason=f"exclude.{mt2}",
                    )
                )
                if "exclude_match" not in risk_flags:
                    risk_flags.append("exclude_match")

    for kw in title_kw:
        ok, match_type = safe_keyword_match(kw, fields["title"])
        if ok:
            penalty += 40
            excluded.append(
                KeywordHit(
                    keyword=kw,
                    field="title",
                    weight=-40,
                    reason=f"exclude.{match_type}",
                )
            )
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
                ok, match_type = safe_keyword_match(kw, ftext)
                if ok:
                    weight = int(w)
                    total += weight
                    excluded.append(
                        KeywordHit(
                            keyword=kw,
                            field=fname,
                            weight=-weight,
                            reason=f"penalty.{match_type}",
                        )
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
