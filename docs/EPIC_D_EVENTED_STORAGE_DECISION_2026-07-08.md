# Epic D Evented Storage Decision — 2026-07-08

## Audit summary

Before this epic:

- `vacancy_reviews` stored only the latest state;
- `briefing_reports` already existed from Epic C;
- `review set`, `review apply`, `review next`, bulk review actions, and
  `apply-pack --save-review` changed durable state without a normal event trail;
- there was no integration outbox for future sync flows.

## Decision

Implement the evented layer inside `src/storage.py`, not as a second service.

Reason:

- current flows already converge on storage writes;
- this keeps review/apply/briefing updates atomic with event/outbox persistence;
- UI, auth, and search code stay unchanged.

## Event model

Events are append-only rows in `vacancy_events`.

Current event types:

- `review_status_changed`
- `review_applied`
- `review_note_updated`
- `review_next_action_set`
- `review_draft_saved`
- `review_draft_cleared`
- `briefing_saved`

The event payload is intentionally small. It stores the action-specific delta,
while the outbox snapshot carries the current vacancy/review/briefing context
needed by future sync workers.

## Outbox model

`integration_outbox` is generic and local-only for now.

Current decisions:

- target is `external_sync`;
- only integration-relevant events are enqueued there;
- no direct external side effects are executed in this epic.

This keeps the current online-first workflow intact while preparing a safe
handoff point for Epic E sync work.
