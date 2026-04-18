"""
Database configuration and session management for Discovery Service.
Creates tables on startup if they don't exist.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, event
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from config import settings
from shared_models import Company, JobStats, update_job_stats

# Create engine with limited pool to prevent connection exhaustion
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

        conn.execute(text("""
            ALTER TABLE discovery_jobs
            ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP WITH TIME ZONE
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

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_status ON discovery_jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_keyword_region ON discovery_jobs(keyword, region)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_heartbeat ON discovery_jobs(last_heartbeat)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_last_run ON discovery_jobs(last_run)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_domain ON companies(domain)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_discovery_score ON companies(discovery_score)"))

        conn.commit()

    print("Database tables initialized successfully")


class DiscoveryJob(Company.__bases__[0].__class__):
    """DiscoveryJob model — service-specific, not in shared_models."""
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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime)