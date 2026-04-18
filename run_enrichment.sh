#!/bin/bash
# Run Enrichment Service using its venv

cd "$(dirname "$0")/02_enrichment"

PID_FILE="/tmp/leadgen_enrichment.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing existing enrichment (PID: $OLD_PID)"
        kill -9 "$OLD_PID" 2>/dev/null
        sleep 1
    fi
fi

echo $$ > "$PID_FILE"
./venv/bin/python main.py