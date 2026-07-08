"""UI command — launch local web interface, shortcut helper, app-mode."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from ..hh_client import HHClient


def command_ui(args: argparse.Namespace) -> int:
    """Launch the local web UI, or handle sub-commands."""
    if getattr(args, "shortcut", False):
        return _print_shortcut_help()
    if getattr(args, "app_mode", False):
        return _print_app_mode_help()

    host = args.host or "127.0.0.1"
    port = args.port or 8765

    # Safety: refuse non-localhost unless explicitly allowed
    if host not in ("127.0.0.1", "localhost", "::1"):
        if not args.allow_lan:
            print(
                "ERROR: Refusing to bind to non-localhost address "
                f"({host}). Use --allow-lan to override.",
                file=sys.stderr,
            )
            return 1
        print(f"WARNING: Binding to non-localhost address {host}.", file=sys.stderr)

    # Load env
    load_dotenv()

    # Suppress token display
    client = HHClient()
    token_status = "set" if client.active_token_present else "not set"

    url = f"http://{host}:{port}"
    if host == "0.0.0.0":
        url = f"http://127.0.0.1:{port}"

    print("\nCareerSignal HH Local UI")
    print("  Version:  0.7.0")
    print(f"  URL:      {url}")
    print(f"  Auth:     {client.auth_mode}")
    print(f"  Token:    {token_status}")
    print(f"  Bind:     {host}:{port}")
    print()

    # Write status file
    _write_ui_status(host, port)

    # Open browser
    if args.open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            print("Could not open browser automatically.", file=sys.stderr)

    # Start server
    try:
        import uvicorn

        from ..web import create_app

        app = create_app()

        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info" if args.debug else "warning",
            access_log=args.debug,
        )
    except ImportError as exc:
        print(f"ERROR: Missing dependencies: {exc}", file=sys.stderr)
        print("Install with: pip install fastapi uvicorn jinja2", file=sys.stderr)
        return 1

    return 0


def _write_ui_status(host: str, port: int) -> None:
    """Write data/ui_status.json with server info."""
    try:
        Path("data").mkdir(parents=True, exist_ok=True)
        status = {
            "server_started_at": datetime.now(timezone.utc).isoformat(),
            "port": port,
            "host": host,
            "version": "0.7.0",
        }
        Path("data/ui_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _print_shortcut_help() -> int:
    """Print instructions to create desktop shortcuts."""
    print("\nCareerSignal HH — Desktop Shortcut Helper\n")

    print("=== Windows ===")
    print()
    print("Option 1: PowerShell shortcut script")
    print("  Run: scripts/Create-CareerSignalShortcut.ps1")
    print()
    print("Option 2: Manual shortcut")
    print("  Right-click Desktop > New > Shortcut")
    print('  Target: powershell.exe -ExecutionPolicy Bypass -File "')
    print(f'    {Path.cwd() / "scripts" / "start_ui.ps1"}"')
    print()
    print("Option 3: Chrome App Mode (no address bar)")
    print("  start chrome --app=http://127.0.0.1:8765")
    print()

    print("=== macOS ===")
    print()
    print("Option: Create .command file:")
    print("  echo '#!/bin/bash' > ~/Desktop/CareerSignal.command")
    print(f"  echo 'cd {Path.cwd()} && bash scripts/start_ui.sh' >> ~/Desktop/CareerSignal.command")
    print("  chmod +x ~/Desktop/CareerSignal.command")
    print()

    print("=== Linux ===")
    print()
    print("Option: Create .desktop file:")
    print("  cat > ~/.local/share/applications/career-signal.desktop << 'EOF'")
    print("  [Desktop Entry]")
    print("  Name=CareerSignal HH")
    print(f"  Exec=bash {Path.cwd() / 'scripts' / 'start_ui.sh'}")
    print(f"  Path={Path.cwd()}")
    print("  Terminal=true")
    print("  Type=Application")
    print("  EOF")
    print()

    return 0


def _print_app_mode_help() -> int:
    """Print browser app-mode commands."""
    print("\nCareerSignal HH — Browser App Mode\n")
    print("Run the UI in a borderless browser window (no address bar):")
    print()
    print("  Chrome/Edge:")
    print("    start chrome --app=http://127.0.0.1:8765")
    print("    start msedge --app=http://127.0.0.1:8765")
    print()
    print("  Firefox (via extension or kiosk mode):")
    print("    firefox --kiosk http://127.0.0.1:8765")
    print()
    print("First start the server: python -m src.main ui")
    print("Then open the app window with one of the commands above.")
    print()
    return 0
