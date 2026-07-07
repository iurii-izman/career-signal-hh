from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from typing import Any

from dotenv import load_dotenv
from rich.console import Console

from ..exporter_csv import export_csv, export_jsonl
from ..exporter_html import export_html
from ..models import Vacancy
from ..scoring import score_vacancy
from ..search_profiles import load_scoring_rules
from ..storage import Storage

console = Console()


def _sample_vacancies() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    samples = [
        (
            "sample-ai-llm",
            "LLM / RAG Automation Engineer",
            "Signal AI",
            "Python, FastAPI, LangChain, RAG, API integrations and n8n automation.",
            ["Python", "RAG", "LangChain"],
            "Удаленная работа",
            2500,
            4000,
            "USD",
            "ai_automation",
        ),
        (
            "sample-ai-integration",
            "Systems Integration Engineer",
            "Flow Systems",
            "Webhooks, PostgreSQL, Docker and CRM/ERP integrations.",
            ["API", "PostgreSQL", "Docker"],
            "Удаленная работа",
            180000,
            260000,
            "RUR",
            "ai_automation",
        ),
        (
            "sample-ai-pm",
            "Technical Project Manager AI",
            "Automation Lab",
            "Technical specifications and business process automation for GenAI products.",
            ["GenAI", "Automation"],
            "Гибрид",
            None,
            None,
            None,
            "ai_automation",
        ),
        (
            "sample-bitrix",
            "Архитектор CRM Битрикс24",
            "CRM Practice",
            "Битрикс24, смарт-процессы, роботы, триггеры и права доступа.",
            ["Битрикс24", "CRM"],
            "Удаленная работа",
            150000,
            220000,
            "RUR",
            "bitrix_1c",
        ),
        (
            "sample-1c",
            "Системный аналитик 1С / CRM",
            "Business Stack",
            "Интеграции с 1С, BPMN, AS-IS, TO-BE и техническое задание.",
            ["1С", "BPMN"],
            "Гибрид",
            2000,
            3000,
            "USD",
            "bitrix_1c",
        ),
        (
            "sample-low",
            "Менеджер по продажам",
            "Sales Only",
            "Холодные звонки и выполнение плана продаж.",
            [],
            "Полный день",
            None,
            None,
            None,
            "bitrix_1c",
        ),
    ]
    result: list[dict[str, Any]] = []
    for (
        vacancy_id,
        name,
        employer,
        description,
        skills,
        schedule,
        salary_from,
        salary_to,
        currency,
        profile,
    ) in samples:
        result.append(
            {
                "id": vacancy_id,
                "name": name,
                "employer": {"id": f"employer-{vacancy_id}", "name": employer},
                "area": {"name": "Demo region"},
                "alternate_url": f"https://hh.ru/vacancy/{vacancy_id}",
                "published_at": now,
                "created_at": now,
                "archived": False,
                "salary": (
                    {"from": salary_from, "to": salary_to, "currency": currency}
                    if salary_from is not None or salary_to is not None
                    else None
                ),
                "schedule": {"name": schedule},
                "employment": {"name": "Полная занятость"},
                "experience": {"name": "От 3 до 6 лет"},
                "description": f"<p>{description}</p>",
                "key_skills": [{"name": skill} for skill in skills],
                "_source_profile": profile,
            }
        )
    return result


def command_sample_export(args: argparse.Namespace) -> int:
    load_dotenv()
    db_path = args.db or "data/sample_vacancies.sqlite"
    storage = Storage(db_path)
    rules = load_scoring_rules()
    for item in _sample_vacancies():
        source_profile = item.pop("_source_profile")
        vacancy = Vacancy.from_hh(item, source_profile)
        storage.upsert_vacancy(vacancy)
        storage.upsert_score(score_vacancy(vacancy, rules))
    storage.set_review_status("sample-ai-llm", "interesting")
    storage.set_review_status("sample-ai-pm", "maybe")
    storage.set_review_status("sample-low", "rejected")
    storage.mark_applied("sample-bitrix", date.today().isoformat())
    rows = storage.list_vacancies()
    export_html(rows, "exports/vacancies_report.html")
    export_csv(rows, "exports/vacancies.csv")
    export_jsonl(rows, "exports/vacancies.jsonl")
    console.print(
        f"[green]Добавлено mock-вакансий: 6 в {db_path}. "
        f"Экспортировано записей: {len(rows)}.[/green]"
    )
    console.print("HTML: exports/vacancies_report.html")
    return 0
