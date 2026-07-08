# Current State — 2026-07-08

## Summary

`career-signal-hh` is no longer just a search MVP.

As of 2026-07-08, it is a local single-user operating system for controlled HH
job search with:

- authenticated online-first vacancy search;
- preset-based scoring and queue workflow;
- standalone briefing and deterministic apply-pack generation;
- evented review/audit trail and integration outbox;
- local cockpit/dashboard UI;
- managed OAuth V2 read-only sync for HH user data;
- controlled apply-assist with explicit operator approval.

Core product boundary remains unchanged:

- no auto-apply;
- no hidden writes to hh.ru;
- no browser automation that submits applications;
- `review apply` always records a manual action that already happened outside
  the tool.

## Delivered Phases

The stabilization wave and Epics A-H are complete:

1. Tail-0 — stabilization and online-first baseline
2. Epic A — candidate profile and search positioning
3. Epic B — deterministic letter engine and validator gate
4. Epic C — standalone briefing workflow
5. Epic D — evented storage and integration outbox
6. Epic E — notion/n8n delivery layer
7. Epic F — cockpit 2.0 operational dashboard
8. Epic G — managed OAuth V2 read-only sync
9. Epic H — controlled apply-assist boundary

## Operational Baseline

At the time of this snapshot:

- `python -m ruff check src tests` passes;
- `python -m pytest -q` passes;
- `python -m src.main doctor` is green;
- `python -m src.main health` is green;
- DB schema is up to date;
- backup/export baseline is healthy.

## What Is Done

### Search and scoring

- safe search modes with request budget and 429 handling;
- live authenticated search via app token;
- manual `user_oauth` token mode still supported;
- calibrated presets for CRM / Bitrix / integration / AI automation / no-code;
- scoring v2 with confidence/noise/decision model.

### Decision workflow

- review queue with statuses, notes, applied date, next action;
- standalone `briefing`;
- deterministic `apply-pack` with validator gate;
- `apply-assist` as explicit operator handoff, not auto-apply.

### Observability and state

- `vacancy_events` for important review/briefing/apply-assist actions;
- `integration_outbox` for external sync delivery;
- cockpit metrics from local durable state;
- health/doctor/version/reports/checklists.

### HH user data sync

- managed OAuth V2 lifecycle:
  - `oauth status`
  - `oauth login`
  - `oauth refresh`
  - `oauth revoke-local`
- read-only sync:
  - `hh-sync me`
  - `hh-sync resumes`
  - `hh-sync negotiations`
  - `hh-sync reconcile`

## Known Limits

These are deliberate current boundaries, not accidental bugs:

- no response submission through API or browser automation;
- no bulk assist / bulk apply;
- no hidden token refresh during HH sync;
- no message sync yet;
- negotiations sync still needs pagination maturity;
- local web UI exists, but packaging/installer is still future work.

## Main Remaining Technical Debt

### 1. Release discipline

The version baseline is now aligned at `0.7.0`, but future release discipline
still needs to stay explicit:

- release blocks should not accumulate indefinitely in `Unreleased`;
- package/UI/CLI version surfaces must stay in sync;
- release checklist should be treated as mandatory, not advisory.

### 2. Documentation hierarchy

The authoritative story is currently spread across:

- `README.md`
- `docs/ROADMAP_DECISION_2026-07-07.md`
- epic decision docs
- `docs/career_signal_hh_tz_final_v1_1.md`

Phase 2 should treat this file plus the new Phase 2 roadmap as the concise
baseline and treat the large technical spec as reference material.

### 3. Storage concentration

`src/storage.py` now acts as:

- persistence layer;
- review/event layer;
- outbox writer;
- HH sync snapshot store;
- cockpit aggregation layer.

This is acceptable for a local single-user app, but future large epics should
avoid piling more responsibilities into the same file.

## Recommended Next Phase

Use `docs/PHASE2_ROADMAP_2026-07-08.md` as the implementation roadmap after
Epics A-H.
