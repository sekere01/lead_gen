#!/bin/bash
# Run API + Celery Beat + Celery Worker
#
# Usage: ./run_api_full.sh [start|stop|restart|status] [queue_name]
#
# Examples:
#   ./run_api_full.sh start              # start all services with default queues
#   ./run_api_full.sh stop             # stop all services
#   ./run_api_full.sh restart          # restart all services
#   ./run_api_full.sh status         # check which services are running
#   ./run_api_full.sh start "discovery,browsing"  # custom queues (quoted!)
#
# Default queues: discovery,browsing,enrichment,verification,default

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

PID_DIR="/tmp"
API_PID_FILE="$PID_DIR/leadgen_api.pid"
BEAT_PID_FILE="$PID_DIR/leadgen_beat.pid"
WORKER_PID_FILE="$PID_DIR/leadgen_worker.pid"

REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}
QUEUE=${1:-discovery,browsing,enrichment,verification,default}

# ── Helpers ──────────────────────────────────────────────────────────────
kill_pid_file() {
    local PID_FILE=$1
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "  Killing PID $OLD_PID..."
            kill -15 "$OLD_PID" 2>/dev/null  # SIGTERM first
            sleep 2
            kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID" 2>/dev/null  # SIGKILL if still alive
        fi
        rm -f "$PID_FILE"
    fi
}

kill_by_pattern() {
    # Kill any orphan processes matching pattern not tracked by PID files
    local PATTERN=$1
    pkill -f "$PATTERN" 2>/dev/null
    sleep 1
}

reap_zombies() {
    # Reap any zombie celery/uvicorn processes
    kill_by_pattern "uvicorn main:app"
    kill_by_pattern "celery_tasks beat"
    kill_by_pattern "celery_tasks worker"
}

stop_all() {
    echo "Stopping all services..."
    kill_pid_file "$API_PID_FILE"
    kill_pid_file "$BEAT_PID_FILE"
    kill_pid_file "$WORKER_PID_FILE"
    reap_zombies
    echo "All services stopped."
}

start_all() {
    cd "$SCRIPT_DIR/04_api"

    # Load environment
    if [ -f .env ]; then
        export $(grep -v '^#' .env | xargs)
    fi

    # Kill any existing tracked + orphan processes before starting
    stop_all

    echo "Starting services..."

    echo "  Starting API on port 8000..."
    ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
    echo $! > "$API_PID_FILE"
    echo "  API PID: $(cat $API_PID_FILE)"

    echo "  Starting Celery Beat..."
    "$SCRIPT_DIR/.venv/bin/celery" -A celery_tasks beat \
        --loglevel=info \
        --schedule=/tmp/celerybeat-schedule.db &
    echo $! > "$BEAT_PID_FILE"
    echo "  Beat PID: $(cat $BEAT_PID_FILE)"

    echo "  Starting Celery Worker (queues: $QUEUE)..."
    "$SCRIPT_DIR/.venv/bin/celery" -A celery_tasks worker \
        --loglevel=info \
        --queues=$QUEUE \
        --concurrency=1 \
        --prefetch-multiplier=1 \
        --hostname=worker@%h &
    echo $! > "$WORKER_PID_FILE"
    echo "  Worker PID: $(cat $WORKER_PID_FILE)"

    echo "All services started."
}

status_all() {
    echo "Service status:"
    for NAME_FILE in "API:$API_PID_FILE" "Beat:$BEAT_PID_FILE" "Worker:$WORKER_PID_FILE"; do
        NAME="${NAME_FILE%%:*}"
        FILE="${NAME_FILE##*:}"
        if [ -f "$FILE" ]; then
            PID=$(cat "$FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "  $NAME: Running (PID $PID)"
            else
                echo "  $NAME: Dead (stale PID file)"
            fi
        else
            echo "  $NAME: Not running"
        fi
    done
}

# ── Entry point ──────────────────────────────────��────────────────────────
case "${1:-start}" in
    start)   start_all ;;
    stop)    stop_all ;;
    restart) stop_all; sleep 2; start_all ;;
    status)  status_all ;;
    *)       echo "Usage: $0 [start|stop|restart|status] [queue_name]"; exit 1 ;;
esac