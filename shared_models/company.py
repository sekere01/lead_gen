"""Shared Company model — all columns from every service."""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from datetime import datetime, timezone

from shared_models import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text)
    industry = Column(String(100))
    employee_count = Column(Integer)
    founded_year = Column(Integer)
    headquarters_location = Column(String(255))
    website_url = Column(String(500))
    linkedin_url = Column(String(500))
    twitter_url = Column(String(500))
    facebook_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    discovery_score = Column(Integer, default=0, index=True)
    lead_source = Column(String(100))
    status = Column(String(50), default='discovered', index=True)
    retry_count = Column(Integer, default=0)
    failure_reason = Column(String(500))
    last_heartbeat = Column(DateTime)
    browse_heartbeat = Column(DateTime)
    has_contact_link = Column(Boolean, default=False)
    has_address = Column(Boolean, default=False)
    has_social_links = Column(Boolean, default=False)
    has_email_on_homepage = Column(Boolean, default=False)
    is_parked = Column(Boolean, default=False)
    language_match = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)