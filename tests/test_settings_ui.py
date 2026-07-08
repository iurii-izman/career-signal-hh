"""Tests for settings UI — .env editing, candidate profile, token safety."""

from __future__ import annotations

from pathlib import Path

import pytest

ENV_PATH = ".env"
CANDIDATE_PATH = "config/candidate.yaml"


@pytest.fixture(autouse=True)
def _preserve_env() -> None:
    """Backup and restore candidate.yaml after tests. Skip .env (protected)."""
    cand_content = None
    if Path(CANDIDATE_PATH).exists():
        cand_content = Path(CANDIDATE_PATH).read_bytes()
    yield
    if cand_content is not None:
        Path(CANDIDATE_PATH).write_bytes(cand_content)


# ── Token masking ──────────────────────────────────────────────────────


def test_settings_endpoint_masks_token() -> None:
    import asyncio

    from src.web.routes import api_settings

    async def _run():
        resp = await api_settings()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        token_val = body["data"]["env"]["HH_APP_ACCESS_TOKEN"]
        oauth_token_val = body["data"]["env"]["HH_USER_ACCESS_TOKEN"]
        assert "operator" in body["data"]
        # Token must not be revealed fully
        assert "not set" in token_val or "*" in token_val or len(token_val) < 30
        assert "not set" in oauth_token_val or "*" in oauth_token_val or len(oauth_token_val) < 30
        # If token is set, it must have mask characters
        real_token = __import__("os").getenv("HH_APP_ACCESS_TOKEN", "")
        if real_token and len(real_token) > 8:
            assert "*" in token_val or "not set" in token_val

    asyncio.run(_run())


def test_token_never_in_response_body() -> None:
    """Settings response must never contain the raw token value."""
    import asyncio
    import os

    from src.web.routes import api_settings

    real_token = os.getenv("HH_APP_ACCESS_TOKEN", "")
    if not real_token:
        pytest.skip("No token set in environment")

    async def _run():
        resp = await api_settings()

        body_str = resp.body.decode("utf-8")
        assert real_token not in body_str

    asyncio.run(_run())


# ── .env editing ───────────────────────────────────────────────────────


def test_update_user_agent_works(tmp_path: Path, monkeypatch) -> None:
    """Saving user agent should update .env."""
    test_env = tmp_path / ".env"
    test_env.write_text("HH_USER_AGENT=old-agent\nHH_AUTH_MODE=none\n", encoding="utf-8")
    monkeypatch.setattr("src.services.settings_service.ENV_PATH", str(test_env))

    from src.services.settings_service import save_env_settings

    result = save_env_settings({"HH_USER_AGENT": "NewAgent/1.0"})
    assert result["ok"] is True

    content = test_env.read_text(encoding="utf-8")
    assert "NewAgent/1.0" in content


def test_env_backup_created(monkeypatch, tmp_path: Path) -> None:
    """Backup should be created before .env write."""
    test_env = tmp_path / ".env"
    test_env.write_text("HH_USER_AGENT=test\n", encoding="utf-8")
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(exist_ok=True)

    monkeypatch.setattr("src.services.settings_service.ENV_PATH", str(test_env))
    monkeypatch.setattr("src.services.settings_service.BACKUPS_DIR", backups_dir)

    from src.services.settings_service import save_env_settings

    save_env_settings({"HH_USER_AGENT": "Updated"})
    backups = list(backups_dir.glob("env_*"))
    assert len(backups) >= 1


def test_token_saved_but_never_returned(monkeypatch, tmp_path: Path) -> None:
    """Token replacement should be saved but never echoed back."""
    test_env = tmp_path / ".env"
    test_env.write_text("HH_APP_ACCESS_TOKEN=OLD_TOKEN_VALUE\n", encoding="utf-8")
    monkeypatch.setattr("src.services.settings_service.ENV_PATH", str(test_env))

    from src.services.settings_service import save_env_settings

    result = save_env_settings({"HH_APP_ACCESS_TOKEN": "NEW_TOKEN_12345"})
    assert result["ok"] is True
    # Message must NOT contain the new token
    assert "NEW_TOKEN_12345" not in result.get("message", "")

    # File must contain the new token
    content = test_env.read_text(encoding="utf-8")
    assert "NEW_TOKEN_12345" in content


