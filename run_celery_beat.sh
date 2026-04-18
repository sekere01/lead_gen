#!/bin/bash
# Run Celery Beat scheduler for periodic tasks
# Usage: ./run_celery_beat.sh

cd "$(dirname "$0")/04_api"

# Add project root to PYTHONPATH
export PYTHONPATH="/home/fisazkido/lead_gen2:$PYTHONPATH"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Redis URL (default to localhost if not set)
REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}

echo "Starting Celery Beat scheduler"
echo "Redis broker: $REDIS_URL"

./.venv/bin/celery -A celery_tasks beat \
    --loglevel=info \
    --schedule=/tmp/celerybeat-schedule.db