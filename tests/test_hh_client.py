from __future__ import annotations

from typing import Any

import pytest

from src.hh_client import HHAuthorizationRequired, HHClient


class FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return self._body


def test_none_mode_does_not_add_authorization() -> None:
    client = HHClient("TestClient/1.0", auth_mode="none")
    assert "Authorization" not in client.session.headers


def test_application_token_adds_bearer_header() -> None:
    client = HHClient(
        "TestClient/1.0",
        auth_mode="application_token",
        app_access_token="secret-token-value",
    )
    assert client.session.headers["Authorization"] == "Bearer secret-token-value"


def test_user_oauth_adds_bearer_header() -> None:
    client = HHClient(
        "TestClient/1.0",
        auth_mode="user_oauth",
        user_access_token="user-secret-token",
    )
    assert client.session.headers["Authorization"] == "Bearer user-secret-token"


def test_403_has_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HHClient("TestClient/1.0", auth_mode="none")
    monkeypatch.setattr(
        client.session,
        "get",
        lambda *args, **kwargs: FakeResponse(403, {"errors": [{"type": "forbidden"}]}),
    )

    with pytest.raises(HHAuthorizationRequired) as error:
        client.search_vacancies("python", per_page=1)

    assert error.value.status_code == 403
    assert error.value.body == {"errors": [{"type": "forbidden"}]}
    assert "HH_APP_ACCESS_TOKEN" in str(error.value)
    assert "HH_AUTH_MODE=application_token" in str(error.value)


def test_get_negotiations_passes_page_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HHClient("TestClient/1.0", auth_mode="user_oauth", user_access_token="token")
    captured: dict[str, object] = {}

    def _fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse(200, {"items": [], "page": 2, "pages": 3, "per_page": 25})

    monkeypatch.setattr(client.session, "get", _fake_get)
    payload = client.get_negotiations(status="active", per_page=25, page=2)

    assert payload["page"] == 2
    assert captured["url"] == "https://api.hh.ru/negotiations"
    assert captured["params"] == {"status": "active", "per_page": 25, "page": 2}


def test_get_negotiation_messages_uses_read_only_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = HHClient("TestClient/1.0", auth_mode="user_oauth", user_access_token="token")
    captured: dict[str, object] = {}

    def _fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse(200, {"items": [], "page": 0, "pages": 1, "per_page": 50})

    monkeypatch.setattr(client.session, "get", _fake_get)
    payload = client.get_negotiation_messages("neg-42", per_page=50, page=0)

    assert payload["pages"] == 1
    assert captured["url"] == "https://api.hh.ru/negotiations/neg-42/messages"
    assert captured["params"] == {"per_page": 50, "page": 0}
