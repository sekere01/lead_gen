#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
cd "$SCRIPT_DIR/04_api"
exec celery -A celery_tasks worker --loglevel=info --concurrency=1 --prefetch-multiplier=1 -Q discovery,browsing,enrichment,verification,default
