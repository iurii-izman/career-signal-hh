# Roadmap Decision — 2026-07-07

## Decision

Do not stop for a long "perfect tails" phase.

The project is already healthy enough to continue feature development in online-first mode. The right move is:

1. Close a short stabilization batch.
2. Re-baseline the roadmap against the real repo state.
3. Execute large implementation epics in sequence.

## Why this decision

The current technical spec in [career_signal_hh_tz_final_v1_1.md](C:/Dev/career-signal-hh/docs/career_signal_hh_tz_final_v1_1.md) is directionally strong, but several assumptions are stale:

- It says `user_oauth` is not implemented and should wait for V2.
- It treats local UI as a late-stage item.
- It lists `Local web UI` in P3 backlog.
- It is still framed around uncertainty of live HH access.

The repository state is already ahead of that:

- `src/hh_client.py` supports `application_token` and `user_oauth` manual token mode.
- `src/commands/ui.py` and `src/web/*` provide the local web UI now.
- [DESKTOP_UI_PLAN.md](C:/Dev/career-signal-hh/docs/DESKTOP_UI_PLAN.md) marks Phase 1 complete.
- Live auth and smoke search are already operational, so the main product mode is no longer "offline until access works".

## What are still tails

These are worth closing first, but they are not strategic blockers:

- Refresh stale roadmap assumptions in docs.
- Refresh the README note that still reflects the old 403-blocked period.
- Make a clean baseline snapshot before the next big implementation wave.
- Keep an eye on the remaining test warning, but do not block roadmap work on it.

## Recommended roadmap

### Tail-0: Stabilization

Scope:

- align docs with actual repo state;
- update status notes around live HH access;
- capture a clean baseline of working online mode.

Exit criteria:

- roadmap no longer refers to missing UI or missing manual OAuth token mode;
- baseline commands are documented and repeatable.

### Epic A: Candidate Profile + Search Positioning

Scope:

- refresh `config/candidate.yaml`;
- refresh presets for CRM, Bitrix24, integration, AI automation, no-code;
- calibrate search relevance on live vacancies.

Exit criteria:

- improved preset recall and cleaner review queue;
- explicit target role matrix and inclusion/exclusion logic.

### Epic B: Letter Engine Rewrite

Scope:

- rewrite application letter templates;
- add validator-driven quality gates;
- tighten `apply-pack` decision logic.

Exit criteria:

- every generated draft passes deterministic validator checks;
- weak or generic drafts are rejected before export.

### Epic C: Vacancy Briefing Core

Scope:

- implement standalone `briefing` command;
- generate the required 7-block vacancy analysis;
- connect save/export/review flows.

Exit criteria:

- briefing works both for a single vacancy and for top-ranked queue items;
- review flow can persist generated briefing artifacts.

### Epic D: Evented Storage Layer

Scope:

- keep `briefing_reports` as the generated-artifact store added in Epic C;
- add `vacancy_events`;
- add `integration_outbox`;
- connect review / apply-pack / briefing actions to event emission.

Exit criteria:

- important actions emit structured events;
- downstream sync does not depend on scraping current table state.

### Epic E: Notion / n8n Outbox

Scope:

- webhook/outbox payloads;
- retry/status mechanics;
- safe dry-run and replay support.

Exit criteria:

- external sync is auditable and idempotent;
- no direct side effects bypass the outbox.

### Epic F: Cockpit 2.0

Scope:

- use events, briefings, and review state in the cockpit;
- add pipeline visibility, risk buckets, preset performance, and action shortcuts.

Exit criteria:

- cockpit becomes the operational control surface for daily work;
- queue health and funnel state are visible without manual SQL inspection.

### Epic G: OAuth V2 Read-Only Sync

Scope:

- browser login, refresh, and local secure storage;
- metadata tracking for tokens;
- read-only sync for resumes, negotiations, and responses.

Exit criteria:

- OAuth is additive, safe, and observable;
- manual dual-token mode stays intact as fallback.

### Epic H: Controlled Apply Assist

Scope:

- guarded browser handoff;
- mandatory briefing and validator gates;
- no silent auto-apply behavior.

Exit criteria:

- every assisted apply action is intentional, reviewable, and reversible where possible.

## Priority order

Recommended execution order:

1. Tail-0
2. Epic A
3. Epic B
4. Epic C
5. Epic D
6. Epic E
7. Epic F
8. Epic G
9. Epic H

## What should not stay in backlog as-is

These items should be reclassified in future planning:

- "Local web UI" is no longer a future feature. The next UI milestone is packaging: Tauri wrapper and installer.
- OAuth should be split into:
  - V1 manual token support: already present;
  - V2 managed login/refresh/read-only sync: still future.
- The roadmap should be online-first, not framed around assumed API lockout.

## Management rule for the next implementation wave

Do not try to perfect everything before moving.

Use this rule instead:

- if an issue blocks safe daily online operation, fix it immediately;
- if it is documentation drift or a non-blocking warning, batch it into Tail-0;
- otherwise continue with the next epic.
