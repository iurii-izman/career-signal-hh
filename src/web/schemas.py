"""Web schemas — Pydantic models for API request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    """Standard API response envelope."""

    ok: bool
    message: str = ""
    data: Any = None


class ActionRequest(BaseModel):
    """Generic action request with optional parameters."""

    mode: str = "normal"
    preset: str | None = None
    force: bool = False


class ReviewStatusRequest(BaseModel):
    """Request to update review status."""

    status: str


class NoteRequest(BaseModel):
    """Request to save a note."""

    note: str


class AppliedRequest(BaseModel):
    """Request to mark vacancy as applied."""

    date: str = "today"


class NextActionRequest(BaseModel):
    """Request to set next action."""

    action: str
    date: str = "today"


class BulkActionRequest(BaseModel):
    """Request for bulk review actions."""

    max_score: int | None = None
    min_score: int | None = None
    decision: str | None = None
    force: bool = False
    confirm: bool = True


class OperatorHHSyncRequest(BaseModel):
    """Explicit HH read-only sync request."""

    entity: str = "reconcile"
    status: str | None = None
    per_page: int = 50


class OperatorOutboxRequest(BaseModel):
    """Explicit outbox operator action."""

    action: str = "push_pending"
    outbox_id: int | None = None
    limit: int = 10
    dry_run: bool = False


class OperatorApplyAssistApprovalRequest(BaseModel):
    """Explicit apply-assist approval request."""

    open_browser: bool = False
