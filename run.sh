#!/bin/bash
# run.sh — Single entry point for cron and manual runs.
# Resolves its own location, so it works on any device with no hard-coded paths.
# Called as: /path/to/run.sh >> /path/to/logs/analyzer.log 2>&1

set -e

# Resolve the directory this script lives in (portable across devices)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Pick a Python interpreter (prefer python3)
PYTHON="$(command -v python3 || command -v python)"
if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found on PATH. Install Python 3 and re-run." >&2
    exit 1
fi

# Ensure all required packages are present (idempotent — fast when already installed)
"$PYTHON" -m pip install --quiet --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"

# Run the pipeline
exec "$PYTHON" main.py
