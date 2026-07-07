# Tail-0 Stabilization — 2026-07-07

## Scope

Short stabilization batch before the next implementation wave:

- align docs with the real repo state;
- freeze a repeatable online-first baseline;
- separate blocking tails from non-blocking tails;
- avoid new feature work.

## Audit Summary

Repository audit confirmed:

- manual `user_oauth` bearer token mode already works in `src/hh_client.py`;
- local web UI already exists in `src/commands/ui.py` and `src/web/*`;
- live online mode is already the baseline, not a hypothetical future mode;
- the main stale assumptions were in `docs/career_signal_hh_tz_final_v1_1.md`, not in the code.

README already reflected live HH access, but it did not yet freeze one explicit
Tail-0 command baseline for the daily online-first scenario.

## Roadmap Alignment

Current roadmap direction in `docs/ROADMAP_DECISION_2026-07-07.md` is consistent
with the codebase:

- Tail-0 = short stabilization;
- next work should proceed epic by epic;
- UI is no longer a backlog placeholder;
- managed OAuth remains a future epic, but manual token mode is current reality.

No roadmap rewrite is needed. Only stale assumptions in the large technical spec
needed correction.

## Baseline Commands

Current repeatable online-first baseline:

```powershell
Copy-Item .env.example .env
```

```dotenv
HH_AUTH_MODE=application_token
HH_APP_ACCESS_TOKEN=...
HH_USER_AGENT=CareerSignalHH/0.1 (real-email-or-url)
```

Alternative manual OAuth baseline:

```dotenv
HH_AUTH_MODE=user_oauth
HH_USER_ACCESS_TOKEN=...
```

Checks and workflow:

```powershell
python -m src.main doctor
python -m src.main auth-check
python -m src.main health
python -m src.main search --mode smoke
python -m src.main top
python -m src.main export
python -m src.main ui
```

## Tail Classification

### Blocking

1. Stale technical spec claimed manual `user_oauth` was not implemented.
2. Stale technical spec treated local web UI as a future/P3 item.
3. Baseline online-first commands were not frozen in one explicit place.

Status: closed in this batch.

### Non-blocking

1. Managed OAuth lifecycle is still absent: `login` / `refresh` / `revoke-local` / safe storage.
2. No read-only sync of real HH responses/applications yet.
3. Desktop packaging is still future work: wrapper/installer, not core UI.
4. Remaining product epics still require candidate/profile/template/domain work, but none of that blocks the current online-first baseline.

## Decisions Captured

- Do not treat manual `user_oauth` as "OAuth V2 done". It is only a manual
  bearer-token mode for authorized calls.
- Keep online-first as the main operating mode.
- Treat the current local web UI as shipped baseline functionality.
- Keep managed OAuth and sync as additive epics so the existing search/export
  flow stays stable.
