"""Vacancy detail service — full data, score explain, similar vacancies."""

from __future__ import annotations

import os
from typing import Any

from ..storage import Storage
from ..utils import json_loads


def _get_storage() -> Storage:
    return Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))


def get_full(vacancy_id: str) -> dict[str, Any] | None:
    """Return vacancy with all joined data, parsed JSON fields."""
    storage = _get_storage()
    v = storage.get_vacancy_full(vacancy_id)
    if v is None:
        return None

    # Parse JSON fields
    v["_matched_kw"] = json_loads(v.get("matched_keywords_json"), [])
    v["_excluded_kw"] = json_loads(v.get("excluded_keywords_json"), [])
    v["_risk_flags"] = json_loads(v.get("risk_flags_json"), [])
    v["_work_flags"] = json_loads(v.get("work_format_flags_json"), [])
    v["_category_scores"] = json_loads(v.get("category_scores_json"), {})

    # Cluster info
    cluster = storage.get_cluster_for_vacancy(vacancy_id)
    if cluster:
        v["_cluster"] = {
            "id": cluster.get("cluster_id"),
            "reason": cluster.get("cluster_reason", ""),
            "size": cluster.get("cluster_size", 1),
            "similarity": cluster.get("similarity_score"),
        }

    # Review draft
    review = storage.get_review(vacancy_id)
    v["_draft"] = review.get("cover_letter_draft")
    v["_next_action"] = review.get("next_action")
    v["_next_action_at"] = review.get("next_action_at")

    return v


def get_score_explain(vacancy_id: str) -> dict[str, Any] | None:
    """Return score explanation data for a vacancy."""
    storage = _get_storage()
    v = storage.get_vacancy(vacancy_id)
    if v is None:
        return None

    details = storage.get_score_details(vacancy_id)
    if details is None:
        return {"vacancy_id": vacancy_id, "has_score": False}

    matched = json_loads(details.get("matched_keywords_json"), [])
    excluded = json_loads(details.get("excluded_keywords_json"), [])
    risk_flags = json_loads(details.get("risk_flags_json"), [])
    quality_flags = json_loads(details.get("quality_flags_json"), [])
    cat_scores = json_loads(details.get("category_scores_json"), {})
    explanation = json_loads(details.get("explanation_json"), {})

    # Process keywords for display
    def _kw_list(items: list[Any]) -> list[dict[str, Any]]:
        result = []
        for item in items:
            if isinstance(item, dict):
                result.append(
                    {
                        "keyword": item.get("keyword", ""),
                        "field": item.get("field", ""),
                        "weight": item.get("weight", 0),
                        "reason": item.get("reason", ""),
                    }
                )
            elif isinstance(item, str):
                result.append({"keyword": item, "field": "", "weight": 0, "reason": ""})
        return result

    return {
        "vacancy_id": vacancy_id,
        "has_score": True,
        "total_score": details.get("total_score", 0),
        "confidence_score": details.get("confidence_score", 0),
        "noise_score": details.get("noise_score", 0),
        "decision": details.get("decision", "unknown"),
        "preset_name": details.get("preset_name", ""),
        "category_scores": cat_scores,
        "matched_keywords": _kw_list(matched),
        "excluded_keywords": _kw_list(excluded),
        "risk_flags": risk_flags,
        "quality_flags": quality_flags,
        "explanation": explanation,
    }


def get_similar(vacancy_id: str, limit: int = 10) -> dict[str, Any]:
    """Return similar vacancies: same cluster, same employer, similar title."""
    storage = _get_storage()

    v = storage.get_vacancy_full(vacancy_id)
    if v is None:
        return {"vacancy_id": vacancy_id, "cluster": [], "same_employer": [], "similar_title": []}

    # Same cluster
    cluster_vacancies: list[dict[str, Any]] = []
    cluster = storage.get_cluster_for_vacancy(vacancy_id)
    if cluster:
        cid = cluster["cluster_id"]
        with storage.connect() as conn:
            rows = conn.execute(
                "SELECT vc.vacancy_id FROM vacancy_clusters vc"
                " WHERE vc.cluster_id = ? AND vc.vacancy_id != ?"
                " LIMIT ?",
                (cid, vacancy_id, limit),
            ).fetchall()
            cluster_ids = [r["vacancy_id"] for r in rows]
        for cvid in cluster_ids:
            cdata = storage.get_vacancy_full(cvid)
            if cdata:
                cluster_vacancies.append(_summarize(cdata))

    # Same employer
    same_employer: list[dict[str, Any]] = []
    employer = v.get("employer_name", "")
    if employer:
        with storage.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM vacancies WHERE employer_name = ?"
                " AND id != ? ORDER BY last_seen_at DESC LIMIT ?",
                (employer, vacancy_id, limit),
            ).fetchall()
            for (eid,) in rows:
                edata = storage.get_vacancy_full(eid)
                if edata:
                    same_employer.append(_summarize(edata))

    # Similar title (simple string contains heuristic)
    similar_title: list[dict[str, Any]] = []
    name = v.get("name", "")
    if name and len(name) > 5:
        words = [w.lower() for w in name.split() if len(w) > 3]
        if words:
            # Use first 2 meaningful words for search
            search_words = words[:2]
            like_clauses = " OR ".join("v.name LIKE ?" for _ in search_words)
            with storage.connect() as conn:
                rows = conn.execute(
                    f"SELECT v.id, v.name, s.total_score, v.employer_name"
                    f" FROM vacancies v LEFT JOIN scores s ON s.vacancy_id=v.id"
                    f" WHERE ({like_clauses}) AND v.id != ?"
                    f" ORDER BY COALESCE(s.total_score,0) DESC LIMIT ?",
                    [f"%{w}%" for w in search_words] + [vacancy_id, limit],
                ).fetchall()
            for row in rows:
                similar_title.append(
                    {
                        "id": row["id"],
                        "name": row["name"] or "",
                        "total_score": row["total_score"] or 0,
                        "employer_name": row["employer_name"] or "",
                    }
                )

    return {
        "vacancy_id": vacancy_id,
        "cluster": cluster_vacancies,
        "same_employer": same_employer,
        "similar_title": similar_title,
    }


def _summarize(data: dict[str, Any]) -> dict[str, Any]:
    """Extract summary fields from a full vacancy dict."""
    return {
        "id": data.get("id", ""),
        "name": data.get("name", "")[:80],
        "employer_name": data.get("employer_name", ""),
        "total_score": data.get("total_score", 0),
        "decision": data.get("decision", ""),
        "review_status": data.get("review_status", "new"),
        "alternate_url": data.get("alternate_url", ""),
    }


def generate_apply_pack_preview(
    vacancy_id: str, lang: str = "ru", style: str = "medium"
) -> dict[str, Any]:
    """Generate apply pack and return preview data."""
    import argparse

    from ..commands.apply_pack import command_apply_pack

    pack_args = argparse.Namespace(
        vacancy_id=vacancy_id,
        top=None,
        limit=None,
        decision=None,
        preset=None,
        min_score=0,
        lang=lang,
        format="both",
        style=style,
        template=None,
        save_review=False,
        overwrite=False,
    )
    try:
        rc = command_apply_pack(pack_args)
        return {
            "ok": rc == 0,
            "message": f"Apply pack generated for {vacancy_id}",
            "vacancy_id": vacancy_id,
            "lang": lang,
            "style": style,
        }
    except Exception as exc:
        return {"ok": False, "message": f"Apply pack failed: {exc}"}
