from __future__ import annotations

import os
import secrets
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from .hh_client import HHAuthorizationRequired, HHClient, HHConfigurationError
from .storage import Storage
from .utils import mask_secret

HH_OAUTH_PROVIDER = "hh_user_oauth"


class HHOAuthError(RuntimeError):
    pass


class HHOAuthStorageError(HHOAuthError):
    pass


@dataclass
class HHOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str
    storage_backend: str
    authorize_url: str = "https://hh.ru/oauth/authorize"
    token_url: str = "https://api.hh.ru/token"

    @classmethod
    def from_env(cls) -> "HHOAuthConfig":
        return cls(
            client_id=os.getenv("HH_CLIENT_ID", "").strip(),
            client_secret=os.getenv("HH_CLIENT_SECRET", "").strip(),
            redirect_uri=os.getenv("HH_REDIRECT_URI", "").strip(),
            scope=os.getenv("HH_OAUTH_SCOPE", "").strip(),
            storage_backend=os.getenv("HH_OAUTH_STORAGE", "keyring").strip().lower() or "keyring",
        )

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("HH_CLIENT_ID", self.client_id),
                ("HH_CLIENT_SECRET", self.client_secret),
                ("HH_REDIRECT_URI", self.redirect_uri),
            )
            if not value
        ]
        if missing:
            raise HHConfigurationError(
                "Managed OAuth requires "
                + ", ".join(missing)
                + " in .env before running oauth login/refresh."
            )
        if self.storage_backend != "keyring":
            raise HHConfigurationError(
                "Managed OAuth supports only HH_OAUTH_STORAGE=keyring. "
                "Manual HH_USER_ACCESS_TOKEN remains available as fallback."
            )


@dataclass
class OAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    token_type: str
    scope: str | None
    obtained_at: datetime
    expires_at: datetime | None

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(timezone.utc)


