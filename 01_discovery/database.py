"""
Database configuration and session management.
Creates tables on startup if they don't exist.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from config import settings

# Create engine
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables if they don't exist."""
    from sqlalchemy import text
    
    # Create tables using raw SQL for compatibility
    with engine.connect() as conn:
        # Discovery Jobs table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS discovery_jobs (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(255) NOT NULL,
                region VARCHAR(100) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                results_count INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                last_run TIMESTAMP,
                last_heartbeat TIMESTAMP WITH TIME ZONE,
                error_message VARCHAR(500),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        
        # Migration: Add last_heartbeat column if it doesn't exist (for existing tables)
        conn.execute(text("""
            ALTER TABLE discovery_jobs 
            ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP WITH TIME ZONE
        """))
        
        # Companies table
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
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))
        
        # Create indexes
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_status ON discovery_jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_keyword_region ON discovery_jobs(keyword, region)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_heartbeat ON discovery_jobs(last_heartbeat)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_last_run ON discovery_jobs(last_run)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_domain ON companies(domain)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_discovery_score ON companies(discovery_score)"))
        
        conn.commit()
    
    print("Database tables initialized successfully")


# Models (for reference)
class DiscoveryJob(Base):
    """DiscoveryJob model representing a keyword search task."""
    __tablename__ = "discovery_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    region = Column(String(100), nullable=False)
    status = Column(String(50), default='pending')
    results_count = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text)
    last_run = Column(DateTime)
    last_heartbeat = Column(DateTime)
    error_message = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)


class Company(Base):
    """Company model representing a business entity."""
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
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
    discovery_score = Column(Integer, default=0)
    lead_source = Column(String(100))
    status = Column(String(50), default='discovered')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)
