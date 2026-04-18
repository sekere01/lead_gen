"""Shared Contact and ExtractedEmail models."""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from datetime import datetime, timezone

from shared_models import Base


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    job_title = Column(String(255))
    department = Column(String(100))
    phone_number = Column(String(50))
    linkedin_profile = Column(String(500))
    twitter_handle = Column(String(100))
    is_verified = Column(Boolean, default=False)
    verification_date = Column(DateTime)
    verification_status = Column(String(50), index=True)
    is_catch_all = Column(Boolean, default=False)
    needs_retry = Column(Boolean, default=False)
    source_url = Column(Text)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)


class ExtractedEmail(Base):
    __tablename__ = "extracted_emails"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    email_type = Column(String(50))
    source_url = Column(Text)
    company_id = Column(Integer, ForeignKey("companies.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))