# Changelog

## Unreleased
- documentation baseline refreshed for post-L state;
- added `docs/CURRENT_STATE_2026-07-09.md`;
- added `docs/PHASE3_ROADMAP_2026-07-09.md`;
- added `docs/EPIC_L_SYNC_MATURITY_DECISION_2026-07-09.md`;
- aligned README and release checklist with Phase 2 complete / Phase 3 ready baseline.

## v0.7.0 (2026-07-08)
- Tail-0 stabilization and online-first auth baseline
- candidate/search recalibration for CRM, Bitrix24, integration, AI automation, and no-code roles
- deterministic letter engine with validator-driven apply-pack gate
- standalone briefing workflow and saved briefing artifacts
- evented storage layer with `vacancy_events` and `integration_outbox`
- notion/n8n delivery layer with dry-run, retry, replay, and sent-row resend guard
- cockpit 2.0 with pipeline, queue health, risk buckets, preset performance, recent activity, and action shortcuts
- managed OAuth V2 with keyring-backed token lifecycle and read-only HH sync for profile, resumes, and negotiations
- controlled `apply-assist` command with explicit operator approval gate
- assist guard rails bound to briefing, review draft, validator, score/confidence/noise
- assist audit trail in `vacancy_events` with handoff events mirrored to `integration_outbox`
- wizard apply updated to point to controlled assist instead of ambiguous draft-only finish
- release baseline docs:
  `docs/CURRENT_STATE_2026-07-08.md`,
  `docs/PHASE2_ROADMAP_2026-07-08.md`
- release hardening for versioning, checklist, and baseline documentation

## v0.6.0 (2026-06-16)
- Universal search presets with field-aware scoring v2
- explainable score_details with decision labels
- review queue and bulk actions
- apply pack generation (MD/HTML)
- letter engine rewrite with deterministic apply-pack validator gate
- safe daily autopilot workflow
- market analytics (skills, employers, salary, funnel)
- preset management CLI (create, clone, edit, validate)
- quality gates: ruff, pytest, smoke scripts, version command

## v0.5.0 (2026-06-16)
- Universal search presets (config/search_presets.yaml)
- scoring v2 with include/exclude/boost/penalties
- adhoc search with --include/--exclude
- presets list/show commands
- preset-based export/review filtering

## v0.4.0 (2026-06-16)
- Safe search modes (smoke, normal, deep)
- request budget and rate limiting
- smart detail fetching
- run estimate and dry-run improvements
- DB hygiene commands (info, backup, purge-samples)
- sample/prod data separation

## v0.3.0
- Manual vacancy review workflow
- review list/set/note/apply/next commands
- review statuses in exports

## v0.2.0
- Doctor, profiles, sample-export commands
- HTML/CSV/JSONL export

## v0.1.0
- Initial MVP
- HH API client with application token auth
- SQLite storage
- search command with configurable profiles
- rule-based scoring
