from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
import yaml

from ..storage import OUTBOX_TARGET_EXTERNAL_SYNC, Storage
from ..utils import json_dumps, json_loads

DEFAULT_CONFIG_PATH = Path("config/notion_sync.yaml")


@dataclass(slots=True)
class NotionSyncConfig:
    enabled: bool
    target: str
    provider: str
    webhook_url_env: str
    webhook_secret_env: str
    timeout_seconds: int
    batch_size: int
    verify_tls: bool

    @property
    def webhook_url(self) -> str:
        return os.getenv(self.webhook_url_env, "").strip()

    @property
    def webhook_secret(self) -> str:
        return os.getenv(self.webhook_secret_env, "").strip()


def load_notion_sync_config(path: str | Path = DEFAULT_CONFIG_PATH) -> NotionSyncConfig:
    defaults = {
        "enabled": False,
        "target": OUTBOX_TARGET_EXTERNAL_SYNC,
        "provider": "n8n_webhook",
        "webhook_url_env": "JOB_TRACKER_WEBHOOK_URL",
        "webhook_secret_env": "JOB_TRACKER_SECRET",
        "timeout_seconds": 10,
        "batch_size": 10,
        "verify_tls": True,
    }

    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        payload = {}

    section = payload.get("notion_sync", {}) if isinstance(payload, dict) else {}
    if not isinstance(section, dict):
        section = {}
    merged = {**defaults, **section}
    return NotionSyncConfig(
        enabled=bool(merged["enabled"]),
        target=str(merged["target"] or OUTBOX_TARGET_EXTERNAL_SYNC),
        provider=str(merged["provider"] or "n8n_webhook"),
        webhook_url_env=str(merged["webhook_url_env"] or "JOB_TRACKER_WEBHOOK_URL"),
        webhook_secret_env=str(merged["webhook_secret_env"] or "JOB_TRACKER_SECRET"),
        timeout_seconds=max(1, int(merged["timeout_seconds"])),
        batch_size=max(1, int(merged["batch_size"])),
        verify_tls=bool(merged["verify_tls"]),
    )


def redact_webhook_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    path = parts.path or ""
    masked_path = path
    if path:
        chunks = [chunk for chunk in path.split("/") if chunk]
        if chunks:
            chunks[-1] = "***"
            masked_path = "/" + "/".join(chunks)
    query = "…" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, masked_path, query, ""))


def build_delivery_key(entry: dict[str, Any]) -> str:
    return f"cshh:{entry['target']}:{entry['id']}"


def build_delivery_envelope(
    entry: dict[str, Any],
    *,
    attempt_number: int | None = None,
    replayed: bool = False,
) -> dict[str, Any]:
    payload = json_loads(entry.get("payload_json"), default={}) or {}
    return {
        "delivery": {
            "outbox_id": entry["id"],
            "target": entry["target"],
            "status": entry["status"],
            "attempt": attempt_number if attempt_number is not None else int(entry["attempts"]) + 1,
            "delivery_key": build_delivery_key(entry),
            "replayed": replayed,
            "created_at": entry["created_at"],
            "updated_at": entry["updated_at"],
        },
        "event": payload,
    }


def _build_headers(config: NotionSyncConfig, body: str, delivery_key: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-CareerSignal-Delivery-Key": delivery_key,
        "X-CareerSignal-Source": "career-signal-hh",
    }
    secret = config.webhook_secret
    if secret:
        digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["X-CareerSignal-Signature"] = f"sha256={digest}"
    return headers


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    sanitized = dict(headers)
    if "X-CareerSignal-Signature" in sanitized:
        sanitized["X-CareerSignal-Signature"] = "[REDACTED]"
    return sanitized


