# Epic L — HH Sync Maturity

## Decision

Epic L extends the existing managed OAuth/read-only sync baseline into a more
useful operator surface without changing the safety boundary.

The implementation remains explicitly read-only:

- no hidden writes to hh.ru;
- no auto-apply;
- no message sending, editing, hiding, or negotiation mutation;
- no implicit token refresh during routine sync.

## What Epic L Adds

### 1. Pagination-aware negotiations sync

`hh-sync negotiations` no longer behaves like a first-page snapshot only.

The service now walks all available pages and stores the complete locally
available negotiation snapshot for the current token/scopes.

### 2. Read-only message snapshots

`hh-sync messages` uses the applicant-side read-only negotiation messages
endpoint and stores local message snapshots tied to negotiations.

This adds operator visibility into:

- message presence;
- unread counters on negotiations;
- local freshness and reconcile context.

### 3. Actionable reconcile

`hh-sync reconcile` now reports more than compact counts. It includes:

- matched vs unmatched negotiations relative to local vacancies;
- negotiations with unread messages;
- freshness and remote-vs-local update comparison;
- linkage to local review state where possible;
- actionable summary lines for the operator.

## Verified Boundary

Epic L deliberately does **not** add:

- sending or editing messages;
- hidden retry/remediation loops;
- automatic review mutation based on remote HH state;
- implicit token refresh inside sync commands.

## Remaining Limits

The current implementation still depends on real HH API access patterns:

- message sync is only as complete as the available applicant endpoint and token
  scopes allow;
- current sync remains explicit and operator-driven;
- downstream operator setup still needs live activation on the local machine.

## Why this was the right stopping point

Before Epic L, the HH sync layer existed but was still closer to an early
baseline than to an operational aid.

After Epic L:

- negotiations sync is materially complete;
- messages become locally observable;
- reconcile becomes operationally useful;
- the product stays inside the same safety envelope.

That makes Epic L a maturity step, not a boundary expansion.
