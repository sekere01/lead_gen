"""
Database configuration for Verification Service.
All tables are defined in shared_models and created via Base.metadata.create_all().
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from config import settings
from shared_models import Company, Contact, JobStats, update_job_stats, Base

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


def _ensure_indexes():
    """Create indexes that SQLAlchemy create_all() may not handle automatically."""
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_company_domain ON companies(domain)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_company_id ON contacts(company_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_contact_verification_status ON contacts(verification_status)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_email_lower ON contacts (LOWER(email))"))
        conn.commit()


def init_db():
    """Initialize database tables from shared_models definitions."""
    Base.metadata.create_all(engine)
    _ensure_indexes()
    print("Verification database tables initialized successfully")