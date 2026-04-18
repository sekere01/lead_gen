#!/bin/bash
# Run Discovery Service using its venv

cd "$(dirname "$0")/01_discovery"

PID_FILE="/tmp/leadgen_discovery.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing existing discovery (PID: $OLD_PID)"
        kill -9 "$OLD_PID" 2>/dev/null
        sleep 1
    fi
fi

echo $$ > "$PID_FILE"
./venv/bin/python main.py