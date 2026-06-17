"""LLM prompt framework — generates prompt files for manual copy/paste.

No API integration. No auto-send. Privacy-first by default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .storage import Storage
from .utils import json_loads, truncate

LLM_CONFIG_PATH = "config/llm.yaml"
PROMPTS_DIR = Path("exports/llm_prompts")


def load_llm_config() -> dict[str, Any]:
    """Load LLM configuration. Returns safe defaults if missing."""
    try:
        cfg = yaml.safe_load(Path(LLM_CONFIG_PATH).read_text(encoding="utf-8"))
        return (cfg or {}).get("llm", {})
    except (OSError, yaml.YAMLError):
        return {}


def _privacy_header(config: dict[str, Any]) -> str:
    return (
        "<!-- PRIVACY NOTICE: This prompt file is for manual use only.\n"
        "No data is sent automatically. No API keys, tokens, or .env values are included.\n"
        "Copy and paste into your preferred LLM (ChatGPT, Claude, etc.) manually. -->\n\n"
    )


def _truncate_desc(text: str, config: dict[str, Any]) -> str:
    if not config.get("include_description", True):
        return "[Description omitted per privacy config]"
    limit = config.get("max_description_chars", 3000)
    return truncate(text, limit)


# ═══════════════════════════════════════════════════════════════════════════
# Apply-pack prompt
# ═══════════════════════════════════════════════════════════════════════════


def generate_apply_pack_prompt(vacancy_id: str) -> str:
    """Generate a prompt for improving a cover letter."""
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    config = load_llm_config()
    include_desc = config.get("include_description", True)

    row = storage.get_vacancy_full(vacancy_id)
    if not row:
        return f"Vacancy '{vacancy_id}' not found.\n"

    details = storage.get_score_details(vacancy_id) or {}

    # Candidate data (name only, no full profile — privacy)
    try:
        candidate_cfg = yaml.safe_load(Path("config/candidate.yaml").read_text(encoding="utf-8"))
        cand = candidate_cfg.get("candidate", {})
        cand_name = cand.get("name_en", cand.get("name_ru", "Candidate"))
        cand_summary = cand.get("profiles", {}).get("default", {}).get("summary_en", "")
    except Exception:
        cand_name = "Candidate"
        cand_summary = ""

    matched = json_loads(details.get("matched_keywords_json"), [])
    excluded = json_loads(details.get("excluded_keywords_json"), [])
    risks = json_loads(row.get("risk_flags_json"), [])
    work = json_loads(row.get("work_format_flags_json"), [])

    desc = (
        _truncate_desc(row.get("description_text") or "", config) if include_desc else "[omitted]"
    )
    salary = f"{row.get('salary_from') or '?'}–{row.get('salary_to') or '?'} {row.get('salary_currency') or ''}".strip()

    # Key strengths from matched keywords
    strengths = ", ".join(kw.get("keyword", "") for kw in matched[:8] if kw.get("weight", 0) > 0)

    # Format matched keywords for prompt
    matched_str = "\n".join(
        f"- {kw.get('keyword', '')} ({kw.get('field', '')}, +{kw.get('weight', 0)})"
        for kw in matched[:10]
    )

    prompt = _privacy_header(config)
    prompt += (
        f"# Cover Letter Improvement Request\n\n"
        f"**Vacancy:** {row.get('name', '?')}\n"
        f"**Company:** {row.get('employer_name', '?')}\n"
        f"**Location:** {row.get('area_name', '?')}\n"
        f"**Schedule:** {row.get('schedule_name', '?')}\n"
        f"**Salary:** {salary}\n"
        f"**Score:** {row.get('total_score', 0)}/100 | Confidence: {details.get('confidence_score', 0)}% | Noise: {details.get('noise_score', 0)}%\n"
        f"**Decision:** {details.get('decision', '?')}\n\n"
        f"## Key Strengths (Matched Keywords)\n"
        f"{matched_str}\n\n"
        f"## Risks & Concerns\n"
        f"Risks: {', '.join(str(r) for r in risks) if risks else 'none'}\n"
        f"Work format: {', '.join(work) if work else 'unknown'}\n"
        f"Excluded: {', '.join(kw.get('keyword', '') for kw in excluded[:5]) if excluded else 'none'}\n\n"
        f"## Vacancy Description\n"
        f"{desc}\n\n"
        f"## Your Task\n"
        f"You are {cand_name}. {cand_summary}\n\n"
        f"Write a professional, tailored cover letter for this vacancy. "
        f"Emphasize the key strengths above. Address or mitigate the risks.\n\n"
        f"**IMPORTANT:** This is a draft. Do NOT send anything automatically. "
        f"The user will review and send manually.\n\n"
        f"Key skills to highlight: {strengths}\n"
    )

    return prompt


# ═══════════════════════════════════════════════════════════════════════════
# Score review prompt
# ═══════════════════════════════════════════════════════════════════════════


def generate_score_review_prompt(vacancy_id: str) -> str:
    """Generate a prompt asking LLM to critique the current score."""
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    config = load_llm_config()
    include_desc = config.get("include_description", True)

    row = storage.get_vacancy_full(vacancy_id)
    if not row:
        return f"Vacancy '{vacancy_id}' not found.\n"

    details = storage.get_score_details(vacancy_id) or {}

    matched = json_loads(details.get("matched_keywords_json"), [])
    excluded = json_loads(details.get("excluded_keywords_json"), [])
    cat_scores = json_loads(details.get("category_scores_json"), {})
    quality = json_loads(details.get("quality_flags_json"), [])
    explanation = json_loads(details.get("explanation_json"), {})

    desc = (
        _truncate_desc(row.get("description_text") or "", config) if include_desc else "[omitted]"
    )

    prompt = _privacy_header(config)
    prompt += (
        f"# Score Review Request\n\n"
        f"**Vacancy:** {row.get('name', '?')}\n"
        f"**Company:** {row.get('employer_name', '?')}\n"
        f"**Score:** {row.get('total_score', 0)}/100\n"
        f"**Confidence:** {details.get('confidence_score', 0)}%\n"
        f"**Noise:** {details.get('noise_score', 0)}%\n"
        f"**Decision:** {details.get('decision', '?')}\n"
        f"**Quality flags:** {', '.join(quality) if quality else 'none'}\n\n"
        f"## Category Scores\n"
        + "".join(f"- {k}: {v}\n" for k, v in sorted(cat_scores.items()))
        + "\n## Matched Keywords\n"
        + "".join(
            f"- {kw.get('keyword', '')} ({kw.get('field', '')}, +{kw.get('weight', 0)})\n"
            for kw in matched[:15]
        )
        + "\n## Excluded Keywords\n"
        + "".join(
            f"- {kw.get('keyword', '')} ({kw.get('field', '')}, {kw.get('weight', 0)})\n"
            for kw in excluded[:10]
        )
        + f"\n## Scoring Formula\n{explanation.get('total_formula', 'n/a')}\n"
        f"Confidence: {explanation.get('confidence_breakdown', 'n/a')}\n"
        f"Noise: {explanation.get('noise_breakdown', 'n/a')}\n\n"
        f"## Vacancy Description\n{desc}\n\n"
        f"## Your Task\n"
        f"Review this vacancy's score and decision. Is it reasonable? "
        f"Are there keywords that should be added/removed? "
        f"Is the confidence/noise assessment fair? "
        f"Suggest specific improvements to the preset scoring rules.\n"
    )

    return prompt


# ═══════════════════════════════════════════════════════════════════════════
# Preset improve prompt
# ═══════════════════════════════════════════════════════════════════════════


def generate_preset_improve_prompt(preset_name: str) -> str:
    """Generate a prompt asking LLM to suggest preset YAML improvements."""
    from .search_presets import get_preset

    config = load_llm_config()

    preset = get_preset(preset_name)
    if preset is None:
        return f"Preset '{preset_name}' not found.\n"

    preset_yaml = yaml.safe_dump(
        {k: v for k, v in preset.items() if not k.startswith("_")},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    # Get calibration suggestions for this preset
    try:
        from .commands.calibrate import _load_suggestions

        suggestions = _load_suggestions()
        relevant = [s for s in suggestions if s.get("preset") == preset_name][:5]
        sug_text = "\n".join(
            f"- [{s.get('type')}] {s.get('keyword', '')}: {s.get('reason', '')}" for s in relevant
        )
    except Exception:
        sug_text = "No calibration suggestions available."

    # Get example vacancies (good and bad)
    load_dotenv()
    storage = Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
    with storage.connect() as conn:
        good = conn.execute(
            """SELECT v.name, v.employer_name, sd.total_score, sd.decision
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id=v.id
               WHERE v.source_profile=? AND sd.total_score>=80
               ORDER BY sd.total_score DESC LIMIT 5""",
            (preset_name,),
        ).fetchall()
        bad = conn.execute(
            """SELECT v.name, v.employer_name, sd.total_score, sd.decision
               FROM vacancies v
               JOIN score_details sd ON sd.vacancy_id=v.id
               WHERE v.source_profile=? AND sd.total_score<50
               ORDER BY sd.total_score ASC LIMIT 5""",
            (preset_name,),
        ).fetchall()

    good_examples = (
        "\n".join(
            f"- [{r['decision']}, score={r['total_score']}] {r['name']} @ {r['employer_name']}"
            for r in good
        )
        or "none"
    )
    bad_examples = (
        "\n".join(
            f"- [{r['decision']}, score={r['total_score']}] {r['name']} @ {r['employer_name']}"
            for r in bad
        )
        or "none"
    )

    prompt = _privacy_header(config)
    prompt += (
        f"# Preset Improvement Request: {preset_name}\n\n"
        f"## Current Preset YAML\n```yaml\n{preset_yaml}```\n\n"
        f"## Calibration Suggestions\n{sug_text}\n\n"
        f"## Top-Scoring Vacancies (should match)\n{good_examples}\n\n"
        f"## Low-Scoring Vacancies (should NOT match)\n{bad_examples}\n\n"
        f"## Your Task\n"
        f"Suggest improvements to the search preset YAML above. "
        f"Consider:\n"
        f"- Adding missing keywords to include.any or boost\n"
        f"- Adding noise terms to exclude.any or penalties\n"
        f"- Adjusting decision thresholds if needed\n"
        f"- Adding include.all for required combinations\n\n"
        f"**OUTPUT ONLY THE IMPROVED YAML** — no explanations, no markdown outside the code block.\n"
    )

    return prompt


# ═══════════════════════════════════════════════════════════════════════════
# Privacy guard — field preview
# ═══════════════════════════════════════════════════════════════════════════


def preview_fields(config: dict[str, Any]) -> list[str]:
    """Return list of field names that will be included in prompts."""
    fields = [
        "Vacancy name",
        "Company name",
        "Area/location",
        "Schedule",
        "Salary range",
        "Score & decision",
        "Matched keywords",
        "Excluded keywords",
        "Risk flags",
        "Confidence & noise",
    ]
    if config.get("include_description", True):
        fields.append(
            f"Description (truncated to {config.get('max_description_chars', 3000)} chars)"
        )
    else:
        fields.append("Description (EXCLUDED per privacy config)")
    fields.append("Candidate name (from candidate.yaml)")
    return fields
