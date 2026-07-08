# Epic F Cockpit 2.0 Decision — 2026-07-08

## Audit summary

Before this epic:

- the local web dashboard showed only top-level counts, health, reports, and jobs;
- `cockpit export` was useful as a static daily page, but it mostly summarized raw queue rows;
- evented storage and `briefing_reports` already existed, but cockpit surfaces barely used them;
- operational questions still required SQL or manual navigation:
  "what is blocked in the queue?", "which strong matches still need briefing?",
  "which presets convert into applied/interview/offer?", "is sync backlog healthy?".

## Decision

Cockpit 2.0 is implemented as an additive operational layer on top of `src/storage.py`
and exposed through the existing dashboard API plus the existing `cockpit export`.

Reason:

- this keeps auth, search, queue UI, and current online-first flows unchanged;
- `vacancy_events`, `briefing_reports`, and `integration_outbox` stay the single durable sources;
- web dashboard and standalone cockpit now read the same operational model instead
  of drifting into separate interpretations.

## Shipped operational views

- pipeline counters: sourced, scored, shortlisted, briefed, drafted, applied, interview, offer;
- queue health: pending new, strong new, missing briefing, interesting without draft,
  follow-up due, risky queue, outbox pending, outbox failed;
- risk buckets from `risk_flags_json` and `quality_flags_json`;
- preset performance with briefing/applied/offer visibility;
- attention context for strong matches without briefing and due follow-ups;
- recent activity stream from `vacancy_events`;
- briefing/outbox summary for integration readiness.

## Deliberate decisions

### 1. No new backend service layer

Operational queries live in `Storage.get_operational_metrics()`.

Reason:

- the data is already local and relational;
- the new dashboard needs aggregation, not orchestration;
- adding a second analytics layer would create avoidable drift for a small codebase.

### 2. `api/dashboard` was enriched instead of adding many small endpoints

Reason:

- the current dashboard loads one payload already;
- the UI remains simple and fast;
- the epic needed observability, not API surface expansion for its own sake.

### 3. Cockpit focuses on actionability, not decorative redesign

Reason:

- the goal is daily funnel operation;
- high-signal panels beat a visual rewrite;
- the queue page remains the detailed work surface, cockpit becomes the operator overview.

## Known limits

- risk buckets are pragmatic text-based aggregations over stored flags, not a separate taxonomy engine;
- action context intentionally highlights only the most immediate blocking items;
- standalone `cockpit.html` remains static and read-only, while the web dashboard is the interactive surface.
