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


def _load_candidate() -> dict[str, Any]:
    try:
        with open("config/candidate.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _pick_profile(preset_name: str | None) -> str:
    if preset_name and preset_name.startswith("ai"):
        return "ai"
    if preset_name and preset_name.startswith("bitrix"):
        return "bitrix"
    return "default"


def _slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")[:60]


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


def _generate_md(
    vacancy: dict[str, Any],
    details: dict[str, Any] | None,
    lang: str,
) -> str:
    name = vacancy.get("name", "?")
    company = vacancy.get("employer_name", "?")
    area = vacancy.get("area_name", "?")
    url = vacancy.get("alternate_url", "")
    vid = vacancy.get("id", "")
    preset = vacancy.get("best_profile") or (
        details.get("preset_name") if details else ""
    )

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
    desc = vacancy.get("description_text") or ""

    candidate_name = _load_candidate_text(lang, "name", preset)
    summary = _load_candidate_text(lang, "summary", preset)
    location = _load_candidate_text(lang, "location", preset)
    gh = _load_candidate_text(lang, "github", preset)
    li = _load_candidate_text(lang, "linkedin", preset)

    # Build sections
    if lang == "ru":
        greeting = "Здравствуйте!"
        why_header = "## Почему подходит"
        risks_header = "## Риски / что проверить до отклика"
        checklist_header = "## Чеклист ручного отклика"
        cover_header = "## Черновик cover letter"
        closing = "С уважением,"
        lang_intro_text = "Меня зовут"
        lang_at_text = "в"
        lang_experience_text = "так как мой опыт связан с"
        top_areas = _top_matched_areas(matched, lang)
        fit_bullets = _fit_bullets(matched, desc, lang)
        risk_bullets = _risk_bullets(excluded, risks, vacancy, lang)
    else:
        greeting = "Hello!"
        why_header = "## Why it fits"
        risks_header = "## Risks / verify before applying"
        checklist_header = "## Manual application checklist"
        cover_header = "## Cover letter draft"
        closing = "Best regards,"
        lang_intro_text = "My name is"
        lang_at_text = "at"
        lang_experience_text = "as my experience aligns with"
        top_areas = _top_matched_areas(matched, lang)
        fit_bullets = _fit_bullets(matched, desc, lang)
        risk_bullets = _risk_bullets(excluded, risks, vacancy, lang)

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

{why_header}
{fit_bullets}

{risks_header}
{risk_bullets}

{checklist_header}
- Open HH URL: {url}
- Check remote availability
- Check country/timezone restrictions
- Check salary/contract details
- Check whether cover letter is needed
- Send manually via HH
- Then run: `python -m src.main review apply {vid} --date today`

{cover_header}

{greeting}

{candidate_name}. {lang_intro_text} **{name}** {lang_at_text} **{company}**, {lang_experience_text} {top_areas}.

{summary}

{closing}
{candidate_name}
{gh}
{li}
"""


def _top_matched_areas(matched: list[dict], lang: str) -> str:
    if lang == "ru":
        default = "релевантными технологиями"
    else:
        default = "relevant technologies"
    if not matched:
        return default
    areas = list(dict.fromkeys(kw.get("keyword", "") for kw in matched[:5]))
    return ", ".join(areas)


def _fit_bullets(matched: list[dict], desc: str, lang: str) -> str:
    lines = []
    seen = set()
    for kw in matched[:6]:
        k = kw.get("keyword", "")
        field = kw.get("field", "")
        if k not in seen:
            seen.add(k)
            snippet = _find_snippet(desc, k)
            lines.append(f"- **{k}** ({field})" + (f": _{snippet}_" if snippet else ""))
    if not lines:
        lines.append("- (no detailed match data — run score rescore for details)")
    return "\n".join(lines)


def _find_snippet(desc: str, keyword: str) -> str:
    if not desc or not keyword:
        return ""
    idx = desc.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - 30)
    end = min(len(desc), idx + len(keyword) + 50)
    return desc[start:end].strip()


def _risk_bullets(
    excluded: list[dict], risks: list[str], vacancy: dict, lang: str
) -> str:
    lines = []
    for kw in excluded[:5]:
        lines.append(
            f"- ⚠️ Excluded: **{kw.get('keyword', '')}** ({kw.get('field', '')})"
        )
    for r in risks[:3]:
        lines.append(f"- ⚠️ Risk: {r}")
    salary = vacancy.get("salary_from") or vacancy.get("salary_to")
    if not salary:
        if lang == "ru":
            lines.append("- ⚠️ Зарплата не указана")
        else:
            lines.append("- ⚠️ Salary not specified")
    if not lines:
        if lang == "ru":
            lines.append("- Явных рисков не обнаружено")
        else:
            lines.append("- No obvious risks detected")
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


def _generate_html(md_content: str, title: str) -> str:
    # Simple converter: headings, bold, lists, links, code
    html_content = md_content
    html_content = re.sub(
        r"^### (.+)", r"<h3>\1</h3>", html_content, flags=re.MULTILINE
    )
    html_content = re.sub(r"^## (.+)", r"<h2>\1</h2>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"^# (.+)", r"<h1>\1</h1>", html_content, flags=re.MULTILINE)
    html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
    html_content = re.sub(r"`([^`]+)`", r"<code>\1</code>", html_content)
    html_content = re.sub(r"^- (.+)", r"<li>\1</li>", html_content, flags=re.MULTILINE)
    html_content = re.sub(
        r"(\[([^\]]+)\]\(([^)]+)\))", r'<a href="\3">\2</a>', html_content
    )
    html_content = html_content.replace("\n\n", "</p><p>")
    html_content = f"<p>{html_content}</p>"
    html_content = html_content.replace("<p><li>", "<ul><li>").replace(
        "</li></p>", "</li></ul>"
    )
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


def _write_pack(
    vacancy: dict, details: dict | None, lang: str, fmt: str, out_dir: Path
) -> Path:
    name = vacancy.get("name", "vacancy")
    vid = vacancy.get("id", "")
    slug = _slug(name)
    md_content = _generate_md(vacancy, details, lang)

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


def command_apply_pack(args: argparse.Namespace) -> int:
    storage, _, _ = _services()
    lang = args.lang or "ru"
    fmt = args.format or "both"
    out_dir = Path("exports/apply_packs")
    out_dir.mkdir(parents=True, exist_ok=True)

    vacancies: list[dict[str, Any]] = []

    if args.vacancy_id:
        row = storage.get_vacancy(args.vacancy_id)
        if not row:
            console.print(f"[red]Vacancy '{args.vacancy_id}' not found.[/red]")
            return 1
        # Also get score details
        details = storage.get_score_details(args.vacancy_id)
        # Get scores for best_profile
        scores = storage.list_vacancies(limit=1)
        for s in scores:
            if s["id"] == args.vacancy_id:
                row["total_score"] = s.get("total_score", 0)
                row["best_profile"] = s.get("best_profile", "")
                break
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
        paths = _write_pack(vacancy, details, lang, fmt, out_dir)
        console.print(f"[green]{vid}: {paths.name}[/green]")

        if args.save_review:
            md_content = _generate_md(vacancy, details, lang)
            if _save_review(storage, vid, md_content, args.overwrite):
                saved_drafts += 1

    if saved_drafts:
        console.print(
            f"[green]Saved {saved_drafts} cover letter drafts to review.[/green]"
        )

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
