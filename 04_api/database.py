"""
Database configuration for API Service.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, event
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
from functools import lru_cache

from config import settings
from shared_models import Company, Contact, ExtractedEmail, JobStats, update_job_stats

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,
    pool_timeout=10,
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
            CREATE TABLE IF NOT EXISTS discovery_jobs (
                id SERIAL PRIMARY KEY,
                keyword VARCHAR(255) NOT NULL,
                region VARCHAR(100) NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                results_count INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                last_run TIMESTAMP,
                error_message VARCHAR(500),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
        """))

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
                browse_heartbeat TIMESTAMP WITH TIME ZONE,
                has_contact_link BOOLEAN DEFAULT FALSE,
                has_address BOOLEAN DEFAULT FALSE,
                has_social_links BOOLEAN DEFAULT FALSE,
                has_email_on_homepage BOOLEAN DEFAULT FALSE,
                is_parked BOOLEAN DEFAULT FALSE,
                language_match BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE
            )
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

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_status ON discovery_jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_verification_status ON contacts(verification_status)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email_lower ON contacts (LOWER(email))"))

        conn.commit()

    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS job_stats (
                    id SERIAL PRIMARY KEY,
                    job_type VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    last_job_id INTEGER,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(job_type, status)
                )
            """))
            conn.commit()
    except Exception:
        pass

    try:
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS job_templates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    keyword VARCHAR(255) NOT NULL,
                    region VARCHAR(100),
                    city VARCHAR(100),
                    tld VARCHAR(20),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS service_metrics (
                    id SERIAL PRIMARY KEY,
                    service VARCHAR(50) NOT NULL,
                    metric VARCHAR(50) NOT NULL,
                    value INTEGER,
                    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
    except Exception:
        pass

    print("API database tables initialized successfully")


class DiscoveryJob(Company.__bases__[0].__class__):
    """DiscoveryJob model — API-specific, not shared."""
    __tablename__ = "discovery_jobs"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255), nullable=False, index=True)
    region = Column(String(100), nullable=False)
    status = Column(String(50), default='pending')
    results_count = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text)
    last_run = Column(DateTime)
    error_message = Column(String(500))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)


class JobTemplate(Company.__bases__[0].__class__):
    """JobTemplate model — API-specific."""
    __tablename__ = "job_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    keyword = Column(String(255), nullable=False)
    region = Column(String(100))
    city = Column(String(100))
    tld = Column(String(20))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ServiceMetrics(Company.__bases__[0].__class__):
    """ServiceMetrics model — API-specific."""
    __tablename__ = "service_metrics"

    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(50), nullable=False, index=True)
    metric = Column(String(50), nullable=False)
    value = Column(Integer)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)