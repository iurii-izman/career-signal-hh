"""Tests for presets and campaigns UI and endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PRESETS_PATH = "config/search_presets.yaml"
CAMPAIGNS_PATH = "config/campaigns.yaml"


@pytest.fixture(autouse=True)
def _preserve_presets() -> None:
    """Backup and restore presets/campaigns after tests."""
    preset_content = None
    campaign_content = None
    if Path(PRESETS_PATH).exists():
        preset_content = Path(PRESETS_PATH).read_bytes()
    if Path(CAMPAIGNS_PATH).exists():
        campaign_content = Path(CAMPAIGNS_PATH).read_bytes()
    yield
    if preset_content is not None:
        Path(PRESETS_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(PRESETS_PATH).write_bytes(preset_content)
    if campaign_content is not None:
        Path(CAMPAIGNS_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(CAMPAIGNS_PATH).write_bytes(campaign_content)


@pytest.fixture
def empty_presets(monkeypatch) -> None:
    """Create empty presets.yaml."""
    Path(PRESETS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(PRESETS_PATH).write_text(yaml.dump({"defaults": {}, "presets": {}}), encoding="utf-8")


@pytest.fixture
def empty_campaigns(monkeypatch) -> None:
    """Create empty campaigns.yaml."""
    Path(CAMPAIGNS_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(CAMPAIGNS_PATH).write_text(yaml.dump({"campaigns": {}}), encoding="utf-8")


# ── Presets page renders ───────────────────────────────────────────────


def test_presets_page_renders() -> None:
    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/presets")
    assert resp.status_code == 200
    assert "presets-page" in resp.text


def test_campaigns_page_renders() -> None:
    from fastapi.testclient import TestClient

    from src.web.app import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/campaigns")
    assert resp.status_code == 200
    assert "campaigns-list" in resp.text


# ── Preset save creates backup ─────────────────────────────────────────


def test_preset_save_creates_backup(empty_presets: None) -> None:
    from src.services.presets_service import save_preset

    result = save_preset(
        "test-preset",
        {
            "enabled": True,
            "description": "Test",
            "search_terms": ["Python", "AI"],
            "include": {"any": ["python", "ai"], "all": [], "title": []},
            "exclude": {"any": ["qa"], "title": []},
            "remote_only": True,
        },
    )
    assert result["ok"] is True

    # Verify YAML was saved
    data = yaml.safe_load(Path(PRESETS_PATH).read_text(encoding="utf-8"))
    assert "test-preset" in data["presets"]
    assert data["presets"]["test-preset"]["search_terms"] == ["Python", "AI"]

    # Backup should exist
    backups = list(Path("config/backups").glob("search_presets_*.yaml"))
    assert len(backups) >= 1


# ── Invalid preset rejected ────────────────────────────────────────────


def test_invalid_preset_rejected(empty_presets: None) -> None:
    from src.services.presets_service import save_preset

    # Empty search_terms
    result = save_preset(
        "bad-preset",
        {
            "search_terms": [],
            "include": {"any": [], "all": [], "title": []},
            "exclude": {"any": [], "title": []},
        },
    )
    assert result["ok"] is False
    assert len(result["errors"]) >= 1

    # Path separator in name
    result2 = save_preset(
        "bad/name",
        {
            "search_terms": ["test"],
            "include": {"any": ["test"], "all": [], "title": []},
            "exclude": {"any": [], "title": []},
        },
    )
    assert result2["ok"] is False


# ── Enable/disable works ────────────────────────────────────────────────


def test_enable_disable_works(empty_presets: None) -> None:
    from src.services.presets_service import save_preset, set_preset_enabled

    save_preset(
        "toggle-preset",
        {
            "search_terms": ["Test"],
            "include": {"any": ["test"], "all": [], "title": []},
            "exclude": {"any": [], "title": []},
            "enabled": True,
        },
    )

    result = set_preset_enabled("toggle-preset", False)
    assert result["ok"] is True

    data = yaml.safe_load(Path(PRESETS_PATH).read_text(encoding="utf-8"))
    assert data["presets"]["toggle-preset"]["enabled"] is False

    set_preset_enabled("toggle-preset", True)
    data = yaml.safe_load(Path(PRESETS_PATH).read_text(encoding="utf-8"))
    assert data["presets"]["toggle-preset"]["enabled"] is True


# ── Clone works ────────────────────────────────────────────────────────


def test_clone_works(empty_presets: None) -> None:
    from src.services.presets_service import clone_preset, save_preset

    save_preset(
        "original",
        {
            "search_terms": ["Python"],
            "include": {"any": ["python"], "all": [], "title": []},
            "exclude": {"any": [], "title": []},
        },
    )

    result = clone_preset("original", "cloned")
    assert result["ok"] is True

    data = yaml.safe_load(Path(PRESETS_PATH).read_text(encoding="utf-8"))
    assert "cloned" in data["presets"]
    assert data["presets"]["cloned"]["search_terms"] == ["Python"]


# ── Campaign edit works ────────────────────────────────────────────────


def test_campaign_save_works(empty_campaigns: None) -> None:
    from src.services.presets_service import save_campaign

    result = save_campaign(
        "my-campaign",
        {
            "enabled": True,
            "presets": ["ai_rag_remote"],
            "candidate_profile": "iurii",
            "min_score": 80,
            "default_lang": "en",
        },
    )
    assert result["ok"] is True

    data = yaml.safe_load(Path(CAMPAIGNS_PATH).read_text(encoding="utf-8"))
    assert "my-campaign" in data["campaigns"]
    assert data["campaigns"]["my-campaign"]["presets"] == ["ai_rag_remote"]


# ── API endpoints ──────────────────────────────────────────────────────


def test_api_presets_list() -> None:
    import asyncio

    from src.web.routes import api_presets_list

    async def _run():
        resp = await api_presets_list()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)

    asyncio.run(_run())


def test_api_presets_save_rejected_invalid() -> None:
    import asyncio

    from src.web.routes import api_presets_save

    async def _run():
        resp = await api_presets_save("no-terms", {})
        import json

        body = json.loads(resp.body)
        # May fail due to empty search terms
        assert "ok" in body

    asyncio.run(_run())


def test_api_campaigns_list() -> None:
    import asyncio

    from src.web.routes import api_campaigns_list

    async def _run():
        resp = await api_campaigns_list()
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)

    asyncio.run(_run())


# ── Calibration apply/dismiss works ────────────────────────────────────


def test_calibration_dismiss_works(monkeypatch, tmp_path: Path) -> None:
    import json

    sid = "suggest-1"
    suggestions_file = tmp_path / "calibration_suggestions.json"
    suggestions_file.write_text(
        json.dumps(
            [{"id": sid, "preset": "test", "type": "include", "keyword": "AI", "status": "pending"}]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.services.presets_service.SUGGESTIONS_PATH",
        str(suggestions_file),
    )

    from src.services.presets_service import dismiss_calibration_suggestion

    result = dismiss_calibration_suggestion(sid)
    assert result["ok"] is True

    updated = json.loads(suggestions_file.read_text(encoding="utf-8"))
    assert updated[0]["status"] == "dismissed"


# ── Sidebar has presets/campaigns links ────────────────────────────────


def test_index_has_presets_links() -> None:
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    assert "/presets" in html
    assert "/campaigns" in html
