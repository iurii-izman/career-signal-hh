from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from src.models import Vacancy
from src.services.notion_sync_service import (
    NotionSyncConfig,
    NotionSyncService,
    build_delivery_envelope,
)
from src.storage import Storage

pytestmark = pytest.mark.no_network


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _RecordingSession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _storage_with_outbox(tmp_path: Path) -> Storage:
    storage = Storage(str(tmp_path / "notion-sync.sqlite"))
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
    storage.set_review_status("vacancy-1", "interesting")
    return storage


def _service(storage: Storage, session: _RecordingSession | None = None) -> NotionSyncService:
    config = NotionSyncConfig(
        enabled=True,
        target="external_sync",
        provider="n8n_webhook",
        webhook_url_env="JOB_TRACKER_WEBHOOK_URL",
        webhook_secret_env="JOB_TRACKER_SECRET",
        timeout_seconds=5,
        batch_size=10,
        verify_tls=True,
    )
    return NotionSyncService(storage, config, session=session)


def test_dry_run_builds_delivery_envelope_with_stable_key(tmp_path: Path, monkeypatch) -> None:
    storage = _storage_with_outbox(tmp_path)
    monkeypatch.setenv("JOB_TRACKER_WEBHOOK_URL", "https://example.com/webhook/test-secret")
    monkeypatch.setenv("JOB_TRACKER_SECRET", "super-secret")
    service = _service(storage)

    dry = service.dry_run_entries(status="pending", limit=1)

    assert len(dry) == 1
    item = dry[0]
    entry = item["entry"]
    body = item["body"]
    assert body["delivery"]["outbox_id"] == entry["id"]
    assert body["delivery"]["delivery_key"] == f"cshh:external_sync:{entry['id']}"
    assert body["event"]["event_type"] == "review_status_changed"
    assert item["headers"]["X-CareerSignal-Signature"] == "[REDACTED]"
    assert item["url"] == "https://example.com/webhook/***"


def test_push_success_marks_entry_sent(tmp_path: Path, monkeypatch) -> None:
    storage = _storage_with_outbox(tmp_path)
    monkeypatch.setenv("JOB_TRACKER_WEBHOOK_URL", "https://example.com/hook/test")
    monkeypatch.setenv("JOB_TRACKER_SECRET", "super-secret")
    session = _RecordingSession([_FakeResponse(202, "accepted")])
    service = _service(storage, session)

    result = service.push_entries(status="pending", limit=1)

    assert result["sent"] == 1
    assert result["failed"] == 0
    entry = storage.get_outbox_entry(1)
    assert entry is not None
    assert entry["status"] == "sent"
    assert entry["attempts"] == 1
    assert session.calls[0]["url"] == "https://example.com/hook/test"
    headers = session.calls[0]["headers"]
    assert headers["X-CareerSignal-Delivery-Key"] == "cshh:external_sync:1"
    sent_body = json.loads(session.calls[0]["data"].decode("utf-8"))
    assert sent_body["delivery"]["delivery_key"] == "cshh:external_sync:1"


def test_push_failure_marks_entry_failed_and_retry_keeps_same_key(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage_with_outbox(tmp_path)
    monkeypatch.setenv("JOB_TRACKER_WEBHOOK_URL", "https://example.com/hook/test")
    monkeypatch.setenv("JOB_TRACKER_SECRET", "super-secret")
    session = _RecordingSession(
        [
            requests.ConnectionError("network down"),
            _FakeResponse(200, "ok"),
        ]
    )
    service = _service(storage, session)

    first = service.push_entries(status="pending", limit=1)
    assert first["sent"] == 0
    assert first["failed"] == 1

    failed_entry = storage.get_outbox_entry(1)
    assert failed_entry is not None
    assert failed_entry["status"] == "failed"
    assert failed_entry["attempts"] == 1
    assert "network down" in (failed_entry["last_error"] or "")

    first_key = build_delivery_envelope(failed_entry)["delivery"]["delivery_key"]
    second = service.push_entries(status="failed", outbox_id=1, limit=1, replayed=True)
    assert second["sent"] == 1

    retried_entry = storage.get_outbox_entry(1)
    assert retried_entry is not None
    assert retried_entry["status"] == "sent"
    assert retried_entry["attempts"] == 2
    second_key = build_delivery_envelope(retried_entry)["delivery"]["delivery_key"]
    assert second_key == first_key


def test_push_blocks_already_sent_entries(tmp_path: Path, monkeypatch) -> None:
    storage = _storage_with_outbox(tmp_path)
    monkeypatch.setenv("JOB_TRACKER_WEBHOOK_URL", "https://example.com/hook/test")
    service = _service(storage, _RecordingSession([]))

    storage.update_outbox_delivery_attempt(1, status="sent", last_error=None)

    with pytest.raises(ValueError, match="already sent outbox entries is blocked"):
        service.push_entries(status="sent", limit=1)
