"""
Database configuration for Enrichment Service.
All tables are defined in shared_models and created via Base.metadata.create_all().
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from config import settings
from shared_models import Company, Contact, ExtractedEmail, JobStats, update_job_stats, Base

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=300,
    pool_timeout=settings.DB_POOL_TIMEOUT
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
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_status ON companies(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_discovery_score ON companies(discovery_score)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_heartbeat ON companies(last_heartbeat)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_retry ON companies(retry_count)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_company_id ON contacts(company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_verification_status ON contacts(verification_status)"))
        conn.commit()


def init_db():
    """Initialize database tables from shared_models definitions."""
    Base.metadata.create_all(engine)
    _ensure_indexes()
    print("Enrichment database tables initialized successfully")