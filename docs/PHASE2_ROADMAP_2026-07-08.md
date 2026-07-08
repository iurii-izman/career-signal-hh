# Phase 2 Roadmap — 2026-07-08

## Decision

Do not continue with another long tail-cleanup loop.

Phase 1 is complete enough to shift from "feature assembly" to
"productization + operator maturity".

The next wave should focus on:

1. release hardening;
2. desktop/app delivery;
3. UI control-plane maturity;
4. read-only sync maturity.

## Why this is the right next move

After Tail-0 and Epics A-H, the core daily product loop already exists:

```text
search -> score -> queue -> briefing -> apply-pack -> apply-assist
-> manual apply -> review tracking -> outbox/sync
```

The biggest remaining gaps are no longer core domain features. They are:

- release discipline;
- easier packaging and operator entrypoint;
- UI access to already shipped backend capabilities;
- sync completeness and observability.

## What is explicitly not next

The following are intentionally out of scope for Phase 2:

- auto-apply;
- hidden browser submission flows;
- silent writes to hh.ru;
- hidden token refresh inside routine sync;
- broad multi-market expansion before productization;
- major architecture rewrites for their own sake.

## Recommended Epic Order

1. Epic I — Release Hardening & Baseline Freeze
2. Epic J — Desktop Packaging & Local App Delivery
3. Epic K — Operator Control Plane in UI
4. Epic L — Sync Maturity: Pagination, Messages, Reconcile 2.0

## Epic I — Release Hardening & Baseline Freeze

### Goal

Turn the current state into a release-ready baseline instead of an informal
"main branch snapshot".

### Scope

- align version values across package, CLI, and UI;
- convert the large `Unreleased` bucket in `CHANGELOG.md` into a structured release block;
- refresh `RELEASE_CHECKLIST.md`;
- create one concise baseline document for the post-A-H state;
- verify `doctor`, `health`, `version`, `ruff`, and `pytest` against the new baseline.

### Exit criteria

- versioning is internally consistent;
- changelog is release-readable;
- release checklist matches real workflows;
- one concise baseline document exists and is referenced from README.

### Risks

- low risk;
- mostly documentation/release discipline, not product behavior.

## Epic J — Desktop Packaging & Local App Delivery

### Goal

Make the local UI feel like an installable tool instead of a developer-run
localhost app.

### Scope

- strengthen `ui` startup story for app mode;
- add `--no-browser` or equivalent app-runner path if needed;
- document Windows-first app mode and packaging;
- prepare pragmatic wrapper/launcher baseline;
- keep CLI and local-only safety model unchanged.

### Exit criteria

- user can launch the app in a predictable desktop-like flow;
- no fragile assumptions about interactive dev shell remain;
- packaging boundary is documented even if installer work stays partial.

### Risks

- medium risk;
- mostly runtime/path/process-management complexity.

## Epic K — Operator Control Plane in UI

### Goal

Expose already shipped operator capabilities in the local UI so daily operation
does not depend on CLI for routine checks.

### Scope

- show OAuth status and sync freshness;
- show outbox status and delivery backlog;
- show apply-assist readiness / assist-related activity;
- surface safe read-only or explicit operator actions through existing dashboard/settings views;
- keep CLI as baseline and reuse existing durable sources.

### Exit criteria

- UI covers most daily operator checks;
- no new unsafe side effects are introduced;
- UI and CLI read the same durable state.

### Risks

- medium risk;
- danger is UI sprawl, not core logic.

## Epic L — Sync Maturity: Pagination, Messages, Reconcile 2.0

### Goal

Upgrade HH read-only sync from a narrow baseline into a mature operator aid.

### Scope

- pagination-aware negotiations sync;
- message sync only if HH API/scopes allow it safely;
- richer reconcile summary;
- improved local visibility into freshness, matched/unmatched items, and sync gaps;
- optional new snapshot tables only when justified by real sync needs.

### Exit criteria

- negotiations sync is no longer effectively first-page oriented;
- reconcile is actionable rather than only count-based;
- sync limits are explicit and observable.

### Risks

- medium to high risk;
- external API details and pagination edge cases dominate this epic.

## Management Rules For Phase 2

- Keep the no-auto-apply boundary absolute.
- Prefer additive changes over rewrites.
- Do not hide state transitions from the operator.
- If a feature makes the product less observable, it is probably the wrong feature.
- Avoid pushing major new responsibilities into `src/storage.py` unless there is
  a strong pragmatic reason.

## Recommended Execution Style

- Epic I can be done in the current thread.
- Epics J-L are better executed one epic per fresh thread.
- Each epic should finish with:
  - updated docs;
  - green `ruff`;
  - green `pytest`;
  - clean git tree;
  - commit and push.