def test_user_oauth_token_saved(monkeypatch, tmp_path: Path) -> None:
    """OAuth token replacement should be saved safely."""
    test_env = tmp_path / ".env"
    test_env.write_text("HH_USER_ACCESS_TOKEN=OLD_USER_TOKEN\n", encoding="utf-8")
    monkeypatch.setattr("src.services.settings_service.ENV_PATH", str(test_env))

    from src.services.settings_service import save_env_settings

    result = save_env_settings({"HH_USER_ACCESS_TOKEN": "NEW_USER_TOKEN_12345"})
    assert result["ok"] is True
    assert "NEW_USER_TOKEN_12345" not in result.get("message", "")

    content = test_env.read_text(encoding="utf-8")
    assert "NEW_USER_TOKEN_12345" in content


# ── Candidate profile ──────────────────────────────────────────────────


def test_candidate_yaml_edit_works(tmp_path: Path, monkeypatch) -> None:
    """Saving candidate profile should write candidate.yaml."""
    test_cand = tmp_path / "candidate.yaml"
    monkeypatch.setattr("src.services.settings_service.CANDIDATE_PATH", str(test_cand))

    from src.services.settings_service import save_candidate_profile

    data = {
        "candidate": {
            "name_ru": "Test User",
            "name_en": "Test",
            "location": "Remote",
            "links": {"github": "test"},
            "profiles": {"default": {"summary_ru": "Experienced"}},
        }
    }
    result = save_candidate_profile(data)
    assert result["ok"] is True
    assert test_cand.exists()


# ── Page renders ───────────────────────────────────────────────────────


def test_settings_page_renders() -> None:
    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "settings-section" in resp.text
    assert "candidate" in resp.text.lower()
    assert "Operator Control Plane" in resp.text


# ── Sidebar has settings link ──────────────────────────────────────────


def test_sidebar_has_settings_link() -> None:
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    assert "/settings" in html


def test_settings_template_has_operator_sections() -> None:
    html = Path("src/web/templates/settings.html").read_text(encoding="utf-8")
    assert "operator-summary" in html
    assert "btn-oauth-refresh" in html
    assert "btn-outbox-push" in html
    assert "operator-apply-assist" in html


def test_operator_oauth_refresh_endpoint(monkeypatch) -> None:
    import asyncio
    import json

    from src.web.routes import api_operator_oauth_refresh

    class _Bundle:
        expires_at = None

    class _FakeManager:
        def __init__(self, storage=None) -> None:
            self.storage = storage

        def refresh(self):
            return _Bundle()

    monkeypatch.setattr("src.hh_oauth.HHOAuthManager", _FakeManager)

    async def _run():
        resp = await api_operator_oauth_refresh()
        body = json.loads(resp.body)
        assert body["ok"] is True
        assert "refreshed" in body["message"].lower()

    asyncio.run(_run())


def test_operator_hh_sync_endpoint(monkeypatch) -> None:
    import asyncio
    import json

    from src.web.routes import api_operator_hh_sync
    from src.web.schemas import OperatorHHSyncRequest

    class _FakeHHSyncService:
        def __init__(self, storage=None) -> None:
            self.storage = storage

        def sync_negotiations(self, status=None, per_page=50):
            return {"entity": "negotiations", "count": 3, "status_filter": status, "per_page": per_page}

        def sync_messages(self, negotiation_id=None, status=None, per_page=50, messages_per_page=50):
            return {
                "entity": "messages",
                "count": 4,
                "negotiation_id": negotiation_id,
                "status_filter": status,
                "per_page": per_page,
                "messages_per_page": messages_per_page,
                "failed_negotiations": [],
            }

    monkeypatch.setattr("src.hh_sync.HHSyncService", _FakeHHSyncService)

    async def _run():
        resp = await api_operator_hh_sync(
            OperatorHHSyncRequest(entity="negotiations", status="active", per_page=25)
        )
        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["count"] == 3

    asyncio.run(_run())


