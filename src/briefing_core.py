from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .utils import json_dumps, json_loads


def briefing_slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")[:60]


def briefing_output_paths(vacancy: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    slug = briefing_slug(vacancy.get("name", "vacancy"))
    stem = f"{vacancy.get('id', '')}_{slug}"
    return {
        "md": out_dir / f"{stem}.md",
        "html": out_dir / f"{stem}.html",
        "json": out_dir / f"{stem}.json",
    }


def _salary_text(vacancy: dict[str, Any], lang: str) -> str:
    salary_from = vacancy.get("salary_from")
    salary_to = vacancy.get("salary_to")
    currency = vacancy.get("salary_currency") or ""
    if salary_from is None and salary_to is None:
        return "Не указана" if lang == "ru" else "Not specified"
    parts = []
    if salary_from is not None:
        parts.append(str(salary_from))
    if salary_to is not None:
        parts.append(str(salary_to))
    text = "–".join(parts) if parts else "?"
    return f"{text} {currency}".strip()


def _risk_items(vacancy: dict[str, Any], details: dict[str, Any] | None, lang: str) -> list[str]:
    risks = json_loads((details or {}).get("risk_flags_json"), None)
    if risks is None:
        risks = json_loads(vacancy.get("risk_flags_json"), [])
    work = json_loads((details or {}).get("work_format_flags_json"), None)
    if work is None:
        work = json_loads(vacancy.get("work_format_flags_json"), [])
    items = [str(r) for r in risks[:4]]
    if vacancy.get("salary_from") is None and vacancy.get("salary_to") is None:
        items.append("Зарплата не указана" if lang == "ru" else "Salary not specified")
    if "remote" not in work and (vacancy.get("schedule_name") or "").lower() not in (
        "remote",
        "удаленная работа",
    ):
        items.append("Remote формат не подтвержден" if lang == "ru" else "Remote format not confirmed")
    return items


def _match_bullets(details: dict[str, Any] | None) -> list[str]:
    matched = json_loads((details or {}).get("matched_keywords_json"), [])
    bullets = []
    for kw in matched[:6]:
        keyword = kw.get("keyword", "")
        field = kw.get("field", "")
        weight = kw.get("weight")
        suffix = f", +{weight}" if weight is not None else ""
        if keyword:
            bullets.append(f"{keyword} ({field}{suffix})")
    return bullets


def _gap_items(details: dict[str, Any] | None, lang: str) -> list[dict[str, str]]:
    excluded = json_loads((details or {}).get("excluded_keywords_json"), [])
    gaps: list[dict[str, str]] = []
    for kw in excluded[:5]:
        keyword = kw.get("keyword", "")
        if not keyword:
            continue
        phrase = (
            f"Есть пересечение по домену, но опыт с {keyword} лучше честно уточнить и закрыть через быстрый онбординг."
            if lang == "ru"
            else f"I have adjacent experience, but I should address the {keyword} gap directly and position it as a fast onboarding item."
        )
        gaps.append(
            {
                "requirement": keyword,
                "status": "gap",
                "interview_phrase": phrase,
            }
        )
    return gaps


def _question_items(vacancy: dict[str, Any], lang: str) -> list[str]:
    schedule = vacancy.get("schedule_name") or "-"
    employment = vacancy.get("employment_name") or "-"
    salary = _salary_text(vacancy, lang)
    if lang == "ru":
        return [
            "Какие 2-3 результата ожидаются от человека в первые 90 дней?",
            f"Как реально устроен формат работы и remote-график ({schedule})?",
            f"Какой тип оформления и занятости предполагается ({employment})?",
            f"Есть ли зарплатный коридор и как устроен пересмотр ({salary})?",
        ]
    return [
        "What are the top 2-3 outcomes expected in the first 90 days?",
        f"What is the actual remote setup and working schedule ({schedule})?",
        f"What employment or contract format is expected ({employment})?",
        f"Is there a salary band and review process ({salary})?",
    ]


def _recommended_action(
    total_score: int,
    decision: str,
    risks: list[str],
    lang: str,
) -> dict[str, str]:
    if decision == "strong_match" and total_score >= 80 and len(risks) <= 2:
        verdict = "Откликаться" if lang == "ru" else "Apply"
        next_step = (
            "Сделать apply-pack, проверить HH-форму и отправить вручную."
            if lang == "ru"
            else "Generate the apply-pack, verify the HH form, and apply manually."
        )
    elif total_score >= 65:
        verdict = "Рассмотреть после уточнений" if lang == "ru" else "Review after clarifications"
        next_step = (
            "Сначала закрыть вопросы по remote / контракту / ключевым гэпам."
            if lang == "ru"
            else "Clarify remote setup, contract details, and the main skill gaps first."
        )
    else:
        verdict = "Низкий приоритет" if lang == "ru" else "Low priority"
        next_step = (
            "Не тратить слот отклика без новой информации."
            if lang == "ru"
            else "Do not spend an application slot without new information."
        )
    return {"verdict": verdict, "next_step": next_step}


def build_briefing_payload(
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    *,
    lang: str = "ru",
) -> dict[str, Any]:
    total_score = int((details or {}).get("total_score") or vacancy.get("total_score") or 0)
    confidence = int((details or {}).get("confidence_score") or 0)
    noise = int((details or {}).get("noise_score") or 0)
    decision = str((details or {}).get("decision") or vacancy.get("decision") or "unknown")
    category_scores = json_loads((details or {}).get("category_scores_json"), {})
    explanation = json_loads((details or {}).get("explanation_json"), {})
    risks = _risk_items(vacancy, details, lang)
    gaps = _gap_items(details, lang)
    action = _recommended_action(total_score, decision, risks, lang)
    published = (vacancy.get("published_at") or "")[:10]
    payload = {
        "vacancy_id": vacancy.get("id", ""),
        "lang": lang,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vacancy": {
            "title": vacancy.get("name", ""),
            "company": vacancy.get("employer_name", ""),
            "area": vacancy.get("area_name", ""),
            "url": vacancy.get("alternate_url", ""),
            "salary": _salary_text(vacancy, lang),
            "schedule": vacancy.get("schedule_name") or "",
            "employment": vacancy.get("employment_name") or "",
            "experience": vacancy.get("experience_name") or "",
            "published_at": published,
            "review_status": vacancy.get("review_status") or "new",
        },
        "score": {
            "total": total_score,
            "confidence": confidence,
            "noise": noise,
            "decision": decision,
            "category_scores": category_scores,
            "decision_logic": explanation.get("decision_logic", ""),
        },
        "blocks": [
            {
                "key": "snapshot",
                "title": "Vacancy Snapshot",
                "items": [
                    f"{vacancy.get('employer_name', '')} — {vacancy.get('name', '')}",
                    f"{vacancy.get('area_name', '')} · {_salary_text(vacancy, lang)}",
                    f"{vacancy.get('schedule_name') or '-'} · {vacancy.get('employment_name') or '-'} · {published or '-'}",
                ],
            },
            {
                "key": "score_verdict",
                "title": "Score Verdict",
                "items": [
                    f"score={total_score}",
                    f"decision={decision}",
                    f"confidence={confidence}",
                    f"noise={noise}",
                    explanation.get("decision_logic", ""),
                ],
            },
            {
                "key": "match_evidence",
                "title": "Match Evidence",
                "items": _match_bullets(details),
            },
            {
                "key": "gaps_objections",
                "title": "Gaps And Objections",
                "items": [
                    f"{gap['requirement']}: {gap['interview_phrase']}"
                    for gap in gaps
                ]
                or ["Существенных гэпов не найдено" if lang == "ru" else "No major gaps detected"],
            },
            {
                "key": "risk_checks",
                "title": "Risk And Checks",
                "items": risks or ["Явных рисков нет" if lang == "ru" else "No obvious risks"],
            },
            {
                "key": "recruiter_questions",
                "title": "Recruiter Questions",
                "items": _question_items(vacancy, lang),
            },
            {
                "key": "recommended_action",
                "title": "Recommended Action",
                "items": [action["verdict"], action["next_step"]],
            },
        ],
        "gaps": gaps,
        "risk_flags": risks,
        "questions": _question_items(vacancy, lang),
        "recommended_action": action,
    }
    return payload


