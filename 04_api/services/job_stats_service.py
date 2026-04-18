"""
Job Stats Service - Manages pre-computed job counts for fast dashboard queries.
"""
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import Dict, Optional
from datetime import datetime

from database import JobStats, SessionLocal


class JobStatsService:
    """Service for managing cached job statistics."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_all(self) -> list[JobStats]:
        """Get all job stats."""
        return self.db.query(JobStats).all()
    
    def get_summary(self) -> Dict[str, Dict[str, int]]:
        """Get nested dict: {job_type: {status: count}}"""
        result = {
            'discovery': {},
            'browsing': {},
            'enrichment': {},
            'verification': {}
        }
        for stat in self.db.query(JobStats).all():
            result[stat.job_type][stat.status] = stat.count
        return result
    
    def get_counts(self, job_type: str = 'discovery') -> Dict[str, int]:
        """Get counts for a specific job type."""
        stats = self.db.query(JobStats).filter(JobStats.job_type == job_type).all()
        return {s.status: s.count for s in stats}
    
    def get_pending_count(self, job_type: str = 'discovery') -> int:
        """Get pending count for a job type."""
        stat = self.db.query(JobStats).filter(
            JobStats.job_type == job_type,
            JobStats.status == 'pending'
        ).first()
        return stat.count if stat else 0
    
    def get_processing_count(self, job_type: str = 'discovery') -> int:
        """Get processing count for a job type."""
        stat = self.db.query(JobStats).filter(
            JobStats.job_type == job_type,
            JobStats.status == 'processing'
        ).first()
        return stat.count if stat else 0
    
    def get_completed_count(self, job_type: str = 'discovery') -> int:
        """Get completed count for a job type."""
        stat = self.db.query(JobStats).filter(
            JobStats.job_type == job_type,
            JobStats.status == 'completed'
        ).first()
        return stat.count if stat else 0
    
    def get_failed_count(self, job_type: str = 'discovery') -> int:
        """Get failed count for a job type."""
        stat = self.db.query(JobStats).filter(
            JobStats.job_type == job_type,
            JobStats.status == 'failed'
        ).first()
        return stat.count if stat else 0
    
    def increment(self, job_type: str, status: str, amount: int = 1, job_id: int = None):
        """Atomic increment - now uses unified UPSERT for both +/-."""
        self.update_count(job_type, status, amount, job_id)

    def decrement(self, job_type: str, status: str, amount: int = 1):
        """Atomic decrement - now uses unified UPSERT for both +/-."""
        self.update_count(job_type, status, -amount, None)

    def update_count(self, job_type: str, status: str, delta: int, job_id: int = None):
        """Unified atomic update - handles both + and - deltas safely."""
        self.db.execute(
            text("""
                INSERT INTO job_stats (job_type, status, count, last_job_id, updated_at)
                VALUES (:job_type, :status, GREATEST(0, :delta), :job_id, NOW())
                ON CONFLICT (job_type, status)
                DO UPDATE SET
                    count = GREATEST(0, job_stats.count + :delta),
                    last_job_id = COALESCE(:job_id, job_stats.last_job_id),
                    updated_at = NOW()
            """),
            {
                'job_type': job_type,
                'status': status,
                'delta': delta,
                'job_id': job_id
            }
        )
        self.db.commit()
    
    def set_count(self, job_type: str, status: str, count: int, job_id: int = None):
        """Set absolute count - use for backfilling."""
        self.db.execute(
            text("""
                INSERT INTO job_stats (job_type, status, count, last_job_id, updated_at)
                VALUES (:job_type, :status, :count, :job_id, NOW())
                ON CONFLICT (job_type, status) 
                DO UPDATE SET 
                    count = :count,
                    last_job_id = :job_id,
                    updated_at = NOW()
            """),
            {
                'job_type': job_type,
                'status': status,
                'count': count,
                'job_id': job_id
            }
        )
        self.db.commit()
    
    def transition(self, job_type: str, job_id: int, from_status: str, to_status: str):
        """Atomic status transition - decrement old, increment new."""
        self.db.execute(
            text("""
                UPDATE job_stats 
                SET count = GREATEST(0, count - 1),
                    updated_at = NOW()
                WHERE job_type = :job_type AND status = :from_status
            """),
            {'job_type': job_type, 'from_status': from_status}
        )
        self.db.execute(
            text("""
                UPDATE job_stats 
                SET count = count + 1,
                    last_job_id = :job_id,
                    updated_at = NOW()
                WHERE job_type = :job_type AND status = :to_status
            """),
            {'job_type': job_type, 'job_id': job_id, 'to_status': to_status}
        )
        self.db.commit()
    
    def backfill(self, job_type: str = 'discovery'):
        """Backfill stats from actual job data."""
        from database import DiscoveryJob
        
        # Get counts by status
        counts = self.db.query(
            DiscoveryJob.status,
            func.count(DiscoveryJob.id)
        ).group_by(DiscoveryJob.status).all()
        
        for status, count in counts:
            self.set_count(job_type, status, count)
        
        return {status: count for status, count in counts}


def get_stats_service() -> JobStatsService:
    """Get a JobStatsService instance."""
    db = SessionLocal()
    return JobStatsService(db)