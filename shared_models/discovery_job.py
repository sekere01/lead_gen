"""Shared DiscoveryJob model."""
from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime, timezone

from shared_models import Base


class DiscoveryJob(Base):
    """Discovery job tracking model."""
    __tablename__ = "discovery_jobs"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    region = Column(String(100), nullable=False)
    status = Column(String(50), default='pending', index=True)
    results_count = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text)
    last_run = Column(DateTime)
    last_heartbeat = Column(DateTime)
    error_message = Column(String(500))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)