def test_operator_hh_sync_messages_endpoint(monkeypatch) -> None:
    import asyncio
    import json

    from src.web.routes import api_operator_hh_sync
    from src.web.schemas import OperatorHHSyncRequest

    class _FakeHHSyncService:
        def __init__(self, storage=None) -> None:
            self.storage = storage

        def sync_messages(self, negotiation_id=None, status=None, per_page=50, messages_per_page=50):
            return {
                "entity": "messages",
                "count": 2,
                "negotiation_id": negotiation_id,
                "status_filter": status,
                "per_page": per_page,
                "messages_per_page": messages_per_page,
                "failed_negotiations": [],
            }

    monkeypatch.setattr("src.hh_sync.HHSyncService", _FakeHHSyncService)

    async def _run():
        resp = await api_operator_hh_sync(
            OperatorHHSyncRequest(
                entity="messages",
                negotiation_id="neg-42",
                per_page=25,
                messages_per_page=10,
            )
        )
        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["count"] == 2
        assert body["data"]["negotiation_id"] == "neg-42"

    asyncio.run(_run())


def test_operator_outbox_endpoint(monkeypatch) -> None:
    import asyncio
    import json

    from src.web.routes import api_operator_outbox
    from src.web.schemas import OperatorOutboxRequest

    class _FakeNotionSyncService:
        def __init__(self, storage, config) -> None:
            self.storage = storage
            self.config = config

        def push_entries(self, **kwargs):
            return {"processed": 2, "sent": 2, "failed": 0, "kwargs": kwargs}

        def dry_run_entries(self, **kwargs):
            return [{"entry": {"id": 1}, "body": {"delivery": {"outbox_id": 1}}, "kwargs": kwargs}]

    monkeypatch.setattr("src.web.routes.NotionSyncService", _FakeNotionSyncService)
    monkeypatch.setattr("src.web.routes.load_notion_sync_config", lambda: object())

    async def _run():
        resp = await api_operator_outbox(OperatorOutboxRequest(action="push_pending", limit=2))
        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["processed"] == 2

    asyncio.run(_run())


def test_operator_apply_assist_endpoints(monkeypatch) -> None:
    import asyncio
    import json

    from src.web.routes import (
        api_operator_apply_assist_approve,
        api_operator_apply_assist_preview,
    )
    from src.web.schemas import OperatorApplyAssistApprovalRequest

    monkeypatch.setattr(
        "src.web.routes.prepare_apply_assist",
        lambda storage, vacancy_id: {
            "ok": True,
            "message": f"Apply assist ready for {vacancy_id}",
            "data": {"vacancy": {"id": vacancy_id}},
        },
    )
    monkeypatch.setattr(
        "src.web.routes.execute_apply_assist",
        lambda storage, vacancy_id, approve, open_browser: {
            "ok": True,
            "message": f"Apply assist handoff prepared for {vacancy_id}",
            "data": {"vacancy": {"id": vacancy_id}, "approve": approve, "open_browser": open_browser},
        },
    )

    async def _run():
        preview = await api_operator_apply_assist_preview("vac-1")
        preview_body = json.loads(preview.body)
        assert preview_body["ok"] is True

        approve = await api_operator_apply_assist_approve(
            "vac-1",
            OperatorApplyAssistApprovalRequest(open_browser=False),
        )
        approve_body = json.loads(approve.body)
        assert approve_body["ok"] is True
        assert "handoff" in approve_body["message"].lower()

    asyncio.run(_run())
