# Epic C Briefing Decision — 2026-07-08

## Scope shipped

Epic C is implemented as a pragmatic layer on top of existing `vacancies`,
`scores`, `score_details`, and `vacancy_reviews`.

Delivered:

- standalone CLI command `briefing`;
- single vacancy mode and top-N queue mode;
- stable 7-block briefing structure;
- export to `md`, `html`, `json`;
- persistence in `briefing_reports`;
- wiring into `wizard apply`;
- links surfaced in the main HTML export when briefing/apply-pack artifacts exist.

## Deliberate decisions

### 1. `briefing` reuses current scoring data instead of creating a second analyzer

Reason:

- `score_details` already contains the core evidence needed for a manual decision:
  matched keywords, excluded keywords, category scores, risk flags, confidence,
  noise, and decision logic.
- duplicating that logic inside a separate vacancy-analysis engine would create
  immediate drift with `review` and `apply-pack`.

### 2. Persistence uses `briefing_reports`, not `vacancy_reviews`

Reason:

- `vacancy_reviews` is current-state review metadata;
- briefing is a generated artifact with structured payload and markdown;
- storing it separately keeps review state compact and makes future event/outbox
  work cleaner.

### 3. Event model is intentionally deferred

`vacancy_events` is not added in this epic.

Reason:

- event sourcing is part of Epic D and is not required to deliver a useful,
  stable briefing workflow now;
- `briefing_reports` is sufficient for save/export/review integration in the
  current architecture.

## Workflow now

```powershell
python -m src.main review next-best
python -m src.main briefing --top 5 --decision strong_match --save-review
python -m src.main apply-pack --top 5 --decision strong_match
python -m src.main review apply VACANCY_ID --date today
```

## Known limits

- briefing links in HTML export depend on generated artifact files already
  existing under `exports/briefings` or `exports/apply_packs`;
- web UI does not render briefing natively yet;
- there is no event or outbox emission from briefing creation in this epic.
