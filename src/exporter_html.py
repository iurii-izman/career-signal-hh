from __future__ import annotations

import html
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .utils import json_loads, salary_to_str, truncate


def _e(value: Any) -> str:
    return html.escape(str(value or ""))


def export_html(rows: list[dict[str, Any]], path: str | Path) -> None:
    total = len(rows)
    top_score = max((row.get("total_score") or 0 for row in rows), default=0)
    new_24h = sum(
        1 for row in rows if row.get("first_seen_at", "") >= _day_ago_iso()
    )
    remote = sum(
        "remote" in json_loads(row.get("work_format_flags_json"), []) for row in rows
    )
    ai = sum((row.get("ai_automation_score") or 0) >= 15 for row in rows)
    bitrix = sum((row.get("bitrix_1c_score") or 0) >= 15 for row in rows)
    cards = []
    for row in rows:
        reasons = json_loads(row.get("match_reasons_json"), [])
        risks = json_loads(row.get("risk_flags_json"), [])
        work = json_loads(row.get("work_format_flags_json"), [])
        salary = salary_to_str(
            row.get("salary_from"), row.get("salary_to"), row.get("salary_currency")
        )
        search = " ".join(
            str(row.get(key) or "")
            for key in ("name", "employer_name", "area_name", "description_text")
        ).casefold()
        cards.append(f"""
<article class="vacancy" data-score="{row.get('total_score') or 0}"
 data-profile="{_e(row.get('best_profile'))}" data-remote="{str('remote' in work).lower()}"
 data-salary="{str(row.get('salary_from') is not None or row.get('salary_to') is not None).lower()}"
 data-search="{_e(search)}">
 <div class="score">{row.get('total_score') or 0}</div>
 <div class="body">
  <div class="heading"><span class="badge">{_e(row.get('best_profile'))}</span>
   <a href="{_e(row.get('alternate_url'))}" target="_blank" rel="noopener">{_e(row.get('name'))}</a></div>
  <div class="meta">{_e(row.get('employer_name'))} · {_e(row.get('area_name'))} · {_e(salary)}</div>
  <div class="meta">{_e(row.get('schedule_name'))} · {_e(row.get('employment_name'))} · {_e(row.get('experience_name'))} · {_e((row.get('published_at') or '')[:10])}</div>
  <p>{_e(truncate(row.get('description_text'), 300))}</p>
  <div class="tags">{''.join(f'<span>{_e(x)}</span>' for x in reasons)}</div>
  <div class="risks">{''.join(f'<span>{_e(x)}</span>' for x in risks)}</div>
  <small>Источник: {_e(row.get('source_profile'))}</small>
 </div>
</article>""")
    document = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CareerSignal HH</title><style>
:root{{--bg:#0b1020;--panel:#141b2d;--line:#26324d;--text:#e8edf7;--muted:#9ba8bd;--accent:#67e8f9}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:28px}} h1{{margin:0 0 18px;font-size:28px}}
.summary{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px}}
.summary div,.filters,.vacancy{{background:var(--panel);border:1px solid var(--line);border-radius:12px}}
.summary div{{padding:14px}} .summary strong{{display:block;font-size:22px;color:var(--accent)}} .summary span,.meta,small{{color:var(--muted)}}
.filters{{display:flex;gap:10px;flex-wrap:wrap;padding:12px;margin-bottom:12px;position:sticky;top:0;z-index:2}}
input,select{{background:#0e1527;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px}}
.vacancy{{display:grid;grid-template-columns:64px 1fr;gap:14px;padding:16px;margin:10px 0}}
.score{{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;background:#123448;color:#67e8f9;font-size:20px;font-weight:800}}
.heading{{font-size:18px;font-weight:700}} a{{color:#d9f8ff;text-decoration:none}} a:hover{{text-decoration:underline}}
.badge,.tags span,.risks span{{display:inline-block;padding:3px 7px;border-radius:6px;margin:2px 4px 2px 0;font-size:12px}}
.badge,.tags span{{background:#193b42;color:#9bf6e8}} .risks span{{background:#4a2029;color:#ffb4c0}}
p{{color:#cbd5e1;line-height:1.5}} @media(max-width:800px){{.summary{{grid-template-columns:repeat(2,1fr)}} main{{padding:14px}}}}
</style></head><body><main><h1>CareerSignal HH</h1>
<section class="summary">{''.join(f'<div><strong>{v}</strong><span>{k}</span></div>' for k,v in [('Всего',total),('Top score',top_score),('Новые 24ч',new_24h),('Remote',remote),('AI matches',ai),('Bitrix/1C',bitrix)])}</section>
<section class="filters"><input id="q" placeholder="Поиск"><input id="min" type="number" min="0" max="100" value="0" placeholder="Min score">
<select id="profile"><option value="">Все профили</option><option>ai_automation</option><option>bitrix_1c</option><option>mixed</option><option>low_match</option></select>
<label><input id="remote" type="checkbox"> Только remote</label><label><input id="salary" type="checkbox"> С зарплатой</label>
<label><input id="low" type="checkbox"> Скрыть low match</label></section>
<section id="list">{''.join(cards)}</section></main><script>
const controls=[q,min,profile,remote,salary,low];function filter(){{
 const text=q.value.toLowerCase(), threshold=Number(min.value||0);
 document.querySelectorAll('.vacancy').forEach(v=>{{
  const show=v.dataset.search.includes(text)&&Number(v.dataset.score)>=threshold&&
   (!profile.value||v.dataset.profile===profile.value)&&(!remote.checked||v.dataset.remote==='true')&&
   (!salary.checked||v.dataset.salary==='true')&&(!low.checked||v.dataset.profile!=='low_match');
  v.hidden=!show;
 }});
}} controls.forEach(c=>c.addEventListener('input',filter));
</script></body></html>"""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=output.parent
    ) as handle:
        handle.write(document)
        temp = Path(handle.name)
    os.replace(temp, output)


def _day_ago_iso() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
