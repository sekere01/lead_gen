"""Shared service metrics model."""
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timezone

from shared_models import Base


class ServiceMetrics(Base):
    """Service metrics for monitoring pipeline health."""
    __tablename__ = "service_metrics"

    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(50), nullable=False, index=True)
    metric = Column(String(50), nullable=False)
    value = Column(Integer)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)