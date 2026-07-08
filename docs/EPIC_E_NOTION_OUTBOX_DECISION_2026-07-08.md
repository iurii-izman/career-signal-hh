# Epic E Notion / n8n Outbox Decision — 2026-07-08

## Audit summary

Before Epic E:

- `vacancy_events` and `integration_outbox` already captured integration-relevant
  local actions;
- payload snapshots were written atomically from `src/storage.py`;
- there was no delivery worker, retry loop, dry-run view, or operator-facing
  status for external sync;
- online-first search, auth, and UI flows did not depend on any external sync.

## Required payloads first

The first payload set is the one already emitted by local workflows:

- `review_status_changed`
- `review_applied`
- `review_next_action_set`
- `review_draft_saved`
- `briefing_saved`

`review_note_updated` stays local-only for now because free-form notes are not
required for the first Notion/n8n flow and would increase accidental data leak
risk.

## Decision

Implement the delivery layer as a separate CLI/service over the existing
`integration_outbox`.

Reason:

- no direct side effects bypass the outbox;
- storage remains the atomic write boundary for vacancy/review/briefing changes;
- push/retry/replay can evolve without touching auth, search, or UI flows;
- network failures degrade to local `failed` rows instead of breaking the main workflow.

## Delivery contract

`notion-sync push` sends an envelope, not the raw stored payload:

- `delivery.outbox_id`
- `delivery.delivery_key = cshh:<target>:<outbox_id>`
- `delivery.attempt`
- `delivery.replayed`
- `event = stored payload_json`

The webhook also receives:

- `X-CareerSignal-Delivery-Key`
- `X-CareerSignal-Source`
- `X-CareerSignal-Signature` when a secret is configured

This keeps downstream dedupe independent from current vacancy state and makes
retries/replays idempotent from the receiver side.

## Retry and replay behavior

- success: row becomes `sent`, `attempts += 1`;
- network or non-2xx HTTP error: row becomes `failed`, `attempts += 1`,
  `last_error` is updated;
- `retry-failed` resends failed rows only;
- `replay --outbox-id` resends a specific pending/failed outbox row with the same
  delivery key;
- replay of already `sent` rows is blocked to preserve local audit clarity;
- `dry-run` renders the exact webhook envelope and redacted headers without sending.

## Observability

Operator visibility is intentionally local-first:

- `notion-sync status` shows counts by status plus oldest pending/failed timestamps;
- the row table exposes `status`, `attempts`, `updated_at`, and `last_error`;
- webhook URLs and signatures are redacted in dry-run/status output.
