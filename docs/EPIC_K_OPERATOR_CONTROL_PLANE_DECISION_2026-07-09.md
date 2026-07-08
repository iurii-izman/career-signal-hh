# Epic K — Operator Control Plane In UI

## Decision

Epic K moves key operator control-plane visibility and explicit safe actions
from CLI-only usage into the local web UI as an additive layer.

The implementation keeps the existing CLI as baseline and does not widen the
product boundary:

- no auto-apply;
- no hidden writes to hh.ru;
- no implicit background approval;
- all operator actions remain explicit.

## UI Surface Added

Dashboard now exposes:

- compact operator control-plane summary;
- apply-assist readiness panel;
- recent assist activity;
- recent outbox activity;
- explicit operator shortcuts for OAuth refresh and outbox delivery actions.

Settings now exposes:

- HH OAuth status and refresh action;
- HH read-only sync summary and explicit sync buttons;
- outbox delivery status, dry-run, push-pending, retry-failed;
- apply-assist readiness table with preview and explicit approval handoff;
- recent assist/outbox operator activity.

## Backend Shape

The UI reuses existing durable/local sources where possible:

- `Storage` for OAuth metadata, HH sync summary, outbox, events, and queue data;
- `app_service.get_operator_state()` as the aggregation layer;
- `HHSyncService` for read-only sync actions;
- `NotionSyncService` for outbox delivery actions;
- `apply_assist_service` for readiness evaluation and explicit approval.

New API surface is intentionally narrow and action-oriented:

- `POST /api/operator/oauth/refresh`
- `POST /api/operator/hh-sync`
- `POST /api/operator/outbox`
- `GET /api/operator/apply-assist/{vacancy_id}`
- `POST /api/operator/apply-assist/{vacancy_id}/approve`

No extra read endpoints were added for dashboard/settings hydration; both pages
reuse existing `/api/dashboard` and `/api/settings` payloads with additive
`operator` state.

## Operator Tasks Now Available Without CLI

- inspect managed OAuth readiness and last sync/refresh state;
- refresh managed OAuth access token;
- inspect local HH sync totals and reconcile state;
- run explicit HH read-only sync for profile, resumes, and negotiations;
- inspect outbox readiness, pending/failed/sent counts, and recent deliveries;
- dry-run pending outbox payloads;
- push pending outbox entries;
- retry failed outbox deliveries;
- inspect apply-assist readiness candidates;
- preview apply-assist result for a vacancy;
- explicitly approve apply-assist handoff without performing any auto-apply;
- monitor recent assist/outbox operator activity from the UI.
