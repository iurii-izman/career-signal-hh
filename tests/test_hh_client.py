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
