#!/bin/bash
# CareerSignal HH Daily Run (Linux/Mac cron)
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR=$(pwd)
LOGDIR="logs"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/daily_$(date +%Y%m%d_%H%M%S).log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOGFILE"; }

log "=== CareerSignal HH Daily Run ==="
log "Project: $PROJECT_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    log "Venv activated"
else
    log "WARNING: .venv not found, using system Python"
fi

log "Running autopilot daily..."
python -m src.main autopilot daily --backup-first --yes 2>&1 | tee -a "$LOGFILE"
AUTO_EXIT=${PIPESTATUS[0]}
log "Autopilot exit code: $AUTO_EXIT"

log "Generating cockpit..."
python -m src.main cockpit export 2>&1 | tee -a "$LOGFILE"
log "Cockpit exit code: $?"

log "Running maintenance report..."
python -m src.main maintenance report 2>&1 | tee -a "$LOGFILE"
log "Maintenance exit code: $?"

log "=== Daily run complete ==="
exit $AUTO_EXIT
