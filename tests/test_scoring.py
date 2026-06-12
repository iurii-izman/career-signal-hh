from datetime import datetime, timezone

from src.models import Vacancy
from src.scoring import score_vacancy
from src.search_profiles import load_scoring_rules


def make_vacancy(name: str, description: str) -> Vacancy:
    return Vacancy(
        id="test-1",
        name=name,
        description_text=description,
        raw_json="{}",
        first_seen_at=datetime.now(timezone.utc).isoformat(),
        last_seen_at=datetime.now(timezone.utc).isoformat(),
        published_at=datetime.now(timezone.utc).isoformat(),
    )


def test_ai_vacancy_scores_high() -> None:
    result = score_vacancy(
        make_vacancy(
            "LLM / RAG Engineer",
            "Python, FastAPI, LangChain, API integrations and n8n automation.",
        ),
        load_scoring_rules(),
    )
    assert result.ai_automation_score >= 50
    assert result.best_profile == "ai_automation"


def test_bitrix_vacancy_scores_high() -> None:
    result = score_vacancy(
        make_vacancy(
            "Архитектор CRM Битрикс24",
            "Интеграции с 1С, бизнес-процессы, BPMN, AS-IS и TO-BE.",
        ),
        load_scoring_rules(),
    )
    assert result.bitrix_1c_score >= 50
    assert result.best_profile == "bitrix_1c"


def test_sales_only_gets_risk_and_low_score() -> None:
    result = score_vacancy(
        make_vacancy(
            "Менеджер по продажам",
            "Холодные звонки и выполнение плана продаж.",
        ),
        load_scoring_rules(),
    )
    assert result.total_score <= 10
    assert "sales_only" in result.risk_flags
    assert result.best_profile == "low_match"
