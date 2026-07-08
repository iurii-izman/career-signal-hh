from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.models import Vacancy
from src.storage import OUTBOX_TARGET_EXTERNAL_SYNC, Storage


def _storage_with_vacancy(tmp_path: Path) -> Storage:
    storage = Storage(str(tmp_path / "evented.sqlite"))
    now = datetime.now(timezone.utc).isoformat()
    storage.upsert_vacancy(
        Vacancy(
            id="vacancy-1",
            name="Python Automation Engineer",
            employer_name="Example",
            area_name="Remote",
            alternate_url="https://hh.ru/vacancy/1",
            published_at=now,
            raw_json="{}",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    return storage


def test_review_actions_emit_events_and_outbox(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)

    storage.set_review_status("vacancy-1", "interesting")
    storage.set_review_note("vacancy-1", "Проверить стек и compensation")
    storage.set_next_action("vacancy-1", "Follow up", "2026-07-10")
    storage.mark_applied("vacancy-1", "2026-07-11")

    events = storage.list_vacancy_events("vacancy-1", limit=10)
    event_types = [row["event_type"] for row in reversed(events)]
    assert event_types == [
        "review_status_changed",
        "review_note_updated",
        "review_next_action_set",
        "review_applied",
    ]

    status_event = next(row for row in events if row["event_type"] == "review_status_changed")
    assert status_event["old_status"] == "new"
    assert status_event["new_status"] == "interesting"

    applied_event = next(row for row in events if row["event_type"] == "review_applied")
    applied_payload = json.loads(applied_event["payload_json"])
    assert applied_event["old_status"] == "interesting"
    assert applied_event["new_status"] == "applied"
    assert applied_payload["applied_at"] == "2026-07-11"

    outbox = storage.list_outbox_entries(status="pending", target=OUTBOX_TARGET_EXTERNAL_SYNC)
    outbox_types = [row["event_type"] for row in outbox]
    assert outbox_types == [
        "review_status_changed",
        "review_next_action_set",
        "review_applied",
    ]

    payload = json.loads(outbox[-1]["payload_json"])
    assert payload["event_type"] == "review_applied"
    assert payload["vacancy"]["id"] == "vacancy-1"
    assert payload["review"]["status"] == "applied"


def test_briefing_report_write_emits_event_and_outbox(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)
    storage.set_review_status("vacancy-1", "interesting")

    payload = {
        "vacancy_id": "vacancy-1",
        "score": {"total": 88, "decision": "strong_match"},
        "blocks": [{"key": "snapshot"}, {"key": "recommended_action"}],
    }
    storage.upsert_briefing_report(
        "vacancy-1",
        lang="ru",
        score_total=88,
        decision="strong_match",
        report_md="# Briefing",
        payload=payload,
    )

    events = storage.list_vacancy_events("vacancy-1", limit=10)
    briefing_event = next(row for row in events if row["event_type"] == "briefing_saved")
    briefing_payload = json.loads(briefing_event["payload_json"])
    assert briefing_payload["lang"] == "ru"
    assert briefing_payload["is_new"] is True

    outbox = storage.list_outbox_entries(status="pending", target=OUTBOX_TARGET_EXTERNAL_SYNC)
    briefing_outbox = next(row for row in outbox if row["event_type"] == "briefing_saved")
    outbox_payload = json.loads(briefing_outbox["payload_json"])
    assert outbox_payload["briefing"]["score_total"] == 88
    assert outbox_payload["review"]["status"] == "interesting"


def test_review_draft_save_emits_event_and_outbox(tmp_path: Path) -> None:
    storage = _storage_with_vacancy(tmp_path)

    storage.upsert_review("vacancy-1", cover_letter_draft="# Draft\n\nHello")

    events = storage.list_vacancy_events("vacancy-1", limit=10)
    draft_event = next(row for row in events if row["event_type"] == "review_draft_saved")
    draft_payload = json.loads(draft_event["payload_json"])
    assert draft_payload["had_draft_before"] is False
    assert draft_payload["has_draft_after"] is True
    assert draft_payload["draft_length"] > 0

    outbox = storage.list_outbox_entries(status="pending", target=OUTBOX_TARGET_EXTERNAL_SYNC)
    assert [row["event_type"] for row in outbox] == ["review_draft_saved"]
