"""
Dashboard Endpoints
Provides aggregated metrics and pipeline status for the dashboard.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db, Company, Contact, DiscoveryJob
from services.process_manager import process_manager

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class CompanyCountByStatus(BaseModel):
    status: str
    count: int


class ContactCountByVerification(BaseModel):
    verification_status: Optional[str] = "unknown"
    count: int


class JobQueueItem(BaseModel):
    id: int
    keyword: str
    region: str
    status: str
    created_at: Optional[str] = None
    last_run: Optional[str] = None


class PipelineMetrics(BaseModel):
    companies_total: int
    companies_by_status: List[CompanyCountByStatus]
    contacts_total: int
    contacts_by_verification: List[ContactCountByVerification]
    verified_count: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int


class DashboardStats(BaseModel):
    metrics: PipelineMetrics
    job_queue: List[JobQueueItem]
    services: dict


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    # Company counts by status
    company_status_counts = db.query(
        Company.status,
        func.count(Company.id).label('count')
    ).group_by(Company.status).all()
    
    companies_by_status = [
        CompanyCountByStatus(status=status, count=count)
        for status, count in company_status_counts
    ]
    
    companies_total = sum(c.count for c in companies_by_status)
    
    # Contact counts by verification status
    contact_verification_counts = db.query(
        func.coalesce(Contact.verification_status, 'unknown').label('verification_status'),
        func.count(Contact.id).label('count')
    ).group_by(func.coalesce(Contact.verification_status, 'unknown')).all()
    
    contacts_by_verification = [
        ContactCountByVerification(verification_status=status, count=count)
        for status, count in contact_verification_counts
    ]
    
    contacts_total = sum(c.count for c in contacts_by_verification)
    verified_count = db.query(Contact).filter(Contact.is_verified == True).count()
    
    # Job counts
    pending_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').count()
    processing_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'processing').count()
    completed_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'completed').count()
    failed_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'failed').count()
    
    # Job queue (pending + processing)
    queue_jobs = db.query(DiscoveryJob).filter(
        DiscoveryJob.status.in_(['pending', 'processing'])
    ).order_by(DiscoveryJob.created_at.desc()).limit(20).all()
    
    job_queue = [
        JobQueueItem(
            id=job.id,
            keyword=job.keyword,
            region=job.region,
            status=job.status,
            created_at=job.created_at.isoformat() if job.created_at else None,
            last_run=job.last_run.isoformat() if job.last_run else None
        )
        for job in queue_jobs
    ]
    
    # Service status
    services_status = process_manager.get_health_status()
    
    metrics = PipelineMetrics(
        companies_total=companies_total,
        companies_by_status=companies_by_status,
        contacts_total=contacts_total,
        contacts_by_verification=contacts_by_verification,
        verified_count=verified_count,
        pending_jobs=pending_jobs + processing_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs
    )
    
    return DashboardStats(
        metrics=metrics,
        job_queue=job_queue,
        services=services_status
    )


@router.get("/job/{job_id}/companies")
def get_job_companies(job_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Get top companies for a job (by discovery score)."""
    job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
    if not job:
        return {'error': 'Job not found'}
    
    # Find companies that match this job's keyword pattern
    # For now, just get recent companies sorted by score
    companies = db.query(Company).order_by(
        Company.discovery_score.desc()
    ).limit(limit).all()
    
    return {
        'job_id': job_id,
        'keyword': job.keyword,
        'companies': [
            {
                'id': c.id,
                'domain': c.domain,
                'discovery_score': c.discovery_score,
                'status': c.status,
                'tier': 'strong' if c.discovery_score >= 8 else 'good' if c.discovery_score >= 5 else 'weak'
            }
            for c in companies
        ]
    }