"""Email List model for saved sorted email lists."""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime, timezone

from shared_models import Base


class EmailList(Base):
    __tablename__ = "email_lists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    total_emails = Column(Integer, default=0)
    provider_breakdown = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