def render_briefing_markdown(payload: dict[str, Any]) -> str:
    vacancy = payload["vacancy"]
    score = payload["score"]
    lines = [
        f"# Briefing: {vacancy['title']}",
        "",
        f"- Vacancy ID: {payload['vacancy_id']}",
        f"- Company: {vacancy['company']}",
        f"- URL: {vacancy['url']}",
        f"- Review status: {vacancy['review_status']}",
        "",
    ]
    for index, block in enumerate(payload["blocks"], 1):
        lines.append(f"## {index}. {block['title']}")
        for item in block["items"]:
            if item:
                lines.append(f"- {item}")
        lines.append("")
    lines.append("## Payload Summary")
    lines.append(f"- score.total: {score['total']}")
    lines.append(f"- score.decision: {score['decision']}")
    lines.append(f"- score.confidence: {score['confidence']}")
    lines.append(f"- score.noise: {score['noise']}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_briefing_html(markdown: str, title: str) -> str:
    html_content = markdown
    html_content = re.sub(r"^## (.+)", r"<h2>\1</h2>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"^# (.+)", r"<h1>\1</h1>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"^- (.+)", r"<li>\1</li>", html_content, flags=re.MULTILINE)
    html_content = html_content.replace("\n\n", "</p><p>")
    html_content = f"<p>{html_content}</p>"
    html_content = html_content.replace("<p><li>", "<ul><li>").replace("</li></p>", "</li></ul>")
    html_content = html_content.replace("<p><h", "<h").replace("</h", "</h")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{background:#0b1020;color:#e8edf7;font:15px system-ui,sans-serif;max-width:880px;margin:40px auto;padding:0 20px;line-height:1.7}}
h1{{font-size:28px;color:#67e8f9}} h2{{font-size:20px;color:#9bf6e8;margin-top:28px}}
ul{{padding-left:20px}} li{{margin:4px 0}} code{{background:#141b2d;padding:2px 6px;border-radius:4px}}
</style></head><body>{html_content}</body></html>"""


def build_briefing_artifact(
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    *,
    lang: str = "ru",
) -> dict[str, Any]:
    payload = build_briefing_payload(vacancy, details, lang=lang)
    markdown = render_briefing_markdown(payload)
    return {
        "payload": payload,
        "markdown": markdown,
        "html": render_briefing_html(markdown, vacancy.get("name", "Briefing")),
        "json": json_dumps(payload),
    }
