"""
Database configuration for Browsing Service.
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, event
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
    """Initialize database columns if they don't exist."""
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("""
            ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS browse_heartbeat TIMESTAMP WITH TIME ZONE
        """))
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

        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_browse_heartbeat ON companies(browse_heartbeat)"))
        conn.commit()

    print("Browsing database columns initialized successfully")