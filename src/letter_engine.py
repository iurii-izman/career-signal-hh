from __future__ import annotations

import re
from typing import Any

import yaml

from .utils import json_loads

CANDIDATE_PATH = "config/candidate.yaml"

GENERIC_PHRASES = {
    "ru": [
        "буду рад обсудить",
        "готов обсудить сотрудничество",
        "меня заинтересовала вакансия",
        "мой профиль",
        "что я могу привнести",
        "буду рад познакомиться",
    ],
    "en": [
        "looking forward to discussing",
        "i would be delighted to connect",
        "i am excited about",
        "my profile",
        "what i bring",
        "i'd be happy to discuss how i can contribute to your team",
    ],
}

AI_ROLE_HINTS = (
    "ai",
    "llm",
    "rag",
    "gpt",
    "langchain",
    "langgraph",
    "n8n",
    "make",
    "automation",
)
BITRIX_ROLE_HINTS = (
    "битрикс",
    "bitrix",
    "crm",
    "1с",
    "1c",
    "integration",
    "интегра",
    "business process",
    "бизнес-процесс",
)
GENERIC_ROLE_WORDS = {
    "engineer",
    "developer",
    "analyst",
    "specialist",
    "remote",
    "senior",
    "middle",
    "junior",
    "lead",
    "python",
    "system",
    "systems",
    "automation",
    "аналитик",
    "разработчик",
    "инженер",
    "удаленно",
    "удаленная",
}
EVIDENCE_ANCHORS = {
    "ai": {"llm", "rag", "n8n", "make", "webhook", "bitrix24", "python", "rest api"},
    "bitrix": {"bitrix24", "crm", "1c", "1с", "rest api", "webhooks", "bpmn"},
    "default": {"crm", "integrations", "rest api", "sql", "python", "bitrix24"},
}
STYLE_WORD_LIMITS = {
    "short": (45, 110),
    "medium": (70, 170),
    "detailed": (90, 230),
}


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _load_candidate() -> dict[str, Any]:
    try:
        with open(CANDIDATE_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalize_token(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s+-]", " ", (text or "").lower())).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w+-]+", text, flags=re.UNICODE))


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", _normalize_text(text))
    return [p.strip() for p in parts if p.strip()]


def _cleanup_letter(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                cleaned.append("")
            blank = True
            continue
        cleaned.append(re.sub(r"\s{2,}", " ", line.strip()))
        blank = False
    return "\n".join(cleaned).strip()


def _pick_role_family(vacancy: dict[str, Any], details: dict[str, Any] | None) -> str:
    text_parts = [
        vacancy.get("name", ""),
        vacancy.get("description_text", ""),
        vacancy.get("snippet_requirement", ""),
        vacancy.get("snippet_responsibility", ""),
        vacancy.get("best_profile", ""),
        (details or {}).get("preset_name", ""),
    ]
    text = " ".join(str(part or "") for part in text_parts).lower()
    if any(token in text for token in AI_ROLE_HINTS):
        return "ai"
    if any(token in text for token in BITRIX_ROLE_HINTS):
        return "bitrix"
    return "default"


def _unique_items(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _title_tokens(title: str) -> list[str]:
    words = re.findall(r"[\w+#-]+", title or "", flags=re.UNICODE)
    result = []
    for word in words:
        normalized = word.lower()
        if len(normalized) < 3 or normalized in GENERIC_ROLE_WORDS:
            continue
        result.append(word)
    return result


def _vacancy_keywords(vacancy: dict[str, Any], details: dict[str, Any] | None, limit: int = 4) -> list[str]:
    matched = json_loads((details or {}).get("matched_keywords_json"), [])
    key_skills = json_loads(vacancy.get("key_skills_json"), [])
    items: list[str] = []

    for kw in matched:
        keyword = str(kw.get("keyword", "")).strip()
        if keyword:
            items.append(keyword)
    for skill in key_skills:
        if isinstance(skill, str):
            items.append(skill)
    items.extend(_title_tokens(vacancy.get("name", "")))

    result = []
    for item in _unique_items(items):
        normalized = item.lower()
        if normalized in GENERIC_ROLE_WORDS:
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _needs_ai_case(vacancy: dict[str, Any], details: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    trigger_keywords = (
        candidate.get("candidate", {})
        .get("real_ai_case", {})
        .get("trigger_keywords", [])
    )
    text_parts = [
        vacancy.get("name", ""),
        vacancy.get("description_text", ""),
        vacancy.get("snippet_requirement", ""),
        vacancy.get("snippet_responsibility", ""),
    ]
    matched = json_loads((details or {}).get("matched_keywords_json"), [])
    text_parts.extend(str(kw.get("keyword", "")) for kw in matched)
    haystack = " ".join(str(part or "").lower() for part in text_parts)
    return any(str(token).lower() in haystack for token in trigger_keywords)


def _role_evidence_line(role_family: str, lang: str, keywords: list[str]) -> str:
    if lang == "ru":
        if role_family == "ai":
            return (
                "У меня практический опыт в Python, webhook-сценариях, "
                "LLM/RAG интеграциях и автоматизации процессов через n8n/Make."
            )
        if role_family == "bitrix":
            return (
                "Мой релевантный опыт — внедрение и развитие Bitrix24, CRM-процессов, "
                "интеграций с 1С и REST API."
            )
        return (
            "Мой фокус — системный анализ, интеграции и автоматизация процессов, "
            "где важны прозрачные требования и рабочие связки между системами."
        )
    if role_family == "ai":
        return (
            "My hands-on background includes Python, webhook workflows, "
            "LLM/RAG integrations, and process automation with n8n/Make."
        )
    if role_family == "bitrix":
        return (
            "My relevant background is in Bitrix24 delivery, CRM process design, "
            "1C integrations, and REST API implementations."
        )
    return (
        "My core background is in systems analysis, integrations, and process automation, "
        "with an emphasis on clear requirements and reliable delivery."
    )


def _role_value_line(role_family: str, lang: str, keywords: list[str]) -> str:
    kw_text = ", ".join(keywords[:3]) if keywords else ""
    if lang == "ru":
        if kw_text:
            return f"Судя по описанию роли, особенно релевантны задачи вокруг {kw_text}."
        if role_family == "bitrix":
            return "По описанию роли вижу прямое пересечение с CRM и интеграционными задачами."
        return "По описанию роли вижу прямое пересечение с задачами, где нужен быстрый выход в полезный результат."
    if kw_text:
        return f"The role description maps well to work around {kw_text}."
    if role_family == "bitrix":
        return "The role description aligns directly with CRM and integration work."
    return "The role description aligns with work where fast, practical delivery matters."


def _closing_line(lang: str, availability: str, location: str) -> str:
    extra = _normalize_text(", ".join(part for part in [availability, location] if part))
    if lang == "ru":
        return (
            "Если мой опыт релевантен вашей задаче, готов обсудить детали."
            + (f" Формат работы: {extra}." if extra else "")
        )
    return (
        "If this background matches your needs, I am ready to discuss the role."
        + (f" Work format: {extra}." if extra else "")
    )


def build_cover_letter(
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    *,
    lang: str,
    style: str,
    template: str,
    candidate_name: str,
    candidate_summary: str,
    location: str = "",
    availability: str = "",
    github: str = "",
    linkedin: str = "",
) -> dict[str, Any]:
    candidate = _load_candidate()
    company = vacancy.get("employer_name", "").strip() or "the company"
    title = vacancy.get("name", "").strip() or "the role"
    role_family = _pick_role_family(vacancy, details)
    keywords = _vacancy_keywords(vacancy, details)
    ai_case_required = _needs_ai_case(vacancy, details, candidate)
    ai_case = (
        candidate.get("candidate", {}).get("real_ai_case", {}).get(lang, "")
        if ai_case_required
        else ""
    )

    if lang == "ru":
        opener = f"Здравствуйте, команда {company}."
        target_line = f"Откликаюсь на позицию {title}."
    else:
        opener = f"Hello, {company} team."
        target_line = f"I am applying for the {title} role."

    links_line = " | ".join(
        part for part in [f"GitHub: {github}" if github else "", f"LinkedIn: {linkedin}" if linkedin else ""] if part
    )

    values = _SafeFormatDict(
        candidate_name=candidate_name,
        vacancy_title=title,
        company=company,
        top_keywords=", ".join(keywords) or "-",
        candidate_summary=_normalize_text(candidate_summary),
        github=github,
        linkedin=linkedin,
        availability=availability,
        location=location,
        decision=(details or {}).get("decision", ""),
        total_score=str((details or {}).get("total_score", vacancy.get("total_score", 0))),
        risks_summary=", ".join(str(r) for r in json_loads(vacancy.get("risk_flags_json"), [])[:3]) or "none",
        fit_reasons=", ".join(keywords) or "-",
        salary=str(vacancy.get("salary_from") or vacancy.get("salary_to") or ""),
        opener=opener,
        target_line=target_line,
        role_focus=_role_value_line(role_family, lang, keywords),
        evidence_line=_role_evidence_line(role_family, lang, keywords),
        ai_case_block=ai_case,
        closing_line=_closing_line(lang, availability, location),
        links_line=links_line,
    )

    text = _cleanup_letter(template.format_map(values))
    validation = validate_cover_letter(
        text,
        vacancy,
        details,
        lang=lang,
        style=style,
        role_family=role_family,
        candidate=candidate,
        vacancy_keywords=keywords,
        ai_case_required=ai_case_required,
    )
    return {
        "text": text,
        "validation": validation,
        "meta": {
            "role_family": role_family,
            "vacancy_keywords": keywords,
            "ai_case_required": ai_case_required,
        },
    }


def validate_cover_letter(
    text: str,
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    *,
    lang: str,
    style: str,
    role_family: str,
    candidate: dict[str, Any] | None = None,
    vacancy_keywords: list[str] | None = None,
    ai_case_required: bool = False,
) -> dict[str, Any]:
    candidate = candidate or _load_candidate()
    candidate_cfg = candidate.get("candidate", {})
    banned_terms = [
        str(item).strip()
        for item in candidate_cfg.get("constraints", {}).get("do_not_write_in_cover_letter", [])
        if str(item).strip()
    ]
    vacancy_keywords = vacancy_keywords or _vacancy_keywords(vacancy, details)
    role_signals = EVIDENCE_ANCHORS.get(role_family, EVIDENCE_ANCHORS["default"])
    summary_text = " ".join(
        str(v).lower()
        for v in [
            candidate_cfg.get("profiles", {}).get("default", {}).get("summary_ru", ""),
            candidate_cfg.get("profiles", {}).get("default", {}).get("summary_en", ""),
        ]
    )
    candidate_signals = {
        token for token in role_signals if token in summary_text or token in text.lower()
    }
    lines = [line for line in text.splitlines() if line.strip()]
    word_count = _word_count(text)
    low, high = STYLE_WORD_LIMITS.get(style, STYLE_WORD_LIMITS["medium"])
    company = vacancy.get("employer_name", "").strip()
    title = vacancy.get("name", "").strip()
    lower_text = text.lower()

    anchor_hits = [
        kw for kw in vacancy_keywords if kw and _normalize_token(kw) in _normalize_token(lower_text)
    ]
    duplicate_sentences: list[str] = []
    seen_sentences: set[str] = set()
    for sentence in _split_sentences(text):
        normalized = _normalize_token(sentence)
        if not normalized:
            continue
        if normalized in seen_sentences:
            duplicate_sentences.append(sentence)
        seen_sentences.add(normalized)

    reasons: list[str] = []
    if word_count < low:
        reasons.append(f"too_short:{word_count}<{low}")
    if word_count > high:
        reasons.append(f"too_long:{word_count}>{high}")
    if company and company.lower() not in lower_text:
        reasons.append("missing_company_name")
    if title and title.lower() not in lower_text:
        reasons.append("missing_vacancy_title")
    if len(anchor_hits) < min(2, len(vacancy_keywords) or 2):
        reasons.append("not_specific_enough")
    if not candidate_signals:
        reasons.append("missing_candidate_evidence")
    if any(term.lower() in lower_text for term in banned_terms):
        reasons.append("contains_banned_candidate_term")
    if any(phrase in lower_text for phrase in GENERIC_PHRASES.get(lang, [])):
        reasons.append("contains_generic_phrase")
    if re.search(r"(^|\n)\s*[-*]\s+", text) or "**" in text or "`" in text or re.search(r"(^|\n)#", text):
        reasons.append("contains_markdown_artifacts")
    if duplicate_sentences:
        reasons.append("repeated_sentences")
    if len(lines) < 3:
        reasons.append("too_few_paragraphs")
    if text.count("!") > 1:
        reasons.append("too_many_exclamation_marks")

    ai_case_present = "ai lead intake" in lower_text
    if ai_case_required and style != "short" and not ai_case_present:
        reasons.append("missing_required_ai_case")
    if not ai_case_required and ai_case_present:
        reasons.append("unexpected_ai_case")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "metrics": {
            "word_count": word_count,
            "paragraph_count": len(lines),
            "anchor_hits": anchor_hits,
            "candidate_signals": sorted(candidate_signals),
            "ai_case_required": ai_case_required,
            "ai_case_present": ai_case_present,
        },
    }
