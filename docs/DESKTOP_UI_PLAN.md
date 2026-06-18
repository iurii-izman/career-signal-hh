# Desktop UI Plan — CareerSignal HH

## Current State (Phase 1 — complete)

- Local web UI at http://127.0.0.1:8765
- FastAPI + Jinja2 + vanilla JS/CSS backend
- No CDN, no external dependencies
- CLI remains fully functional
- Launcher scripts for Windows/macOS/Linux

## Phase 2: Tauri Wrapper (planned)

Goal: Bundle the web UI as a native desktop application.

**Why Tauri:**
- Rust backend (matches project's Python+SQLite philosophy)
- Tiny binary (~5 MB) compared to Electron (~150 MB)
- Native OS integration: tray icon, notifications, auto-start
- The Python backend (FastAPI) could run as a sidecar process

**Architecture:**
```
[tauri-app.exe]
  ├── starts Python backend (python -m src.main ui --no-browser)
  ├── opens webview pointing to http://127.0.0.1:8765
  ├── system tray icon
  └── auto-shutdowns Python on exit
```

**Changes needed:**
- Add `--no-browser` flag to UI command
- Ensure all paths are relative to exe location
- Bundle Python via PyInstaller or embedded Python
- Tauri `tauri.conf.json` configuration

## Phase 3: Installer (planned)

- Inno Setup (Windows) — single .exe installer
- DMG (macOS) — drag-to-install
- AppImage/deb (Linux)
- Auto-creates desktop shortcut
- Registers file associations (.cshh config?)

## Security Boundaries

- **Network**: UI binds ONLY to 127.0.0.1 by default
  - `--allow-lan` flag required for any non-localhost binding
  - Token `HH_APP_ACCESS_TOKEN` never leaves the process
  - No cloud sync, no telemetry, no analytics
- **Token Safety**:
  - Token is stored only in `.env` (gitignored)
  - Never displayed in UI (only "set"/"not set" status)
  - Never logged (all logs sanitize token to `[REDACTED]`)
  - Settings page shows masked version (first 4 + last 4 characters)
- **Filesystem**:
  - Only reads/writes within project directory
  - Backup before any config modification
  - No arbitrary file access

## Why No Auto-Apply

CareerSignal HH is a monitoring and decision-support tool, NOT an auto-apply bot:

1. **HeadHunter ToS**: Automated applications may violate HH terms of service.
2. **Quality over quantity**: Manual review of each match produces better outcomes.
3. **Legal compliance**: Some jurisdictions require explicit consent for automated job applications.
4. **Anti-spam**: Mass applications damage candidate reputation.
5. **Human judgment**: AI scoring is an aid, not a replacement for human decision-making.

The "Mark Applied" button records a *manual* application that the user performed outside the tool (on hh.ru directly). It does NOT submit any application.

## App Mode (Chrome/Edge)

For a desktop-app-like experience without Tauri:

```bash
# Start server
python -m src.main ui

# In another terminal, open as app window (no address bar, no tabs)
start chrome --app=http://127.0.0.1:8765
# or
start msedge --app=http://127.0.0.1:8765
```

This provides a clean, borderless window identical to a native app.

## Future Considerations

- Tray icon with quick actions (Run Daily, Review Queue)
- Desktop notifications for new strong matches
- Scheduled daily runs via OS task scheduler integration
- Offline mode (cache last known state when API unavailable)
