# Epic A Handoff — 2026-07-08

## Status

Epic A is ready to hand off into Epic B.

The project is still operating in online-first mode and the following was verified on the real environment:

- `doctor` = OK
- `health` = OK
- schema version = `8`
- backup freshness = OK after fresh DB backup
- live smoke search works for the updated CRM preset
- search preset calibration is now explainable at per-term level

## What was closed after the first Epic A pass

### 1. Live preset calibration

Confirmed live smoke runs:

- `crm_systems_analyst_remote`
- `integration_analyst_remote`

Both runs completed successfully with:

- authorized HH access;
- no 429s;
- no runtime errors;
- stable smoke-mode request budgets.

### 2. Search Lab attribution fix

Closed a real analytics bug before Epic B:

- `search-lab terms` previously mixed all vacancies of a preset into every term;
- root cause: vacancies stored only `source_profile`, without `source_query`;
- result: per-term analytics looked nearly identical and was not trustworthy.

Fix implemented:

- added `source_query` to the vacancy model and DB schema;
- added schema migration `008_vacancies_source_query`;
- search flow now stores `source_query` on newly imported and refreshed vacancies;
- `touch_vacancy()` now refreshes source attribution on already-known vacancies;
- `search_term_performance()` now joins by `source_profile + source_query`.

This makes `search-lab terms` usable for real preset tuning instead of profile-wide approximations.

## Current calibration snapshot

Direct storage analytics after the fix on the live DB:

- `системный аналитик CRM` -> `10` vacancies, avg score `91.7`
- `системный аналитик интеграций` -> `9` vacancies, avg score `92.4`
- `CRM аналитик` -> `5` vacancies, avg score `71.0`
- `бизнес аналитик CRM` -> `5` vacancies, avg score `61.8`
- `business systems analyst CRM` -> `2` vacancies, avg score `69.0`
- `systems analyst CRM` -> `7` vacancies, avg score `48.3`

Interpretation:

- the strongest current Russian terms are already clear;
- `systems analyst CRM` is meaningfully weaker than the core RU queries;
- English terms should stay under observation and may need narrowing later, but this is not a blocker for Epic B.

## Operational baseline before Epic B

Fresh backup created:

- `backups/vacancies_20260708_000920.sqlite`

Useful commands:

```powershell
python -m src.main doctor
python -m src.main health
python -m src.main presets list
python -m src.main search-lab terms --preset crm_systems_analyst_remote
python -m src.main search-lab terms --preset integration_analyst_remote
```

## Decision

Do not spend more time on Epic A before moving on.

Epic A is sufficiently closed for product progress. Remaining search tuning is iterative calibration work, not a blocker for the next roadmap step.

Next implementation target:

- Epic B — Letter Engine Rewrite
