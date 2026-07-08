from __future__ import annotations

from typing import Any

from .hh_oauth import HHOAuthManager
from .storage import Storage


class HHSyncService:
    def __init__(
        self,
        *,
        storage: Storage | None = None,
        oauth_manager: HHOAuthManager | None = None,
    ) -> None:
        self.storage = storage or Storage()
        self.oauth_manager = oauth_manager or HHOAuthManager(storage=self.storage)

    def sync_me(self) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        profile = client.get_me()
        saved = self.storage.save_hh_profile(profile)
        self.oauth_manager.mark_sync_success()
        return {"entity": "me", "count": 1, "profile_id": saved["id"], "email": saved["email"]}

    def sync_resumes(self) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        payload = client.get_my_resumes()
        items = payload.get("items", payload if isinstance(payload, list) else [])
        count = self.storage.save_hh_resumes(items)
        self.oauth_manager.mark_sync_success()
        return {"entity": "resumes", "count": count}

    def sync_negotiations(self, status: str | None = None, per_page: int = 50) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        payload = client.get_negotiations(status=status, per_page=per_page)
        items = payload.get("items", payload if isinstance(payload, list) else [])
        count = self.storage.save_hh_negotiations(items)
        self.oauth_manager.mark_sync_success()
        return {"entity": "negotiations", "count": count, "status_filter": status}

    def reconcile(self) -> dict[str, Any]:
        summary = self.storage.get_hh_sync_summary()
        unmatched = max(
            0,
            summary["negotiations"] - summary["negotiations_matched_local_vacancies"],
        )
        return {
            **summary,
            "negotiations_unmatched_local_vacancies": unmatched,
            "read_only": True,
        }
