from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest
from rich.console import Console

from src.commands import oauth as oauth_commands
from src.hh_client import HHConfigurationError
from src.hh_oauth import HHOAuthError, HHOAuthManager
from src.storage import Storage


class FakeTokenStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _make_storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "oauth.sqlite"))


def test_oauth_status_masks_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(tmp_path)
    storage.save_oauth_meta(
        "hh_user_oauth",
        {
            "storage_backend": "keyring",
            "access_token_present": True,
            "refresh_token_present": True,
            "account_id": "42",
            "account_email": "user@example.com",
        },
    )
    monkeypatch.setenv("HH_CLIENT_ID", "client-id")
    monkeypatch.setenv("HH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("HH_REDIRECT_URI", "https://example.test/callback")
    monkeypatch.setenv("HH_USER_ACCESS_TOKEN", "MANUAL_SECRET_123456789")
    manager = HHOAuthManager(
        storage=storage,
        token_store=FakeTokenStore(
            {
                "access_token": "MANAGED_SECRET_123456789",
                "refresh_token": "REFRESH_SECRET_123456789",
            }
        ),
    )

    status = manager.status()
    rendered = str(status)

    assert "MANAGED_SECRET_123456789" not in rendered
    assert "REFRESH_SECRET_123456789" not in rendered
    assert "MANUAL_SECRET_123456789" not in rendered
    assert "*" in status["managed_access_token_hint"]
    assert "*" in status["managed_refresh_token_hint"]
    assert "*" in status["manual_env_token_hint"]


def test_oauth_refresh_requires_refresh_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_CLIENT_ID", "client-id")
    monkeypatch.setenv("HH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("HH_REDIRECT_URI", "https://example.test/callback")
    manager = HHOAuthManager(storage=_make_storage(tmp_path), token_store=FakeTokenStore())

    with pytest.raises(HHOAuthError) as error:
        manager.refresh()

    assert "refresh token" in str(error.value).lower()


def test_get_sync_client_uses_manual_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_USER_ACCESS_TOKEN", "MANUAL_SECRET_123456789")
    manager = HHOAuthManager(storage=_make_storage(tmp_path), token_store=FakeTokenStore())

    client = manager.get_sync_client()

    assert client.active_token == "MANUAL_SECRET_123456789"
    assert client.auth_mode == "user_oauth"


def test_reconcile_counts_local_matches(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO vacancies (
                id, name, employer_id, employer_name, area_name, alternate_url,
                published_at, created_at, archived, salary_from, salary_to, salary_currency,
                schedule_name, employment_name, experience_name, description_html,
                description_text, key_skills_json, raw_json, first_seen_at, last_seen_at,
                source_profile, source_query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "vac-1",
                "Vacancy",
                "emp-1",
                "Employer",
                "Area",
                "https://hh.ru/vacancy/vac-1",
                "2026-07-08T00:00:00+00:00",
                "2026-07-08T00:00:00+00:00",
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                "",
                "",
                "[]",
                "{}",
                "2026-07-08T00:00:00+00:00",
                "2026-07-08T00:00:00+00:00",
                "test",
                "query",
            ),
        )
    storage.save_hh_negotiations(
        [
            {
                "id": "neg-1",
                "vacancy": {"id": "vac-1"},
                "resume": {"id": "res-1"},
                "state": {"id": "active"},
            },
            {
                "id": "neg-2",
                "vacancy": {"id": "vac-404"},
                "resume": {"id": "res-2"},
                "state": {"id": "active"},
            },
        ]
    )

    summary = storage.get_hh_sync_summary()

    assert summary["negotiations"] == 2
    assert summary["negotiations_matched_local_vacancies"] == 1


def test_oauth_status_command_never_prints_raw_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    output = Console(record=True, width=140)
    monkeypatch.setattr(oauth_commands, "console", output)
    monkeypatch.setattr(oauth_commands, "load_dotenv", lambda: None)

    class FakeManager:
        def status(self) -> dict[str, object]:
            return {
                "configured": True,
                "storage_backend": "keyring",
                "storage_error": None,
                "managed_access_token_present": True,
                "managed_refresh_token_present": True,
                "managed_access_token_hint": "MANA********6789",
                "managed_refresh_token_hint": "REFR********6789",
                "manual_env_token_present": True,
                "manual_env_token_hint": "MANU********6789",
                "account_id": "1",
                "account_email": "user@example.com",
                "scope": "resume",
                "token_type": "bearer",
                "obtained_at": None,
                "expires_at": None,
                "expired": False,
                "last_refresh_at": None,
                "last_sync_at": None,
                "last_error": None,
            }

    monkeypatch.setattr(oauth_commands, "HHOAuthManager", FakeManager)
    rc = oauth_commands.command_oauth_status(Namespace())

    rendered = output.export_text()
    assert rc == 0
    assert "MANA********6789" in rendered
    assert "MANAGED_SECRET" not in rendered


def test_oauth_login_command_handles_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = Console(record=True, width=140)
    monkeypatch.setattr(oauth_commands, "console", output)
    monkeypatch.setattr(oauth_commands, "load_dotenv", lambda: None)

    class FakeManager:
        def login(self, *, code: str | None, open_browser: bool = False) -> dict[str, object]:
            raise HHConfigurationError("HH_CLIENT_ID missing")

    monkeypatch.setattr(oauth_commands, "HHOAuthManager", FakeManager)
    rc = oauth_commands.command_oauth_login(Namespace(code=None, open_browser=False))

    rendered = output.export_text()
    assert rc == 1
    assert "HH_CLIENT_ID missing" in rendered


def test_oauth_refresh_command_handles_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = Console(record=True, width=140)
    monkeypatch.setattr(oauth_commands, "console", output)
    monkeypatch.setattr(oauth_commands, "load_dotenv", lambda: None)

    class FakeManager:
        def refresh(self) -> object:
            raise HHConfigurationError("HH_REDIRECT_URI missing")

    monkeypatch.setattr(oauth_commands, "HHOAuthManager", FakeManager)
    rc = oauth_commands.command_oauth_refresh(Namespace())

    rendered = output.export_text()
    assert rc == 1
    assert "HH_REDIRECT_URI missing" in rendered