class NotionSyncService:
    def __init__(
        self,
        storage: Storage,
        config: NotionSyncConfig | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.storage = storage
        self.config = config or load_notion_sync_config()
        self.session = session or requests.Session()

    def validate_push_ready(self) -> tuple[bool, str | None]:
        if not self.config.enabled:
            return False, "notion_sync.disabled=true"
        if not self.config.webhook_url:
            return False, f"env {self.config.webhook_url_env} is not set"
        return True, None

    def list_entries(
        self,
        *,
        status: str | None = None,
        vacancy_id: str | None = None,
        outbox_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.storage.list_outbox_entries(
            outbox_id=outbox_id,
            status=status,
            target=self.config.target,
            vacancy_id=vacancy_id,
            limit=limit or self.config.batch_size,
        )

    def dry_run_entries(
        self,
        *,
        status: str | None = None,
        vacancy_id: str | None = None,
        outbox_id: int | None = None,
        limit: int | None = None,
        replayed: bool = False,
    ) -> list[dict[str, Any]]:
        entries = self.list_entries(
            status=status,
            vacancy_id=vacancy_id,
            outbox_id=outbox_id,
            limit=limit,
        )
        result: list[dict[str, Any]] = []
        for entry in entries:
            envelope = build_delivery_envelope(entry, replayed=replayed)
            body = json_dumps(envelope)
            headers = _build_headers(self.config, body, envelope["delivery"]["delivery_key"])
            result.append(
                {
                    "entry": entry,
                    "url": redact_webhook_url(self.config.webhook_url),
                    "headers": sanitize_headers(headers),
                    "body": envelope,
                }
            )
        return result

    def push_entries(
        self,
        *,
        status: str | None = "pending",
        vacancy_id: str | None = None,
        outbox_id: int | None = None,
        limit: int | None = None,
        replayed: bool = False,
    ) -> dict[str, Any]:
        ready, reason = self.validate_push_ready()
        if not ready:
            raise ValueError(f"Webhook push is not ready: {reason}.")

        entries = self.list_entries(
            status=status,
            vacancy_id=vacancy_id,
            outbox_id=outbox_id,
            limit=limit,
        )
        blocked = [entry["id"] for entry in entries if str(entry.get("status") or "") == "sent"]
        if blocked:
            ids = ", ".join(str(item) for item in blocked)
            raise ValueError(
                "Sending already sent outbox entries is blocked to preserve local audit state. "
                f"Blocked outbox ids: {ids}."
            )
        results: list[dict[str, Any]] = []
        for entry in entries:
            attempt_number = int(entry.get("attempts") or 0) + 1
            envelope = build_delivery_envelope(
                entry,
                attempt_number=attempt_number,
                replayed=replayed,
            )
            body = json_dumps(envelope)
            headers = _build_headers(self.config, body, envelope["delivery"]["delivery_key"])
            try:
                response = self.session.post(
                    self.config.webhook_url,
                    data=body.encode("utf-8"),
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                    allow_redirects=False,
                    verify=self.config.verify_tls,
                )
                if 200 <= response.status_code < 300:
                    updated = self.storage.update_outbox_delivery_attempt(
                        entry["id"],
                        status="sent",
                        last_error=None,
                    )
                    results.append(
                        {
                            "id": entry["id"],
                            "status": "sent",
                            "http_status": response.status_code,
                            "attempts": updated["attempts"],
                            "last_error": None,
                        }
                    )
                    continue

                error_text = f"HTTP {response.status_code}"
                if response.text:
                    error_text += f": {response.text.strip()[:200]}"
                updated = self.storage.update_outbox_delivery_attempt(
                    entry["id"],
                    status="failed",
                    last_error=error_text,
                )
                results.append(
                    {
                        "id": entry["id"],
                        "status": "failed",
                        "http_status": response.status_code,
                        "attempts": updated["attempts"],
                        "last_error": error_text,
                    }
                )
            except requests.RequestException as exc:
                error_text = f"{exc.__class__.__name__}: {exc}"
                updated = self.storage.update_outbox_delivery_attempt(
                    entry["id"],
                    status="failed",
                    last_error=error_text[:240],
                )
                results.append(
                    {
                        "id": entry["id"],
                        "status": "failed",
                        "http_status": None,
                        "attempts": updated["attempts"],
                        "last_error": error_text[:240],
                    }
                )

        sent = sum(1 for row in results if row["status"] == "sent")
        failed = sum(1 for row in results if row["status"] == "failed")
        return {
            "sent": sent,
            "failed": failed,
            "processed": len(results),
            "results": results,
        }
