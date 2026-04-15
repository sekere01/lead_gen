"""
Database configuration for Browsing Service.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables if they don't exist."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Update companies table - add browse_heartbeat column if missing
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS browse_heartbeat TIMESTAMP WITH TIME ZONE
        """))
        
        # Add browsing signals columns if missing
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS has_contact_link BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS has_address BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS has_social_links BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS has_email_on_homepage BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS is_parked BOOLEAN DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS language_match BOOLEAN DEFAULT FALSE
        """))
        
        conn.commit()
    
    print("Browsing database columns initialized successfully")


class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)
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
    discovery_score = Column(Integer, default=0)
    lead_source = Column(String(100))
    status = Column(String(50), default='discovered')
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)


class Contact(Base):
    __tablename__ = "contacts"
    
    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    job_title = Column(String(255))
    department = Column(String(100))
    phone_number = Column(String(50))
    linkedin_profile = Column(String(500))
    twitter_handle = Column(String(100))
    is_verified = Column(Boolean, default=False)
    verification_date = Column(DateTime)
    verification_status = Column(String(50))
    is_catch_all = Column(Boolean, default=False)
    needs_retry = Column(Boolean, default=False)
    source_url = Column(Text)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)


class ExtractedEmail(Base):
    __tablename__ = "extracted_emails"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    email_type = Column(String(50))
    source_url = Column(Text)
    company_id = Column(Integer, ForeignKey("companies.id"))
    created_at = Column(DateTime, default=datetime.utcnow)