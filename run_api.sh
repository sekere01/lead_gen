#!/bin/bash
# Run API Service using its venv

cd "$(dirname "$0")/04_api"

# Add project root to PYTHONPATH so shared_models can be resolved
export PYTHONPATH="/home/fisazkido/lead_gen2:$PYTHONPATH"

PID_FILE="/tmp/leadgen_api.pid"

# Kill existing API if running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Killing existing API (PID: $OLD_PID)"
        kill -9 "$OLD_PID" 2>/dev/null
        sleep 1
    fi
fi

# Save our PID
echo $$ > "$PID_FILE"

# Run API
./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000