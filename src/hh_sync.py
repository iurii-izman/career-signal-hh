from __future__ import annotations

from collections.abc import Callable
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
        return {
            "entity": "me",
            "count": 1,
            "profile_id": saved["id"],
            "email": saved["email"],
            "read_only": True,
        }

    def sync_resumes(self) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        payload = client.get_my_resumes()
        items = payload.get("items", payload if isinstance(payload, list) else [])
        count = self.storage.save_hh_resumes(items)
        self.oauth_manager.mark_sync_success()
        return {"entity": "resumes", "count": count, "read_only": True}

    def sync_negotiations(self, status: str | None = None, per_page: int = 50) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        items, meta = self._collect_paginated_items(
            lambda page: client.get_negotiations(status=status, per_page=per_page, page=page),
            per_page=per_page,
        )
        count = self.storage.save_hh_negotiations(items)
        self.oauth_manager.mark_sync_success()
        return {
            "entity": "negotiations",
            "count": count,
            "status_filter": status,
            "pages_fetched": meta["pages_fetched"],
            "found": meta["found"],
            "read_only": True,
        }

    def sync_messages(
        self,
        negotiation_id: str | None = None,
        *,
        status: str | None = None,
        per_page: int = 50,
        messages_per_page: int = 50,
    ) -> dict[str, Any]:
        client = self.oauth_manager.get_sync_client()
        if negotiation_id:
            negotiations = [{"id": negotiation_id}]
            negotiations_meta = {"pages_fetched": 0, "found": 1}
        else:
            negotiations, negotiations_meta = self._collect_paginated_items(
                lambda page: client.get_negotiations(status=status, per_page=per_page, page=page),
                per_page=per_page,
            )
            self.storage.save_hh_negotiations(negotiations)

        total_messages = 0
        pages_fetched = 0
        synced_negotiations = 0
        failed_negotiations: list[dict[str, str]] = []
        for negotiation in negotiations:
            current_id = str(negotiation.get("id") or "").strip()
            if not current_id:
                continue
            try:
                items, meta = self._collect_paginated_items(
                    lambda page, nid=current_id: client.get_negotiation_messages(
                        nid,
                        per_page=messages_per_page,
                        page=page,
                    ),
                    per_page=messages_per_page,
                )
                total_messages += self.storage.save_hh_negotiation_messages(current_id, items)
                pages_fetched += meta["pages_fetched"]
                synced_negotiations += 1
            except Exception as exc:
                failed_negotiations.append({"negotiation_id": current_id, "error": str(exc)})

        if synced_negotiations:
            self.oauth_manager.mark_sync_success()
        return {
            "entity": "messages",
            "negotiation_id": negotiation_id,
            "status_filter": status,
            "count": total_messages,
            "negotiations_considered": len(negotiations),
            "negotiations_synced": synced_negotiations,
            "negotiation_pages_fetched": negotiations_meta["pages_fetched"],
            "message_pages_fetched": pages_fetched,
            "failed_negotiations": failed_negotiations,
            "read_only": True,
        }

    def reconcile(self) -> dict[str, Any]:
        summary = self.storage.get_hh_sync_summary()
        actionable = []
        if summary["negotiations_unmatched_local_vacancies"]:
            actionable.append(
                f"{summary['negotiations_unmatched_local_vacancies']} negotiation(s) are not matched to local vacancies"
            )
        if summary["matched_without_review"]:
            actionable.append(
                f"{summary['matched_without_review']} matched negotiation(s) have no local review yet"
            )
        if summary["matched_remote_newer_than_review"]:
            actionable.append(
                f"{summary['matched_remote_newer_than_review']} matched negotiation(s) changed on HH after the local review"
            )
        if summary["negotiations_with_unread_messages"]:
            actionable.append(
                f"{summary['negotiations_with_unread_messages']} negotiation(s) still show unread HH messages"
            )
        return {
            **summary,
            "actionable_summary": actionable
            or ["HH sync looks aligned: no unmatched negotiations or stale matched reviews detected."],
            "read_only": True,
        }

    @staticmethod
    def _collect_paginated_items(
        fetch_page: Callable[[int], dict[str, Any]],
        *,
        per_page: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int | None]]:
        page = 0
        pages_fetched = 0
        items: list[dict[str, Any]] = []
        found: int | None = None
        while True:
            payload = fetch_page(page)
            page_items = payload.get("items", payload if isinstance(payload, list) else [])
            if not isinstance(page_items, list):
                page_items = []
            items.extend(page_items)
            pages_fetched += 1
            if found is None:
                found = _as_int(payload.get("found"))

            total_pages = _as_int(payload.get("pages"))
            if total_pages is not None:
                if page + 1 >= total_pages:
                    break
            elif len(page_items) < per_page or not page_items:
                break

            page += 1
            if page >= 1000:
                break

        return items, {"pages_fetched": pages_fetched, "found": found}


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
