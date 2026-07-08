# Epic G Decision — 2026-07-08

## What was implemented

Epic G is closed as a read-only OAuth V2 slice:

- managed OAuth lifecycle via `oauth status/login/refresh/revoke-local`;
- secure local token storage through OS keyring;
- SQLite metadata and sync tables:
  - `oauth_tokens_meta`
  - `hh_profiles`
  - `hh_resumes`
  - `hh_negotiations`
- read-only sync commands:
  - `hh-sync me`
  - `hh-sync resumes`
  - `hh-sync negotiations`
  - `hh-sync reconcile`

## Key design decisions

### 1. Managed OAuth is additive, not a replacement

Existing online-first flows stay unchanged:

- `search`, `autopilot`, `export`, UI health/auth checks still rely on current `HHClient`;
- manual `HH_USER_ACCESS_TOKEN` remains a supported fallback;
- managed OAuth does not rewrite `.env` and does not silently migrate manual tokens.

Reason:

This avoids regressions in the already working app-token and manual-token paths.

### 2. Tokens are not stored in SQLite or `.env`

Implemented storage split:

- access token and refresh token -> OS keyring only;
- token metadata -> SQLite only;
- sync payloads -> SQLite only.

Reason:

This is the minimal practical model that gives safe lifecycle management without introducing custom crypto or hidden file formats.

### 3. Read-only scope is enforced at the command surface

This epic intentionally stops at:

- profile sync;
- resumes sync;
- negotiations sync;
- local reconcile against already stored HH vacancy ids.

Not included:

- sending messages;
- resume editing;
- response submission;
- any auto-apply behavior.

Reason:

The product constraint is explicit: read-only first, no silent writes.

### 4. No implicit token refresh during sync

If a managed access token is expired, sync stops with an explicit instruction to run:

```powershell
python -m src.main oauth refresh
```

Reason:

This keeps OAuth state transitions observable for the operator and avoids hidden local state changes during routine sync runs.

## Operator notes

Required env for managed OAuth:

```dotenv
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=
HH_OAUTH_STORAGE=keyring
```

Recommended flow:

```powershell
python -m src.main oauth status
python -m src.main oauth login --open-browser
python -m src.main oauth login --code <authorization_code>
python -m src.main hh-sync me
python -m src.main hh-sync resumes
python -m src.main hh-sync negotiations --status active
python -m src.main hh-sync reconcile
```

Fallback remains valid:

```dotenv
HH_AUTH_MODE=user_oauth
HH_USER_ACCESS_TOKEN=...
```

## Known limits after Epic G

- sync currently covers only the first-page `/negotiations` response exposed by the command parameters;
- there is no message sync yet;
- there is no automatic refresh-before-sync;
- local UI was intentionally not expanded with OAuth controls in this epic to avoid unnecessary auth/UI churn.
