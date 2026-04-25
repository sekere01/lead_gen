#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PID_FILE="/tmp/leadgen_enrichment.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing enrichment (PID: $OLD_PID)..."
        kill -15 "$OLD_PID" 2>/dev/null
        sleep 3
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing (PID: $OLD_PID)..."
            kill -9 "$OLD_PID" 2>/dev/null
        fi
    fi
    rm -f "$PID_FILE"
fi

pkill -f "python.*02_enrichment" 2>/dev/null
sleep 1

export PYTHONPATH="$PROJECT_ROOT"

cd "$SCRIPT_DIR"
./venv/bin/python main.py &
echo $! > "$PID_FILE"
wait