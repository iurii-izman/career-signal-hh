#!/bin/bash
# CareerSignal HH — Local UI Launcher (Bash)
# Run: bash scripts/start_ui.sh

set -e

# Activate venv if exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "Activated .venv"
fi

# Create log dir
mkdir -p logs
LOG_FILE="logs/ui_$(date +%Y%m%d_%H%M%S).log"
echo "Log: $LOG_FILE"

# Start UI
echo "Starting CareerSignal HH Local UI..."
python -m src.main ui --open-browser 2>&1 | tee "$LOG_FILE"
