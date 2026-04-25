#!/bin/bash

cd "$(dirname "$0")/01b_browsing"

export PYTHONPATH="/home/fisazkido/lead_gen2:$PYTHONPATH"

PID_FILE="/tmp/leadgen_browsing.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing browsing (PID: $OLD_PID)..."
        kill -15 "$OLD_PID" 2>/dev/null
        sleep 3
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "Force killing (PID: $OLD_PID)..."
            kill -9 "$OLD_PID" 2>/dev/null
        fi
    fi
    rm -f "$PID_FILE"
fi

pkill -f "python.*01b_browsing" 2>/dev/null
sleep 1

./venv/bin/python main.py &
echo $! > "$PID_FILE"
wait