class KeyringTokenStore:
    def __init__(self, service_name: str = "career-signal-hh") -> None:
        self.service_name = service_name
        try:
            import keyring  # type: ignore
        except ImportError as exc:
            raise HHOAuthStorageError(
                "Managed OAuth storage requires the 'keyring' package. "
                "Install project dependencies again or keep using manual HH_USER_ACCESS_TOKEN."
            ) from exc
        self._keyring = keyring

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(self.service_name, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(self.service_name, key, value)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(self.service_name, key)
        except Exception:
            pass


class HHOAuthManager:
    def __init__(
        self,
        *,
        storage: Storage | None = None,
        config: HHOAuthConfig | None = None,
        token_store: KeyringTokenStore | None = None,
    ) -> None:
        self.storage = storage or Storage(os.getenv("DB_PATH", "data/vacancies.sqlite"))
        self.config = config or HHOAuthConfig.from_env()
        self._token_store = token_store

    def _store(self) -> KeyringTokenStore:
        if self._token_store is None:
            self._token_store = KeyringTokenStore()
        return self._token_store

    def build_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        self.config.validate()
        oauth_state = state or secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "state": oauth_state,
        }
        if self.config.scope:
            params["scope"] = self.config.scope
        return f"{self.config.authorize_url}?{urlencode(params)}", oauth_state

    def exchange_code(self, code: str) -> OAuthTokenBundle:
        self.config.validate()
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "code": code.strip(),
        }
        return self._token_request(payload)

    def refresh(self) -> OAuthTokenBundle:
        self.config.validate()
        refresh_token = self._store().get("refresh_token")
        if not refresh_token:
            raise HHOAuthError(
                "Managed refresh token is not stored locally. "
                "Run `python -m src.main oauth login` or use manual HH_USER_ACCESS_TOKEN fallback."
            )
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
        }
        bundle = self._token_request(payload)
        self._persist_bundle(bundle, mark_refresh=True)
        return bundle

    def login(self, *, code: str | None, open_browser: bool = False) -> dict[str, Any]:
        url, state = self.build_authorization_url()
        if open_browser:
            webbrowser.open(url)
        if not code:
            return {
                "ok": False,
                "message": "Authorization URL generated. Open it, approve access, then rerun oauth login --code <authorization_code>.",
                "authorization_url": url,
                "state": state,
            }
        bundle = self.exchange_code(code)
        profile = self._profile_from_token(bundle.access_token)
        self._persist_bundle(bundle, profile=profile)
        return {
            "ok": True,
            "message": "Managed OAuth tokens stored locally.",
            "authorization_url": url,
            "state": state,
            "profile": {
                "id": profile.get("id"),
                "email": profile.get("email"),
            },
        }

    def revoke_local(self) -> dict[str, Any]:
        store = self._store()
        store.delete("access_token")
        store.delete("refresh_token")
        self.storage.clear_oauth_meta(HH_OAUTH_PROVIDER)
        return {"ok": True, "message": "Managed OAuth tokens removed from local secure storage."}

    def status(self) -> dict[str, Any]:
        config = HHOAuthConfig.from_env()
        meta = self.storage.get_oauth_meta(HH_OAUTH_PROVIDER) or {}
        manual_token = os.getenv("HH_USER_ACCESS_TOKEN", "").strip()
        managed_access = None
        managed_refresh = None
        store_error = None
        try:
            managed_access = self._store().get("access_token")
            managed_refresh = self._store().get("refresh_token")
        except HHOAuthStorageError as exc:
            store_error = str(exc)
        expires_at_raw = meta.get("expires_at")
        expires_at = _parse_iso(expires_at_raw)
        return {
            "configured": bool(config.client_id and config.client_secret and config.redirect_uri),
            "storage_backend": config.storage_backend,
            "storage_error": store_error,
            "managed_access_token_present": bool(managed_access),
            "managed_refresh_token_present": bool(managed_refresh),
            "managed_access_token_hint": meta.get("access_token_hint") or mask_secret(managed_access),
            "managed_refresh_token_hint": meta.get("refresh_token_hint") or mask_secret(managed_refresh),
            "manual_env_token_present": bool(manual_token),
            "manual_env_token_hint": mask_secret(manual_token),
            "account_id": meta.get("account_id"),
            "account_email": meta.get("account_email"),
            "scope": meta.get("scope") or config.scope or None,
            "token_type": meta.get("token_type"),
            "obtained_at": meta.get("obtained_at"),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "expired": expires_at is not None and expires_at <= datetime.now(timezone.utc),
            "last_refresh_at": meta.get("last_refresh_at"),
            "last_sync_at": meta.get("last_sync_at"),
            "last_error": meta.get("last_error"),
        }

    def get_sync_client(self, *, allow_manual_fallback: bool = True) -> HHClient:
        store_error = None
        access_token = None
        try:
            access_token = self._store().get("access_token")
        except HHOAuthStorageError as exc:
            store_error = exc
        meta = self.storage.get_oauth_meta(HH_OAUTH_PROVIDER) or {}
        expires_at = _parse_iso(meta.get("expires_at"))
        if access_token and expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise HHOAuthError(
                "Managed OAuth access token is expired. Run `python -m src.main oauth refresh`."
            )
        if access_token:
            return HHClient(auth_mode="user_oauth", user_access_token=access_token)
        if allow_manual_fallback and os.getenv("HH_USER_ACCESS_TOKEN", "").strip():
            return HHClient(auth_mode="user_oauth")
        if store_error:
            raise store_error
        raise HHAuthorizationRequired(
            "No user OAuth token available for read-only sync. "
            "Use managed `oauth login` or set manual HH_USER_ACCESS_TOKEN."
        )

    def mark_sync_success(self) -> None:
        self.storage.mark_oauth_sync(HH_OAUTH_PROVIDER)

    def _token_request(self, payload: dict[str, str]) -> OAuthTokenBundle:
        try:
            response = requests.post(
                self.config.token_url,
                data=payload,
                headers={"User-Agent": os.getenv("HH_USER_AGENT", "CareerSignalHH/0.1")},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise HHOAuthError(f"HH OAuth token endpoint is unavailable: {exc}") from exc
        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text[:1000]
        if response.status_code >= 400:
            self._update_last_error(f"Token endpoint returned {response.status_code}.")
            raise HHOAuthError(
                f"HH OAuth token exchange failed with {response.status_code}: {body}"
            )
        obtained_at = datetime.now(timezone.utc)
        expires_in = body.get("expires_in")
        expires_at = (
            obtained_at + timedelta(seconds=int(expires_in))
            if expires_in not in (None, "")
            else None
        )
        return OAuthTokenBundle(
            access_token=body.get("access_token", "").strip(),
            refresh_token=(body.get("refresh_token") or "").strip() or None,
            token_type=(body.get("token_type") or "bearer").strip(),
            scope=body.get("scope"),
            obtained_at=obtained_at,
            expires_at=expires_at,
        )

    def _profile_from_token(self, access_token: str) -> dict[str, Any]:
        client = HHClient(auth_mode="user_oauth", user_access_token=access_token)
        return client.get_me()

    def _persist_bundle(
        self,
        bundle: OAuthTokenBundle,
        *,
        profile: dict[str, Any] | None = None,
        mark_refresh: bool = False,
    ) -> None:
        store = self._store()
        store.set("access_token", bundle.access_token)
        if bundle.refresh_token:
            store.set("refresh_token", bundle.refresh_token)
        existing = self.storage.get_oauth_meta(HH_OAUTH_PROVIDER) or {}
        if profile is None:
            try:
                profile = self._profile_from_token(bundle.access_token)
            except Exception:
                profile = {}
        meta = {
            "account_id": profile.get("id") or existing.get("account_id"),
            "account_email": profile.get("email") or existing.get("account_email"),
            "token_type": bundle.token_type,
            "scope": bundle.scope or self.config.scope or existing.get("scope"),
            "storage_backend": self.config.storage_backend,
            "access_token_present": True,
            "refresh_token_present": bool(bundle.refresh_token or existing.get("refresh_token_present")),
            "access_token_hint": mask_secret(bundle.access_token),
            "refresh_token_hint": (
                mask_secret(bundle.refresh_token)
                if bundle.refresh_token
                else existing.get("refresh_token_hint")
            ),
            "obtained_at": bundle.obtained_at.isoformat(),
            "expires_at": bundle.expires_at.isoformat() if bundle.expires_at else None,
            "last_refresh_at": bundle.obtained_at.isoformat() if mark_refresh else existing.get("last_refresh_at"),
            "last_sync_at": existing.get("last_sync_at"),
            "last_error": None,
        }
        self.storage.save_oauth_meta(HH_OAUTH_PROVIDER, meta)

    def _update_last_error(self, error: str) -> None:
        meta = self.storage.get_oauth_meta(HH_OAUTH_PROVIDER) or {
            "storage_backend": self.config.storage_backend,
            "access_token_present": False,
            "refresh_token_present": False,
        }
        meta["last_error"] = error
        self.storage.save_oauth_meta(HH_OAUTH_PROVIDER, meta)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
