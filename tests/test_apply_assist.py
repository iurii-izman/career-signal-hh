from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import Vacancy
from src.services import apply_assist_service
from src.storage import OUTBOX_TARGET_EXTERNAL_SYNC, Storage
from tests.helpers import parse_args

pytestmark = pytest.mark.no_network


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "apply_assist.sqlite"))


def _seed_ready_vacancy(tmp_path: Path) -> Storage:
    storage = _make_storage(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="assist-1",
            name="CRM Systems Analyst",
            employer_name="Acme",
            area_name="Remote",
            alternate_url="https://hh.ru/vacancy/assist-1",
            description_text="Bitrix24, CRM, remote role with integrations",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
            schedule_name="remote",
        )
    )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO scores (
                vacancy_id, total_score, ai_automation_score, bitrix_1c_score,
                best_profile, match_reasons_json, risk_flags_json, work_format_flags_json, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "assist-1",
                90,
                0,
                90,
                "bitrix",
                "[]",
                "[]",
                '["remote"]',
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO score_details (
                vacancy_id, preset_name, total_score, confidence_score, noise_score, decision,
                category_scores_json, matched_keywords_json, excluded_keywords_json, risk_flags_json,
                quality_flags_json, work_format_flags_json, explanation_json, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "assist-1",
                "crm_systems_analyst_remote",
                90,
                70,
                20,
                "strong_match",
                "{}",
                '[{"keyword":"CRM","field":"title"},{"keyword":"Bitrix24","field":"skills"}]',
                "[]",
                "[]",
                "[]",
                '["remote"]',
                "{}",
                now,
            ),
        )
    storage.upsert_review("assist-1", status="interesting", cover_letter_draft="# Draft")
    storage.upsert_briefing_report(
        "assist-1",
        lang="ru",
        score_total=90,
        decision="strong_match",
        report_md="# Briefing",
        payload={"score": {"total": 90, "decision": "strong_match"}},
    )
    return storage


def _good_preview(*_args, **_kwargs) -> dict[str, object]:
    return {
        "ok": True,
        "message": "ok",
        "data": {
            "letter_validation": {
                "ok": True,
                "reasons": [],
                "metrics": {"word_count": 92, "anchor_hits": ["CRM", "Bitrix24"]},
            }
        },
    }


def test_apply_assist_parses() -> None:
    args = parse_args(["apply-assist", "12345", "--approve", "--open-browser"])
    assert args.command == "apply-assist"
    assert args.vacancy_id == "12345"
    assert args.approve is True
    assert args.open_browser is True


def test_apply_assist_command_rejects_open_browser_without_approve(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from argparse import Namespace

    from src.commands import apply_assist as apply_assist_command

    monkeypatch.setattr(
        apply_assist_command,
        "execute_apply_assist",
        lambda *_args, **_kwargs: pytest.fail("execute_apply_assist should not be called"),
    )

    rc = apply_assist_command.command_apply_assist(
        Namespace(vacancy_id="assist-1", approve=False, open_browser=True)
    )

    captured = capsys.readouterr().out
    assert rc == 2
    assert "--open-browser" in captured
    assert "--approve" in captured


def test_apply_assist_blocks_without_briefing(tmp_path: Path, monkeypatch) -> None:
    storage = _seed_ready_vacancy(tmp_path)
    with storage.connect() as connection:
        connection.execute("DELETE FROM briefing_reports WHERE vacancy_id = ?", ("assist-1",))
    monkeypatch.setattr(apply_assist_service, "prepare_apply_pack_preview", _good_preview)

    result = apply_assist_service.execute_apply_assist(
        storage, "assist-1", approve=False, open_browser=False
    )

    assert result["ok"] is False
    assert result["error_type"] == "gates"
    assert "briefing_saved" in result["data"]["failed_gates"]

    events = storage.list_vacancy_events("assist-1", limit=10)
    event_types = [row["event_type"] for row in reversed(events)]
    assert event_types[-2:] == ["apply_assist_requested", "apply_assist_blocked"]


def test_apply_assist_ready_without_approve_logs_ready(tmp_path: Path, monkeypatch) -> None:
    storage = _seed_ready_vacancy(tmp_path)
    monkeypatch.setattr(apply_assist_service, "prepare_apply_pack_preview", _good_preview)

    result = apply_assist_service.execute_apply_assist(
        storage, "assist-1", approve=False, open_browser=False
    )

    assert result["ok"] is True
    assert "Re-run with --approve" in result["message"]

    events = storage.list_vacancy_events("assist-1", limit=20)
    event_types = [row["event_type"] for row in reversed(events)]
    assert event_types[-2:] == ["apply_assist_requested", "apply_assist_ready"]


def test_apply_assist_approve_opens_browser_and_emits_outbox(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _seed_ready_vacancy(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(apply_assist_service, "prepare_apply_pack_preview", _good_preview)
    monkeypatch.setattr(apply_assist_service.webbrowser, "open", lambda url: opened.append(url))

    result = apply_assist_service.execute_apply_assist(
        storage, "assist-1", approve=True, open_browser=True
    )

    assert result["ok"] is True
    assert result["message"] == "Apply assist handoff prepared for assist-1"
    assert opened == ["https://hh.ru/vacancy/assist-1"]

    events = storage.list_vacancy_events("assist-1", limit=20)
    event_types = [row["event_type"] for row in reversed(events)]
    assert event_types[-4:] == [
        "apply_assist_requested",
        "apply_assist_ready",
        "apply_assist_approved",
        "apply_assist_handoff_opened",
    ]

    outbox = storage.list_outbox_entries(
        status="pending",
        target=OUTBOX_TARGET_EXTERNAL_SYNC,
        vacancy_id="assist-1",
    )
    outbox_types = [row["event_type"] for row in outbox]
    assert "apply_assist_approved" in outbox_types
    assert "apply_assist_handoff_opened" in outbox_types


def test_apply_assist_blocks_on_hard_red_flag(tmp_path: Path, monkeypatch) -> None:
    storage = _make_storage(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="assist-2",
            name="Sales Manager",
            employer_name="Acme",
            alternate_url="https://hh.ru/vacancy/assist-2",
            description_text="Remote role",
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO score_details (
                vacancy_id, preset_name, total_score, confidence_score, noise_score, decision,
                category_scores_json, matched_keywords_json, excluded_keywords_json, risk_flags_json,
                quality_flags_json, work_format_flags_json, explanation_json, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "assist-2",
                "crm_systems_analyst_remote",
                90,
                70,
                20,
                "strong_match",
                "{}",
                "[]",
                "[]",
                "[]",
                "[]",
                '["remote"]',
                "{}",
                now,
            ),
        )
    storage.upsert_review("assist-2", status="interesting", cover_letter_draft="# Draft")
    storage.upsert_briefing_report(
        "assist-2",
        lang="ru",
        score_total=90,
        decision="strong_match",
        report_md="# Briefing",
        payload={"score": {"total": 90, "decision": "strong_match"}},
    )
    monkeypatch.setattr(apply_assist_service, "prepare_apply_pack_preview", _good_preview)

    result = apply_assist_service.prepare_apply_assist(storage, "assist-2")

    assert result["ok"] is False
    assert "hard_red_flags" in result["data"]["failed_gates"]
    assert result["data"]["hard_red_flags"] == ["title:sales manager"]
