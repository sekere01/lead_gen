"""
Database configuration for Enrichment Service.
"""
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, ForeignKey, event
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from config import settings
from shared_models import Company, Contact, ExtractedEmail, JobStats, update_job_stats

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=1,
    pool_recycle=300,
    pool_timeout=5
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def set_statement_timeout(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("SET statement_timeout = '30000'")
    cursor.close()


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