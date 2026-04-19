"""Celery application configuration for lead_gen pipeline."""
from celery import Celery
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "leadgen",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "celery_tasks.tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes max per task
    task_soft_time_limit=240,  # 4 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_concurrency=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Queue definitions
celery_app.conf.task_routes = {
    "celery_tasks.tasks.process_discovery_job": {"queue": "discovery"},
    "celery_tasks.tasks.process_browsing": {"queue": "browsing"},
    "celery_tasks.tasks.process_enrichment": {"queue": "enrichment"},
    "celery_tasks.tasks.process_verification": {"queue": "verification"},
    "celery_tasks.tasks.collect_metrics": {"queue": "default"},
}

# Periodic task schedule (Celery Beat)
celery_app.conf.beat_schedule = {
    "collect-metrics-every-30-seconds": {
        "task": "celery_tasks.tasks.collect_metrics",
        "schedule": 30.0,  # Every 30 seconds
    },
}