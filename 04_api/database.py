"""
Database configuration for API Service.
All tables are defined in shared_models and created via Base.metadata.create_all().
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from config import settings
from shared_models import (
    Base,
    Company,
    Contact,
    ExtractedEmail,
    JobStats,
    DiscoveryJob,
    JobTemplate,
    ServiceMetrics,
    update_job_stats,
)

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


def _ensure_indexes():
    """Create indexes that SQLAlchemy create_all() may not handle automatically."""
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_discovery_job_status ON discovery_jobs(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_verification_status ON contacts(verification_status)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email_lower ON contacts (LOWER(email))"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_stats_type_status ON job_stats(job_type, status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_metrics_service_time ON service_metrics(service, recorded_at)"))
        conn.commit()


def _migrate_missing_columns():
    """Add any columns that may be missing from existing databases."""
    from sqlalchemy import text
    with engine.connect() as conn:
        columns_to_add = [
            ("companies", "browse_heartbeat", "TIMESTAMP WITH TIME ZONE"),
            ("companies", "has_contact_link", "BOOLEAN DEFAULT FALSE"),
            ("companies", "has_address", "BOOLEAN DEFAULT FALSE"),
            ("companies", "has_social_links", "BOOLEAN DEFAULT FALSE"),
            ("companies", "has_email_on_homepage", "BOOLEAN DEFAULT FALSE"),
            ("companies", "is_parked", "BOOLEAN DEFAULT FALSE"),
            ("companies", "language_match", "BOOLEAN DEFAULT FALSE"),
            ("companies", "last_heartbeat", "TIMESTAMP WITH TIME ZONE"),
            ("discovery_jobs", "last_heartbeat", "TIMESTAMP WITH TIME ZONE"),
            ("job_stats", "last_job_id", "INTEGER"),
        ]
        for table, column, col_type in columns_to_add:
            try:
                conn.execute(text(f"""
                    DO $$
                    BEGIN
                        ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type};
                    EXCEPTION WHEN others THEN NULL;
                    END $$;
                """))
            except Exception:
                pass
        conn.commit()


def init_db():
    """Initialize database tables from shared_models definitions."""
    Base.metadata.create_all(engine)
    _migrate_missing_columns()
    _ensure_indexes()
    print("API database tables initialized successfully")