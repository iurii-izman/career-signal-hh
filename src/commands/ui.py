"""UI command — launch local web interface, shortcut helper, app-mode."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .. import __version__
from ..hh_client import HHClient


def command_ui(args: argparse.Namespace) -> int:
    """Launch the local web UI, or handle sub-commands."""
    if getattr(args, "shortcut", False):
        return _print_shortcut_help()
    if getattr(args, "app_mode", False):
        return _print_app_mode_help()

    project_root = _project_root()
    _enter_project_root(project_root)

    host = args.host or "127.0.0.1"
    port = args.port or 8765
    open_browser = bool(getattr(args, "open_browser", False)) and not bool(
        getattr(args, "no_browser", False)
    )

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
    load_dotenv(dotenv_path=project_root / ".env")

    # Suppress token display
    client = HHClient()
    token_status = "set" if client.active_token_present else "not set"

    url = _build_ui_url(host, port)

    print("\nCareerSignal HH Local UI")
    print(f"  Version:  {__version__}")
    print(f"  URL:      {url}")
    print(f"  Auth:     {client.auth_mode}")
    print(f"  Token:    {token_status}")
    print(f"  Bind:     {host}:{port}")
    print(f"  Root:     {project_root}")
    print(f"  Browser:  {'disabled' if not open_browser else 'enabled'}")
    print()

    # Write status file
    _write_ui_status(
        host,
        port,
        state="starting",
        root=project_root,
        url=url,
        open_browser=open_browser,
    )

    # Open browser
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            print("Could not open browser automatically.", file=sys.stderr)

    # Start server
    try:
        import uvicorn

        from ..web import create_app

        app = create_app()
        app.state.ui_runtime = {
            "host": host,
            "port": port,
            "url": url,
            "root": project_root,
            "open_browser": open_browser,
        }

        @app.on_event("startup")
        async def _ui_started() -> None:
            _write_ui_status(
                host,
                port,
                state="running",
                root=project_root,
                url=url,
                open_browser=open_browser,
            )

        @app.on_event("shutdown")
        async def _ui_stopped() -> None:
            _write_ui_status(
                host,
                port,
                state="stopped",
                root=project_root,
                url=url,
                open_browser=open_browser,
            )

        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info" if args.debug else "warning",
            access_log=args.debug,
        )
    except ImportError as exc:
        _write_ui_status(
            host,
            port,
            state="failed",
            root=project_root,
            url=url,
            open_browser=open_browser,
            last_error=str(exc),
        )
        print(f"ERROR: Missing dependencies: {exc}", file=sys.stderr)
        print("Install with: pip install fastapi uvicorn jinja2", file=sys.stderr)
        return 1
    except Exception as exc:
        _write_ui_status(
            host,
            port,
            state="failed",
            root=project_root,
            url=url,
            open_browser=open_browser,
            last_error=str(exc),
        )
        raise

    return 0


def _project_root() -> Path:
    """Return the repository root for reliable launcher behavior."""
    return Path(__file__).resolve().parents[2]


def _enter_project_root(project_root: Path) -> None:
    """Ensure relative runtime paths resolve from the repository root."""
    if Path.cwd().resolve() != project_root.resolve():
        os.chdir(project_root)


def _build_ui_url(host: str, port: int) -> str:
    """Build the browser-facing UI URL."""
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _write_ui_status(
    host: str,
    port: int,
    *,
    state: str = "unknown",
    root: Path | None = None,
    url: str | None = None,
    open_browser: bool | None = None,
    last_error: str | None = None,
) -> None:
    """Write data/ui_status.json with server info."""
    runtime_root = root or Path.cwd()
    try:
        data_dir = runtime_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        status = {
            "state": state,
            "server_started_at": datetime.now(timezone.utc).isoformat(),
            "port": port,
            "host": host,
            "url": url or _build_ui_url(host, port),
            "version": __version__,
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "project_root": str(runtime_root),
            "open_browser": open_browser,
            "hostname": socket.gethostname(),
        }
        if last_error:
            status["last_error"] = last_error
        (data_dir / "ui_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _print_shortcut_help() -> int:
    """Print instructions to create desktop shortcuts."""
    project_root = _project_root()
    print("\nCareerSignal HH — Desktop Shortcut Helper\n")

    print("=== Windows ===")
    print()
    print("Option 1: Desktop app wrapper (recommended)")
    print("  Run: scripts/Create-CareerSignalShortcut.ps1")
    print()
    print("Option 2: Manual shortcut")
    print("  Right-click Desktop > New > Shortcut")
    print('  Target: powershell.exe -ExecutionPolicy Bypass -File "')
    print(f'    {project_root / "scripts" / "start_app.ps1"}"')
    print()
    print("Option 3: Browser UI launcher")
    print(f'  powershell.exe -ExecutionPolicy Bypass -File "{project_root / "scripts" / "start_ui.ps1"}"')
    print()

    print("=== macOS ===")
    print()
    print("Option: Create .command file:")
    print("  echo '#!/bin/bash' > ~/Desktop/CareerSignal.command")
    print(f"  echo 'cd {project_root} && bash scripts/start_ui.sh' >> ~/Desktop/CareerSignal.command")
    print("  chmod +x ~/Desktop/CareerSignal.command")
    print()

    print("=== Linux ===")
    print()
    print("Option: Create .desktop file:")
    print("  cat > ~/.local/share/applications/career-signal.desktop << 'EOF'")
    print("  [Desktop Entry]")
    print("  Name=CareerSignal HH")
    print(f"  Exec=bash {project_root / 'scripts' / 'start_ui.sh'}")
    print(f"  Path={project_root}")
    print("  Terminal=true")
    print("  Type=Application")
    print("  EOF")
    print()

    return 0


def _print_app_mode_help() -> int:
    """Print browser app-mode commands."""
    print("\nCareerSignal HH — Browser App Mode\n")
    print("Windows-first app-mode runner:")
    print()
    print("  powershell -ExecutionPolicy Bypass -File scripts/start_app.ps1")
    print()
    print("Manual app-mode commands:")
    print()
    print("  Chrome/Edge:")
    print("    python -m src.main ui --no-browser")
    print("    start chrome --app=http://127.0.0.1:8765")
    print("    start msedge --app=http://127.0.0.1:8765")
    print()
    print("  Firefox (via extension or kiosk mode):")
    print("    python -m src.main ui --no-browser")
    print("    firefox --kiosk http://127.0.0.1:8765")
    print()
    print("Use --no-browser when a wrapper or external browser handles the window.")
    print()
    return 0
