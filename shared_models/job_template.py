"""Shared job template model."""
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timezone

from shared_models import Base


class JobTemplate(Base):
    """Job template model for reusable job configurations."""
    __tablename__ = "job_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    keyword = Column(String(255), nullable=False)
    region = Column(String(100))
    city = Column(String(100))
    tld = Column(String(20))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))