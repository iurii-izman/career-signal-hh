from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .utils import json_loads

CSV_FIELDS = [
    "id",
    "total_score",
    "decision",
    "best_profile",
    "preset_name",
    "name",
    "employer_name",
    "area_name",
    "salary_from",
    "salary_to",
    "salary_currency",
    "schedule_name",
    "employment_name",
    "experience_name",
    "published_at",
    "matched_keywords",
    "excluded_keywords",
    "category_scores",
    "match_reasons",
    "risk_flags",
    "review_status",
    "priority",
    "user_notes",
    "applied_at",
    "next_action",
    "next_action_at",
    "alternate_url",
]


def _atomic_write(path: Path, writer: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=path.parent
    ) as handle:
        temp_path = Path(handle.name)
        writer(handle)
    os.replace(temp_path, path)


def export_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    def write(handle: Any) -> None:
        output = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        output.writeheader()
        for row in rows:
            item = dict(row)
            item["match_reasons"] = "; ".join(json_loads(row.get("match_reasons_json"), []))
            item["risk_flags"] = "; ".join(json_loads(row.get("risk_flags_json"), []))
            # v2 fields
            item["matched_keywords"] = _fmt_keywords(row.get("matched_keywords_json"))
            item["excluded_keywords"] = _fmt_keywords(row.get("excluded_keywords_json"))
            item["category_scores"] = _fmt_json_obj(row.get("category_scores_json"))
            output.writerow(item)

    _atomic_write(Path(path), write)


def _fmt_keywords(raw: str | None) -> str:
    items = json_loads(raw, [])
    if not items:
        return ""
    return "; ".join(
        f"{kw.get('keyword', '')}:{kw.get('field', '')}({kw.get('weight', '')})"
        for kw in items[:10]
    )


def _fmt_json_obj(raw: str | None) -> str:
    data = json_loads(raw, {})
    if not data:
        return ""
    import json

    return json.dumps(data, ensure_ascii=False)


def export_jsonl(rows: list[dict[str, Any]], path: str | Path) -> None:
    def write(handle: Any) -> None:
        for row in rows:
            item = dict(row)
            item["key_skills"] = json_loads(item.pop("key_skills_json", None), [])
            item["match_reasons"] = json_loads(item.pop("match_reasons_json", None), [])
            item["risk_flags"] = json_loads(item.pop("risk_flags_json", None), [])
            item["work_format_flags"] = json_loads(item.pop("work_format_flags_json", None), [])
            item.pop("raw_json", None)
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    _atomic_write(Path(path), write)
