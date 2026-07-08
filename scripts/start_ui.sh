#!/bin/bash
# CareerSignal HH — Local UI Launcher (Bash)
# Run: bash scripts/start_ui.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

resolve_python() {
    if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
        printf '%s' "${REPO_ROOT}/.venv/bin/python"
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        command -v python
        return 0
    fi
    echo "Python 3.11+ not found. Create .venv or add python to PATH." >&2
    return 1
}

PYTHON_BIN="$(resolve_python)"

# Create log dir
mkdir -p "${REPO_ROOT}/logs"
LOG_FILE="${REPO_ROOT}/logs/ui_$(date +%Y%m%d_%H%M%S).log"
echo "Log: $LOG_FILE"
echo "Repo: $REPO_ROOT"

# Start UI
echo "Starting CareerSignal HH Local UI..."
cd "$REPO_ROOT"
"$PYTHON_BIN" -m src.main ui --open-browser 2>&1 | tee "$LOG_FILE"
