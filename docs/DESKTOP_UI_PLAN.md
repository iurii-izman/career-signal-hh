# Desktop UI Plan — CareerSignal HH

## Goal

Epic J upgrades the existing local web UI into a desktop-ready local app experience
without rewriting the UI, without breaking CLI workflows, and without adding unsafe
browser automation.

The baseline remains:

- single-user;
- local-first;
- online-first for HH search/auth/review/apply-assist flows;
- no auto-apply;
- no non-localhost bind unless explicitly allowed.

## Launch Story Audit

Before Epic J the UI launch path had three main gaps:

1. `src/commands/ui.py`
   - assumed repo-root `cwd` for `data/`, `.env`, and status files;
   - mixed server launch with optional browser open, but had no explicit app-runner path;
   - had no lifecycle state beyond a one-shot `ui_status.json` write.

2. `scripts/start_ui.*`
   - depended on the caller's shell/session state;
   - assumed ad-hoc venv activation;
   - were fine for developer use, but weak as a stable desktop entrypoint.

3. Packaged/app mode story
   - `--app-mode` only printed hints;
   - startup/shutdown of the backend and browser window were not coordinated;
   - there was no Windows-first wrapper that behaved like a local app.

## Done in Epic J

### 1. Safe app-runner baseline

`python -m src.main ui` now has a safer runtime contract:

- resolves the project root from the code location, not from the current shell;
- changes into that root before starting FastAPI so relative `data/`, `config/`,
  `exports/`, and `.env` behavior stays predictable;
- supports `--no-browser` for wrapper-driven or app-mode launches;
- writes lifecycle status to `data/ui_status.json` with `starting`, `running`,
  `stopped`, or `failed`;
- keeps localhost-only bind as the default boundary.

### 2. Windows-first local app wrapper

New wrapper flow:

- `scripts/start_app.ps1`
- `scripts/start_app.cmd`

What it does:

1. resolves repo root and Python interpreter without relying on an activated shell;
2. starts `python -m src.main ui --no-browser` in the background;
3. waits for local readiness via `http://127.0.0.1:<port>/api/health`;
4. opens Edge or Chrome in `--app=<url>` mode;
5. stops the backend process when the app window exits.

This is the current Windows-first "desktop-ready" baseline.

### 3. Launcher hardening

- `scripts/start_ui.ps1` and `scripts/start_ui.sh` now resolve paths relative to the
  script location instead of the caller's shell state.
- `scripts/Create-CareerSignalShortcut.ps1` now points to the app wrapper by default.

### 4. Tests and safeguards

Coverage now explicitly checks:

- app wrapper files exist;
- launcher scripts do not embed tokens;
- `--no-browser` is exposed in CLI help;
- UI status file includes normalized runtime metadata;
- wildcard host URLs normalize to a browser-safe localhost URL.

## How To Run

### Browser UI

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_ui.ps1
```

Or directly:

```powershell
python -m src.main ui --open-browser
```

### App mode on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1
```

This opens a local app window backed by the existing FastAPI UI.

### Manual wrapper-style run

```powershell
python -m src.main ui --no-browser
start msedge --app=http://127.0.0.1:8765
```

## Security Boundaries

- UI binds only to `127.0.0.1` by default.
- `--allow-lan` is still required for non-localhost bind.
- No token values are printed by launchers or UI status output.
- No auto-apply or hidden browser automation is introduced.
- Wrapper health checks use only the local loopback UI endpoint.

## Done / Not Done Boundary

### Done

- stable local app-style launch on Windows;
- no-browser server mode for wrappers;
- predictable startup/shutdown for the wrapper flow;
- relative-path-safe launch behavior;
- CLI compatibility preserved.

### Not done yet

- native installer (`.exe`, MSI, DMG, AppImage);
- Tauri/Electron/WebView-native shell;
- bundling Python into a single distributable;
- tray integration, auto-update, or OS notifications.

Those remain planned because they require a dedicated packaging/distribution pass,
not just runtime hardening inside the current repo.
