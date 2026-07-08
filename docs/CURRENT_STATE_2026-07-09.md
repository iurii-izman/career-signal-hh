# Current State — 2026-07-09

## Summary

`career-signal-hh` is now a feature-complete local operator platform for
controlled HH job search, not just a search-and-score toolkit.

As of 2026-07-09, the product baseline includes:

- authenticated online-first HH vacancy search;
- preset-driven scoring and review queue workflow;
- deterministic `briefing` and `apply-pack` artifacts;
- controlled `apply-assist` with explicit operator approval only;
- evented review storage and integration outbox;
- local cockpit/dashboard and operator control plane in UI;
- managed OAuth V2 and read-only HH sync for profile, resumes,
  negotiations, and messages;
- desktop-ready Windows app runner over the existing local UI.

The core boundary remains unchanged:

- no auto-apply;
- no hidden writes to hh.ru;
- no browser automation that submits responses;
- `review apply` only records a manual action that already happened outside
  the tool.

The official consolidated release baseline for this state is `v0.8.0`.

## Delivered Waves

The currently implemented baseline covers Tail-0 and Epics A-L:

1. Tail-0 — stabilization and online-first auth baseline
2. Epic A — candidate profile and search positioning
3. Epic B — deterministic letter engine and validator gate
4. Epic C — standalone briefing workflow
5. Epic D — evented storage and integration outbox
6. Epic E — notion/n8n delivery layer
7. Epic F — cockpit 2.0 operational dashboard
8. Epic G — managed OAuth V2 read-only sync
9. Epic H — controlled apply-assist boundary
10. Epic I — release hardening
11. Epic J — desktop packaging baseline
12. Epic K — operator control plane in UI
13. Epic L — HH sync maturity: pagination, messages, reconcile 2.0

## Verified Engineering Baseline

On 2026-07-09 the active branch baseline verifies as:

- `python -m ruff check src tests` passes;
- `python -m pytest -q` passes (`439 passed`);
- `python -m src.main doctor` is green;
- `python -m src.main health` is green;
- `python -m src.main version` reports `0.8.0`;
- DB schema version is `12`;
- backup/export freshness is healthy.

## Product Maturity Assessment

### What is solid

- The full local daily loop already exists:
  `search -> queue -> briefing -> apply-pack -> apply-assist -> manual apply`.
- Safety boundaries are still intact after the later epics.
- UI is no longer just a read surface; it is now a practical operator surface.
- HH sync is materially more useful after Epic L because negotiations pagination,
  message snapshots, and actionable reconcile are all present.

### What is still not activated in the current environment

These are not missing features, but unactivated operator capabilities:

- managed OAuth tokens are not yet stored locally;
- HH read-only sync snapshots are still empty in the current DB;
- notion/n8n webhook delivery is still disabled.

This means the code is ahead of the live operator setup.

## Main Remaining Technical Debt

### 1. Activation gap

The product ships OAuth/sync/outbox capabilities that are still not fully
activated in the current local environment.

The next pragmatic step is not another abstract epic. It is live activation:

- managed OAuth login/refresh;
- HH sync smoke on real credentials;
- real webhook delivery verification.

### 2. Baseline branch not yet merged into `main`

Epic M resolves the release/documentation drift, but the official post-L
baseline is still ahead of `main` by additive commits.

- `main` does not yet include Epics K and L;
- the audited post-L baseline currently lives on `codex/epic-l-sync-maturity`;
- there is no reverse divergence from `main`, so merge risk is organizational
  rather than architectural.

### 3. Storage concentration

`src/storage.py` remains the main concentration point for:

- persistence;
- review/event/outbox writes;
- HH sync snapshots;
- dashboard and operator aggregates.

This remains acceptable for the current single-user local app, but Phase 3
should avoid adding more large responsibilities there without deliberate
extraction.

## Recommended Phase 3 Direction

Phase 3 should start from consolidation and activation, not from speculative
feature expansion.

Recommended order:

1. merge the consolidated post-L baseline into `main`;
2. activate live OAuth/sync/outbox operator paths;
3. only then add new operator-productivity epics.

Use [docs/PHASE3_ROADMAP_2026-07-09.md](C:/Dev/career-signal-hh/docs/PHASE3_ROADMAP_2026-07-09.md)
as the next implementation baseline.
