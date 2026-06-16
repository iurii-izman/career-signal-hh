#!/bin/bash
# Smoke check for CareerSignal HH

echo "=== CareerSignal HH Smoke Check ==="
failed=0
steps=(
    "help:python -m src.main --help"
    "doctor:python -m src.main doctor"
    "version:python -m src.main version"
    "presets list:python -m src.main presets list"
    "search dry-run:python -m src.main search --dry-run --mode smoke"
    "db info:python -m src.main db info"
    "export:python -m src.main export"
    "pytest:python -m pytest tests/ -q"
)

for step in "${steps[@]}"; do
    name="${step%%:*}"
    cmd="${step#*:}"
    echo ""
    echo "[$name]"
    if eval "$cmd" 2>&1; then
        echo "  OK"
    else
        echo "  FAILED"
        ((failed++))
    fi
done

echo ""
echo "=== $(( ${#steps[@]} - failed ))/${#steps[@]} passed ==="
exit $failed
