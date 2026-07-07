from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from ..config import _services
from ..utils import json_loads

console = Console()

TEMPLATES_PATH = "config/apply_templates.yaml"


# ── Template loading ───────────────────────────────────────────────────────


def _load_templates() -> dict[str, Any]:
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _resolve_template(preset_name: str | None, lang: str, style: str) -> str:
    """
    Resolve the best template for (preset, lang, style).
    Fallback order: preset.lang.style → default.lang.style → default.ru.medium → builtin.
    """
    data = _load_templates()
    tmpls = data.get("templates", {})

    # Try exact match
    if preset_name and preset_name in tmpls:
        preset_tmpl = tmpls[preset_name]
        if lang in preset_tmpl and style in preset_tmpl[lang]:
            return preset_tmpl[lang][style]

    # Try default
    default = tmpls.get("default", {})
    if lang in default and style in default[lang]:
        return default[lang][style]
    if "ru" in default and "medium" in default["ru"]:
        return default["ru"]["medium"]

    # Hardcoded fallback
    if lang == "ru":
        return "Здравствуйте!\n\n{candidate_name}. {candidate_summary}\n\nС уважением,\n{candidate_name}"
    return "Hello!\n\n{candidate_name}. {candidate_summary}\n\nBest regards,\n{candidate_name}"


# ── Candidate data ─────────────────────────────────────────────────────────


