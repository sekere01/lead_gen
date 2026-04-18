"""Shared JobStats model and canonical update_job_stats function."""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from shared_models import Base


class JobStats(Base):
    __tablename__ = "job_stats"

    id = Column(Integer, primary_key=True)
    job_type = Column(String(20), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    count = Column(Integer, nullable=False, default=0)
    last_job_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def update_job_stats(
    db: Session,
    job_type: str,
    status: str,
    delta: int,
    job_id: int = None,
) -> None:
    """
    Atomically update job_stats count using UPSERT.
    Handles both + and - deltas safely. Uses GREATEST(0, ...) to prevent negative counts.
    """
    from sqlalchemy import text

    if delta == 0:
        return

    sql = text("""
        INSERT INTO job_stats (job_type, status, count, last_job_id, updated_at)
        VALUES (:job_type, :status, GREATEST(0, :delta), :job_id, NOW())
        ON CONFLICT (job_type, status)
        DO UPDATE SET
            count = GREATEST(0, job_stats.count + :delta),
            last_job_id = COALESCE(:job_id, job_stats.last_job_id),
            updated_at = NOW()
    """)

    db.execute(sql, {
        "job_type": job_type,
        "status": status,
        "delta": delta,
        "job_id": job_id,
    })
    db.commit()