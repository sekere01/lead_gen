#!/bin/bash
# Run Celery worker for lead generation pipeline
# Usage: ./run_celery_worker.sh [queue_name]

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

# Queue to process (default: all queues)
QUEUE=${1:-discovery,browsing,enrichment,verification}

echo "Starting Celery worker for queues: $QUEUE"
echo "Redis broker: $REDIS_URL"

# Use .venv from project root
"$SCRIPT_DIR/.venv/bin/celery" -A celery_tasks worker \
    --loglevel=info \
    --queues=$QUEUE \
    --concurrency=1 \
    --prefetch-multiplier=1 \
    --hostname=worker@%h