def _load_candidate() -> dict[str, Any]:
    try:
        with open("config/candidate.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _pick_profile(preset_name: str | None) -> str:
    if not preset_name:
        return "default"
    name = preset_name.lower()
    if name.startswith("ai") or any(token in name for token in ("automation", "n8n", "make")):
        return "ai"
    if any(token in name for token in ("bitrix", "crm", "integration", "1c", "one_c", "erp")):
        return "bitrix"
    return "default"


def _load_candidate_text(lang: str, key: str, preset_name: str | None) -> str:
    cand = _load_candidate().get("candidate", {})
    profile = _pick_profile(preset_name)
    profiles = cand.get("profiles", {})
    profile_data = profiles.get(profile, profiles.get("default", {}))
    summary = profile_data.get(f"summary_{lang}", profile_data.get("summary_ru", ""))
    name = cand.get(f"name_{lang}", cand.get("name_ru", "Candidate"))
    if key == "name":
        return name
    if key == "location":
        return cand.get("location", "")
    if key == "availability":
        return cand.get("availability", "")
    if key == "github":
        return cand.get("links", {}).get("github", "")
    if key == "linkedin":
        return cand.get("links", {}).get("linkedin", "")
    if key == "summary":
        return summary
    return ""


# ── Fit summary ─────────────────────────────────────────────────────────────


def _build_fit_summary(details: dict | None, vacancy: dict, lang: str) -> dict[str, str]:
    """Build a structured fit summary from score_details."""
    total = details.get("total_score", 0) if details else 0
    decision = details.get("decision", "") if details else ""
    matched = json_loads(details.get("matched_keywords_json"), []) if details else []
    risks = (
        json_loads(details.get("risk_flags_json"), [])
        if details
        else json_loads(vacancy.get("risk_flags_json"), [])
    )
    work = (
        json_loads(details.get("work_format_flags_json"), [])
        if details
        else json_loads(vacancy.get("work_format_flags_json"), [])
    )
    salary_from = vacancy.get("salary_from")
    salary_to = vacancy.get("salary_to")

    is_ru = lang == "ru"

    # Fit reasons
    reasons = []
    for kw in matched[:5]:
        k = kw.get("keyword", "")
        f = kw.get("field", "")
        if k:
            label = {
                "title": "title",
                "skills": "skills",
                "snippet": "snippet",
                "description": "desc",
            }.get(f, f)
            reasons.append(f"**{k}** ({label})")

    # Concerns
    concerns = []
    if not salary_from and not salary_to:
        concerns.append("Зарплата не указана" if is_ru else "Salary not specified")
    if risks:
        for r in risks[:3]:
            concerns.append(str(r))
    if "remote" not in work and vacancy.get("schedule_name", "").lower() not in (
        "remote",
        "удаленная работа",
    ):
        concerns.append("Не указан remote формат" if is_ru else "Remote format not confirmed")

    # Strategy
    if decision == "strong_match" and total >= 85:
        strategy = (
            "Уверенный отклик, акцент на релевантный опыт"
            if is_ru
            else "Confident application, highlight relevant experience"
        )
    elif total >= 70:
        strategy = (
            "Отклик с акцентом на transferable skills"
            if is_ru
            else "Apply emphasizing transferable skills"
        )
    else:
        strategy = (
            "Оценить fit перед откликом, возможны gaps"
            if is_ru
            else "Assess fit before applying, possible gaps"
        )

    return {
        "reasons": "\n".join(f"- {r}" for r in reasons) if reasons else ("-" if is_ru else "-"),
        "concerns": "\n".join(f"- {c}" for c in concerns) if concerns else ("-" if is_ru else "-"),
        "strategy": strategy,
        "decision": decision,
        "total_score": str(total),
    }


# ── Generate sections ──────────────────────────────────────────────────────


def _generate_md(
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    lang: str,
    style: str = "medium",
    template_name: str | None = None,
) -> str:
    name = vacancy.get("name", "?")
    company = vacancy.get("employer_name", "?")
    area = vacancy.get("area_name", "?")
    url = vacancy.get("alternate_url", "")
    vid = vacancy.get("id", "")
    preset = vacancy.get("best_profile") or (details.get("preset_name") if details else "")

    total_score = (
        details.get("total_score", vacancy.get("total_score", 0))
        if details
        else vacancy.get("total_score", 0)
    )
    decision = (details.get("decision") if details else "") or ""
    matched = json_loads(details.get("matched_keywords_json"), []) if details else []
    excluded = json_loads(details.get("excluded_keywords_json"), []) if details else []
    risks = (
        json_loads(details.get("risk_flags_json"), [])
        if details
        else json_loads(vacancy.get("risk_flags_json"), [])
    )

    salary = _fmt_salary(vacancy, lang)
    schedule = vacancy.get("schedule_name") or ""
    experience = vacancy.get("experience_name") or ""
    published = (vacancy.get("published_at") or "")[:10]

    # Candidate data
    candidate_name = _load_candidate_text(lang, "name", preset)
    summary = _load_candidate_text(lang, "summary", preset)
    location = _load_candidate_text(lang, "location", preset)
    gh = _load_candidate_text(lang, "github", preset)
    li = _load_candidate_text(lang, "linkedin", preset)
    availability = _load_candidate_text(lang, "availability", preset)

    # Fit summary
    fit = _build_fit_summary(details, vacancy, lang)

    # Keywords
    top_kw = ", ".join(kw.get("keyword", "") for kw in matched[:5] if kw.get("keyword")) or "-"

    # Resolve cover letter template
    tmpl = _resolve_template(template_name or preset, lang, style)
    cover_letter = tmpl.format(
        candidate_name=candidate_name,
        vacancy_title=name,
        company=company,
        top_keywords=top_kw,
        candidate_summary=summary,
        github=gh or "",
        linkedin=li or "",
        availability=availability,
        location=location,
        decision=decision,
        total_score=str(total_score),
        risks_summary=", ".join(str(r) for r in risks[:3]) if risks else "none",
        fit_reasons=fit["reasons"],
        salary=salary,
    )

    is_ru = lang == "ru"

    return f"""# Apply Pack: {name}

## Vacancy
- **Company:** {company}
- **Title:** {name}
- **Area:** {area}
- **Salary:** {salary}
- **Schedule:** {schedule}
- **Experience:** {experience}
- **Published:** {published}
- **URL:** {url}

## Score
- **Total:** {total_score}
- **Decision:** {decision or "N/A"}
- **Preset:** {preset or "N/A"}
- **Matched:** {", ".join(f"{kw.get('keyword', '')}({kw.get('field', '')})" for kw in matched[:8])}
- **Risks:** {", ".join(str(r) for r in risks[:5]) if risks else "none"}

## 🔍 Fit Analysis
- **Verdict:** {decision or "N/A"} (score {total_score})
- **Why it fits:**
{fit["reasons"]}

- **Potential concerns:**
{fit["concerns"]}

- **Strategy:** {fit["strategy"]}

## 🤔 Questions to Ask Recruiter
- {"Как организован процесс онбординга?" if is_ru else "What does the onboarding process look like?"}
- {"Какие ключевые метрики на первые 3 месяца?" if is_ru else "What are the key success metrics for the first 3 months?"}
- {"Какой стек / инструменты используются в команде?" if is_ru else "What stack / tools does the team use?"}
- {"Как выглядит типичный рабочий день?" if is_ru else "What does a typical workday look like?"}

## 📋 Contract / Remote Checks
- {"Проверить remote формат (schedule: " + schedule + ")" if is_ru else "Verify remote format (schedule: " + schedule + ")"}
- {"Проверить страну / часовой пояс" if is_ru else "Verify country / timezone restrictions"}
- {"Проверить детали зарплаты: " + salary if is_ru else "Verify salary details: " + salary}
- {"Проверить тип занятости: " + (vacancy.get("employment_name") or "-") if is_ru else "Verify employment type: " + (vacancy.get("employment_name") or "-")}
- {"Уточнить формат контракта / ИП / самозанятость" if is_ru else "Clarify contract format / self-employment options"}

## ⚠️ Risk Check
{_risk_bullets(excluded, risks, vacancy, lang)}

## ✅ Application Checklist
- Open HH URL: {url}
- Check remote availability
- Check country/timezone restrictions
- Check salary/contract details
- Check whether cover letter is needed
- Send manually via HH
- Then run: `python -m src.main review apply {vid} --date today`

## 📝 Cover Letter Draft ({style})

{cover_letter}
"""


def _risk_bullets(excluded: list[dict], risks: list[str], vacancy: dict, lang: str) -> str:
    lines = []
    for kw in excluded[:5]:
        lines.append(f"- ⚠️ Excluded: **{kw.get('keyword', '')}** ({kw.get('field', '')})")
    for r in risks[:3]:
        lines.append(f"- ⚠️ Risk: {r}")
    salary = vacancy.get("salary_from") or vacancy.get("salary_to")
    if not salary:
        lines.append("- ⚠️ Зарплата не указана" if lang == "ru" else "- ⚠️ Salary not specified")
    if not lines:
        lines.append(
            "- Явных рисков не обнаружено" if lang == "ru" else "- No obvious risks detected"
        )
    return "\n".join(lines)


def _fmt_salary(vacancy: dict, lang: str = "ru") -> str:
    sfrom = vacancy.get("salary_from")
    sto = vacancy.get("salary_to")
    curr = vacancy.get("salary_currency") or ""
    if not sfrom and not sto:
        return "Не указана" if lang == "ru" else "Not specified"
    parts = []
    if sfrom:
        parts.append(str(sfrom))
    if sto:
        parts.append(str(sto))
    return "–".join(parts) + (f" {curr}" if curr else "")


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")[:60]


# ── HTML ────────────────────────────────────────────────────────────────────


def _generate_html(md_content: str, title: str) -> str:
    html_content = md_content
    html_content = re.sub(r"^### (.+)", r"<h3>\1</h3>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"^## (.+)", r"<h2>\1</h2>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"^# (.+)", r"<h1>\1</h1>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
    html_content = re.sub(r"`([^`]+)`", r"<code>\1</code>", html_content)
    html_content = re.sub(r"^- (.+)", r"<li>\1</li>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"(\[([^\]]+)\]\(([^)]+)\))", r'<a href="\3">\2</a>', html_content)
    html_content = html_content.replace("\n\n", "</p><p>")
    html_content = f"<p>{html_content}</p>"
    html_content = html_content.replace("<p><li>", "<ul><li>").replace("</li></p>", "</li></ul>")
    html_content = html_content.replace("<p><h", "<h").replace("</h", "</h")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{background:#0b1020;color:#e8edf7;font:15px system-ui,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;line-height:1.7}}
h1{{font-size:26px;color:#67e8f9}} h2{{font-size:20px;color:#9bf6e8;margin-top:30px}} h3{{font-size:17px;color:#bfdbfe}}
strong{{color:#fde68a}} code{{background:#141b2d;padding:2px 6px;border-radius:4px;color:#fda4af}}
ul{{padding-left:20px}} li{{margin:4px 0}} a{{color:#67e8f9}}
</style></head><body>
{html_content}
</body></html>"""


# ── File I/O ────────────────────────────────────────────────────────────────


def _write_pack(
    vacancy: dict,
    details: dict | None,
    lang: str,
    fmt: str,
    out_dir: Path,
    style: str,
    template_name: str | None,
) -> Path:
    name = vacancy.get("name", "vacancy")
    vid = vacancy.get("id", "")
    slug = _slug(name)
    md_content = _generate_md(vacancy, details, lang, style, template_name)

    paths = []
    if fmt in ("md", "both"):
        md_path = out_dir / f"{vid}_{slug}.md"
        md_path.write_text(md_content, encoding="utf-8")
        paths.append(md_path)
    if fmt in ("html", "both"):
        html_content = _generate_html(md_content, name)
        html_path = out_dir / f"{vid}_{slug}.html"
        html_path.write_text(html_content, encoding="utf-8")
        paths.append(html_path)
    return paths[0] if paths else out_dir


def _save_review(storage, vacancy_id: str, md_content: str, overwrite: bool) -> bool:
    review = storage.get_review(vacancy_id)
    existing = review.get("cover_letter_draft")
    if existing and not overwrite:
        return False
    storage.upsert_review(vacancy_id, cover_letter_draft=md_content)
    return True


# ── Main command ────────────────────────────────────────────────────────────


def command_apply_pack(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    lang = args.lang or "ru"
    fmt = args.format or "both"
    style = getattr(args, "style", None) or "medium"
    template_name = getattr(args, "template", None)
    out_dir = Path("exports/apply_packs")
    out_dir.mkdir(parents=True, exist_ok=True)

    vacancies: list[dict[str, Any]] = []

    if args.vacancy_id:
        row = storage.get_vacancy_full(args.vacancy_id)
        if not row:
            console.print(f"[red]Vacancy '{args.vacancy_id}' not found.[/red]")
            return 1
        vacancies = [row]
    elif args.top or args.limit:
        limit = args.top or args.limit or 10
        decisions = [args.decision] if args.decision else None
        rows = storage.list_queue(
            min_score=args.min_score or 0,
            decisions=decisions,
            preset=args.preset,
            limit=limit,
        )
        for row in rows:
            details = storage.get_score_details(row["id"])
            row["best_profile"] = row.get("best_profile", "")
            vacancies.append(row)
    else:
        console.print("[red]Specify --vacancy-id or --top/--limit.[/red]")
        return 1

    if not vacancies:
        console.print("[yellow]No vacancies found.[/yellow]")
        return 0

    saved_drafts = 0
    for vacancy in vacancies:
        vid = vacancy["id"]
        details = storage.get_score_details(vid)
        paths = _write_pack(vacancy, details, lang, fmt, out_dir, style, template_name)
        console.print(f"[green]{vid}: {paths.name} ({style})[/green]")

        if args.save_review:
            md_content = _generate_md(vacancy, details, lang, style, template_name)
            if _save_review(storage, vid, md_content, args.overwrite):
                saved_drafts += 1
            elif not args.overwrite:
                console.print(f"[dim]{vid}: draft already exists, use --overwrite[/dim]")

    if saved_drafts:
        console.print(f"[green]Saved {saved_drafts} cover letter drafts to review.[/green]")

    # Generate index if multiple
    if len(vacancies) > 1:
        index_lines = [
            "<!doctype html><html><head><meta charset=utf-8><title>Apply Packs</title>",
            "<style>body{background:#0b1020;color:#e8edf7;font:15px system-ui;max-width:800px;margin:40px auto;padding:20px}",
            "h1{color:#67e8f9} a{color:#bfdbfe} li{margin:8px 0}</style></head><body>",
            f"<h1>Apply Packs ({len(vacancies)})</h1><ul>",
        ]
        for v in vacancies:
            slug = _slug(v.get("name", ""))
            index_lines.append(
                f'<li><a href="{v["id"]}_{slug}.html">{v.get("name", "?")}</a> — '
                f"{v.get('employer_name', '?')} — score {v.get('total_score', 0)}</li>"
            )
        index_lines.append("</ul></body></html>")
        (out_dir / "index.html").write_text("\n".join(index_lines), encoding="utf-8")
        console.print(f"[green]Index: {out_dir / 'index.html'}[/green]")

    return 0
