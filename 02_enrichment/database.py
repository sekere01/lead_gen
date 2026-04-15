"""
Database configuration for Enrichment Service.
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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                domain VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                industry VARCHAR(100),
                employee_count INTEGER,
                founded_year INTEGER,
                headquarters_location VARCHAR(255),
                website_url VARCHAR(500),
                linkedin_url VARCHAR(500),
                twitter_url VARCHAR(500),
                facebook_url VARCHAR(500),
                is_active BOOLEAN DEFAULT TRUE,
                discovery_score INTEGER DEFAULT 0,
                lead_source VARCHAR(100),
                status VARCHAR(50) DEFAULT 'discovered',
                retry_count INTEGER DEFAULT 0,
                failure_reason VARCHAR(500),
                last_heartbeat TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        
        # Migration: Add enrichment columns if they don't exist (for existing tables)
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(500)
        """))
        conn.execute(text("""
            ALTER TABLE companies 
            ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP WITH TIME ZONE
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                job_title VARCHAR(255),
                department VARCHAR(100),
                phone_number VARCHAR(50),
                linkedin_profile VARCHAR(500),
                twitter_handle VARCHAR(100),
                is_verified BOOLEAN DEFAULT FALSE,
                verification_date TIMESTAMP WITH TIME ZONE,
                verification_status VARCHAR(50),
                is_catch_all BOOLEAN DEFAULT FALSE,
                needs_retry BOOLEAN DEFAULT FALSE,
                source_url TEXT,
                company_id INTEGER NOT NULL REFERENCES companies(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS extracted_emails (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                email_type VARCHAR(50),
                source_url TEXT,
                company_id INTEGER REFERENCES companies(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_discovery_score ON companies(discovery_score)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_heartbeat ON companies(last_heartbeat)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_retry ON companies(retry_count)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_company_id ON contacts(company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_verification_status ON contacts(verification_status)"))
        
        conn.commit()
    
    print("Enrichment database tables initialized successfully")


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
