#!/bin/bash

cd "$(dirname "$0")/01b_browsing"

# Add project root to PYTHONPATH so shared_models can be resolved
export PYTHONPATH="/home/fisazkido/lead_gen2:$PYTHONPATH"

PID_FILE="/tmp/leadgen_browsing.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing existing browsing (PID: $OLD_PID)"
        kill -9 "$OLD_PID" 2>/dev/null
        sleep 1
    fi
fi

echo $$ > "$PID_FILE"
source venv/bin/activate
python3 main.py