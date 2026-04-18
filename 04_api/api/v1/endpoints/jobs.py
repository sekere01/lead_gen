"""
Discovery Jobs API endpoints.
"""
import traceback
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from database import get_db, init_db, DiscoveryJob, JobTemplate, engine

router = APIRouter(prefix="/discovery-jobs", tags=["Discovery Jobs"])
logger = logging.getLogger(__name__)


@router.get("/_test-db")
def test_db():
    """Test database connection."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test")).scalar()
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"DB test failed: {e}")
        return {"status": "error", "error": str(e)}


class JobCreate(BaseModel):
    keyword: str
    region: str = "Global"


class JobUpdate(BaseModel):
    status: Optional[str] = None


class TemplateCreate(BaseModel):
    name: str
    keyword: str
    region: str = "Global"


class JobTemplateUse(BaseModel):
    keyword: str
    region: str = "Global"


class JobResponse(BaseModel):
    id: int
    keyword: str
    region: str
    status: str
    results_count: int
    retry_count: int
    error_message: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.post("", response_model=JobResponse)
def create_job(job: JobCreate, db: Session = Depends(get_db)):
    """Create a new discovery job."""
    logger.info(f"Creating job: {job.keyword} ({job.region})")
    try:
        existing = db.query(DiscoveryJob).filter(
            DiscoveryJob.keyword == job.keyword,
            DiscoveryJob.region == job.region
        ).first()
        
        if existing:
            logger.info(f"Found existing job {existing.id}, resetting to pending")
            existing.status = 'pending'
            existing.error_message = None
            db.commit()
            db.refresh(existing)
            return existing
        
        logger.info("Creating new job record")
        new_job = DiscoveryJob(
            keyword=job.keyword,
            region=job.region,
            status='pending'
        )
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        logger.info(f"Created job {new_job.id}")
        return new_job
    except Exception as e:
        logger.error(f"Failed to create job: {e}\n{traceback.format_exc()}")
        raise


@router.get("")  # response_model removed for error handling
def list_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """List discovery jobs with optional filtering."""
    try:
        query = db.query(DiscoveryJob)
        if status:
            query = query.filter(DiscoveryJob.status == status)
        return query.order_by(DiscoveryJob.created_at.desc()).limit(limit).all()
    except Exception as e:
        # Return empty list on error instead of 500
        return []


@router.post("/templates")
def create_template(template: TemplateCreate, db: Session = Depends(get_db)):
    """Create a new job template."""
    existing = db.query(JobTemplate).filter(
        JobTemplate.name == template.name
    ).first()
    
    if existing:
        existing.keyword = template.keyword
        existing.region = template.region
        db.commit()
        db.refresh(existing)
        return existing
    
    new_template = JobTemplate(
        name=template.name,
        keyword=template.keyword,
        region=template.region
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return new_template


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    """List all job templates."""
    return db.query(JobTemplate).order_by(JobTemplate.name.asc()).all()


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    """Delete a job template."""
    template = db.query(JobTemplate).filter(JobTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"deleted": template_id}


@router.post("/templates/{template_id}/use")
def use_template(template_id: int, use: JobTemplateUse, db: Session = Depends(get_db)):
    """Use a template to create a job."""
    template = db.query(JobTemplate).filter(JobTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    existing = db.query(DiscoveryJob).filter(
        DiscoveryJob.keyword == use.keyword,
        DiscoveryJob.region == use.region
    ).first()
    
    if existing:
        existing.status = 'pending'
        existing.error_message = None
        db.commit()
        db.refresh(existing)
        return existing
    
    new_job = DiscoveryJob(
        keyword=use.keyword,
        region=use.region,
        status='pending'
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get a specific discovery job."""
    job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=JobResponse)
def update_job(job_id: int, update: JobUpdate, db: Session = Depends(get_db)):
    """Update a discovery job (retry failed job)."""
    job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if update.status:
        job.status = update.status
        if update.status == 'pending':
            job.retry_count = 0
            job.error_message = None
    
    db.commit()
    db.refresh(job)
    return job


@router.delete("/pending/clear")
def clear_pending_jobs(db: Session = Depends(get_db)):
    """Clear all pending discovery jobs."""
    deleted = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').delete()
    db.commit()
    return {"deleted": deleted}


@router.delete("/failed/clear")
def clear_failed_jobs(db: Session = Depends(get_db)):
    """Clear all failed discovery jobs."""
    deleted = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'failed').delete()
    db.commit()
    return {"deleted": deleted}


class BulkJobCreate(BaseModel):
    keywords: List[str]
    region: str = "Global"

    @classmethod
    def validate(cls, v):
        if len(v.keywords) > 100:
            raise ValueError('Maximum 100 keywords per bulk request')
        return v


@router.post("/bulk")
def create_bulk_jobs(jobs: BulkJobCreate, db: Session = Depends(get_db)):
    """Create multiple discovery jobs at once."""
    created = 0
    skipped = 0
    for keyword in jobs.keywords:
        existing = db.query(DiscoveryJob).filter(
            DiscoveryJob.keyword == keyword,
            DiscoveryJob.region == jobs.region
        ).first()
        
        if existing:
            existing.status = 'pending'
            existing.error_message = None
            db.commit()
            db.refresh(existing)
            skipped += 1
        else:
            new_job = DiscoveryJob(
                keyword=keyword,
                region=jobs.region,
                status='pending'
            )
            db.add(new_job)
            db.commit()
            db.refresh(new_job)
            created += 1
    
    return {"created": created, "skipped": skipped, "total": len(jobs.keywords)}


@router.get("/queue")
def get_job_queue(db: Session = Depends(get_db)):
    """Get all pending jobs in the queue."""
    jobs = db.query(DiscoveryJob).filter(
        DiscoveryJob.status == 'pending'
    ).order_by(DiscoveryJob.created_at.asc()).all()
    return jobs



