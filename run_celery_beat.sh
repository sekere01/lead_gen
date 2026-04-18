#!/bin/bash
# Run Celery Beat scheduler for periodic tasks
# Usage: ./run_celery_beat.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/04_api"

# Add project root to PYTHONPATH
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Redis URL (default to localhost if not set)
REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}

echo "Starting Celery Beat scheduler"
echo "Redis broker: $REDIS_URL"

# Use .venv from project root
"$SCRIPT_DIR/.venv/bin/celery" -A celery_tasks beat \
    --loglevel=info \
    --schedule=/tmp/celerybeat-schedule.db