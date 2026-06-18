"""Analytics service — summary, funnel, preset performance, skills, employers."""

from __future__ import annotations

import os
from typing import Any

from ..storage import Storage
from ..utils import json_loads


def _get_storage() -> Storage:
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def get_summary() -> dict[str, Any]:
    """Return analytics summary counts."""
    storage = _get_storage()
    with storage.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
        new_24h = conn.execute(
            "SELECT COUNT(*) FROM vacancies"
            " WHERE datetime(first_seen_at) >= datetime('now','-1 day')"
        ).fetchone()[0]
        new_7d = conn.execute(
            "SELECT COUNT(*) FROM vacancies"
            " WHERE datetime(first_seen_at) >= datetime('now','-7 days')"
        ).fetchone()[0]
        new_30d = conn.execute(
            "SELECT COUNT(*) FROM vacancies"
            " WHERE datetime(first_seen_at) >= datetime('now','-30 days')"
        ).fetchone()[0]
        avg_score = conn.execute("SELECT COALESCE(AVG(total_score),0) FROM scores").fetchone()[0]
        strong = conn.execute(
            "SELECT COUNT(*) FROM score_details WHERE decision='strong_match'"
        ).fetchone()[0]
        queue = conn.execute(
            "SELECT COUNT(*) FROM score_details WHERE decision IN ('strong_match','queue')"
        ).fetchone()[0]
        remote = conn.execute(
            "SELECT COUNT(*) FROM scores WHERE work_format_flags_json LIKE '%remote%'"
        ).fetchone()[0]
        with_salary = conn.execute(
            "SELECT COUNT(*) FROM vacancies WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL"
        ).fetchone()[0]
        applied = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='applied'"
        ).fetchone()[0]
        interview = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='interview'"
        ).fetchone()[0]
        offer = conn.execute(
            "SELECT COUNT(*) FROM vacancy_reviews WHERE status='offer'"
        ).fetchone()[0]

    return {
        "total": total,
        "new_24h": new_24h,
        "new_7d": new_7d,
        "new_30d": new_30d,
        "avg_score": round(avg_score, 1),
        "strong_match": strong,
        "queue_strong_plus_queue": queue,
        "remote": remote,
        "with_salary": with_salary,
        "applied": applied,
        "interview": interview,
        "offer": offer,
    }


def get_funnel() -> list[dict[str, Any]]:
    """Return review funnel stages."""
    storage = _get_storage()
    stages = [
        ("new", "COALESCE(r.status,'new')='new'"),
        ("interesting", "r.status='interesting'"),
        ("maybe", "r.status='maybe'"),
        ("applied", "r.status='applied'"),
        ("interview", "r.status='interview'"),
        ("offer", "r.status='offer'"),
        ("rejected", "r.status='rejected'"),
        ("archived", "r.status='archived'"),
    ]
    total = 0
    with storage.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]

    result: list[dict[str, Any]] = []
    for name, where in stages:
        with storage.connect() as conn:
            cnt = conn.execute(
                f"SELECT COUNT(*) FROM vacancies v "
                f"LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id"
                f" WHERE {where}"
            ).fetchone()[0]
        pct = round(100 * cnt / max(1, total), 1)
        result.append({"stage": name, "count": cnt, "percent": pct})

    return result


def get_preset_performance() -> list[dict[str, Any]]:
    """Return per-preset performance metrics."""
    storage = _get_storage()
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT"
            " COALESCE(sd.preset_name, s.best_profile, 'unknown') preset,"
            " COUNT(*) cnt, COALESCE(AVG(s.total_score),0) avg_score,"
            " SUM(CASE WHEN sd.decision='strong_match' THEN 1 ELSE 0 END)"
            " strong,"
            " SUM(CASE WHEN sd.decision IN ('strong_match','queue')"
            " THEN 1 ELSE 0 END) queue,"
            " SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END)"
            " applied,"
            " SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END)"
            " rejected,"
            " SUM(CASE WHEN r.status='interview' THEN 1 ELSE 0 END)"
            " interview,"
            " SUM(CASE WHEN r.status='offer' THEN 1 ELSE 0 END) offer"
            " FROM vacancies v"
            " LEFT JOIN scores s ON s.vacancy_id=v.id"
            " LEFT JOIN score_details sd ON sd.vacancy_id=v.id"
            " LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id"
            " GROUP BY preset ORDER BY cnt DESC"
        ).fetchall()

    return [
        {
            "preset": row[0],
            "vacancies": row[1],
            "avg_score": round(row[2], 1),
            "strong": row[3],
            "queue": row[4],
            "applied": row[5],
            "rejected": row[6],
            "interview": row[7],
            "offer": row[8],
        }
        for row in rows
    ]


def get_top_skills(limit: int = 30) -> list[dict[str, Any]]:
    """Return top skills across all vacancies."""
    storage = _get_storage()
    skill_counts: dict[str, dict[str, Any]] = {}
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT key_skills_json, s.total_score, s.best_profile"
            " FROM vacancies v"
            " LEFT JOIN scores s ON s.vacancy_id=v.id"
            " WHERE key_skills_json IS NOT NULL"
        ).fetchall()
        for row in rows:
            skills = json_loads(row[0], [])
            score = row[1] or 0
            profile = row[2] or ""
            for skill in skills:
                s = skill.strip().lower()
                if not s or len(s) < 2:
                    continue
                if s not in skill_counts:
                    skill_counts[s] = {
                        "count": 0,
                        "total_score": 0,
                        "presets": set(),
                    }
                skill_counts[s]["count"] += 1
                skill_counts[s]["total_score"] += score
                if profile:
                    skill_counts[s]["presets"].add(profile)

    items = sorted(skill_counts.items(), key=lambda x: -x[1]["count"])[:limit]
    return [
        {
            "skill": skill,
            "count": data["count"],
            "avg_score": round(data["total_score"] / max(1, data["count"]), 1),
            "presets": ", ".join(sorted(data["presets"])),
        }
        for skill, data in items
    ]


def get_top_employers(limit: int = 20) -> list[dict[str, Any]]:
    """Return top employers by vacancy count."""
    storage = _get_storage()
    with storage.connect() as conn:
        rows = conn.execute(
            "SELECT employer_name, COUNT(*) cnt,"
            " COALESCE(AVG(s.total_score),0) avg_score,"
            " SUM(CASE WHEN r.status='applied' THEN 1 ELSE 0 END)"
            " applied,"
            " SUM(CASE WHEN r.status='interview' THEN 1 ELSE 0 END)"
            " interview,"
            " SUM(CASE WHEN sd.decision='strong_match'"
            " THEN 1 ELSE 0 END) strong"
            " FROM vacancies v"
            " LEFT JOIN scores s ON s.vacancy_id=v.id"
            " LEFT JOIN vacancy_reviews r ON r.vacancy_id=v.id"
            " LEFT JOIN score_details sd ON sd.vacancy_id=v.id"
            " WHERE v.employer_name IS NOT NULL AND v.employer_name != ''"
            " GROUP BY v.employer_name ORDER BY cnt DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return [
        {
            "employer": row[0] or "?",
            "vacancies": row[1],
            "avg_score": round(row[2], 1),
            "applied": row[3],
            "interview": row[4],
            "strong": row[5],
        }
        for row in rows
    ]
