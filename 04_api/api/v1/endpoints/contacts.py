"""
Contacts API endpoints.
"""
import asyncio
import csv
import io
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db, Contact, Company, SessionLocal
from services.email_verify import verify_email_fast
from api.v1.endpoints.dashboard import broadcast_update

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["Contacts"])


class ContactResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    job_title: Optional[str]
    is_verified: bool
    verification_status: Optional[str]
    company_id: int
    created_at: Optional[datetime]
    
    class Config:
        from_attributes = True


@router.get("")
def list_contacts(
    status: Optional[str] = Query(None, alias="verification_status"),
    is_verified: Optional[bool] = Query(None),
    company_id: Optional[int] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """List contacts with optional filtering."""
    try:
        query = db.query(Contact)
        if status:
            query = query.filter(Contact.verification_status == status)
        if is_verified is not None:
            query = query.filter(Contact.is_verified == is_verified)
        if company_id:
            query = query.filter(Contact.company_id == company_id)
        return query.order_by(Contact.created_at.desc()).limit(limit).all()
    except Exception as e:
        logger.error(f"Error listing contacts: {e}")
        return []


@router.get("/{contact_id}", response_model=ContactResponse)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    """Get a specific contact."""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        logger.warning(f"Contact {contact_id} not found")
        raise HTTPException(status_code=404, detail="Contact not found")
    logger.debug(f"Contact {contact_id}: {contact.email}")
    return contact


class ImportRequest(BaseModel):
    text: str
    format: str = "txt"


class ImportResult(BaseModel):
    imported: int
    skipped: int
    failed: list
    total: int
    companies_created: int


EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


@router.post("/import", response_model=ImportResult)
def import_contacts(req: ImportRequest, db: Session = Depends(get_db)):
    """Import contacts from pasted text or CSV content.

    TXT format: one email per line.
    CSV format: must include an 'email' column.
    Duplicate emails (case-insensitive) are skipped.
    Companies are auto-created from email domains when missing.
    """
    try:
        if req.format == "csv":
            rows = list(csv.DictReader(io.StringIO(req.text)))
        else:
            rows = [{"email": line.strip()} for line in req.text.split("\n") if line.strip()]

        # Phase 1 — validate all emails
        valid_emails = []
        failed = []
        for row in rows:
            email = row.get("email", "").strip().lower()
            if not email:
                continue
            if not EMAIL_RE.match(email):
                failed.append({"email": email, "reason": "Invalid email format"})
                continue
            valid_emails.append(email)

        # Phase 2 — company lookup / creation for all unique domains
        domains = set(e.split("@")[1] for e in valid_emails)
        existing_companies = {
            c.domain: c for c in
            db.query(Company).filter(Company.domain.in_(domains)).all()
        }
        companies_to_create = []
        for domain in domains:
            if domain not in existing_companies:
                c = Company(
                    name=domain.replace(".", " ").title(),
                    domain=domain,
                    status="discovered",
                    lead_source="manual",
                )
                companies_to_create.append(c)
        if companies_to_create:
            db.add_all(companies_to_create)
            db.flush()
            for c in companies_to_create:
                existing_companies[c.domain] = c
        companies_created = len(companies_to_create)

        # Phase 3 — bulk insert with ON CONFLICT DO NOTHING (atomic dedup)
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        contact_dicts = []
        for email in valid_emails:
            company = existing_companies.get(email.split("@")[1])
            if not company:
                continue
            local_part = email.split("@")[0]
            name_parts = re.split(r"[._\-+]", local_part)
            first_name = name_parts[0].capitalize() if name_parts else "Unknown"
            last_name = " ".join(p.capitalize() for p in name_parts[1:]) if len(name_parts) > 1 else "Imported"
            contact_dicts.append({
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'company_id': company.id,
                'source': 'imported',
                'verification_status': 'pending',
            })

        imported = 0
        if contact_dicts:
            stmt = pg_insert(Contact.__table__).values(contact_dicts)
            stmt = stmt.on_conflict_do_nothing()
            result = db.execute(stmt)
            imported = result.rowcount if result.rowcount >= 0 else len(contact_dicts)

        db.commit()
        skipped = len(valid_emails) - imported

        logger.info(
            f"Import complete: {imported} imported, {skipped} skipped, "
            f"{len(failed)} failed, {companies_created} companies created"
        )
        return ImportResult(
            imported=imported,
            skipped=skipped,
            failed=failed[:20],
            total=len(rows),
            companies_created=companies_created,
        )

    except Exception as e:
        logger.exception("Contact import failed")
        raise HTTPException(status_code=500, detail=str(e))


class BatchVerifyRequest(BaseModel):
    source: Optional[str] = None
    company_id: Optional[int] = None


class BatchVerifyJob(BaseModel):
    job_id: str
    status: str
    total: int
    processed: int
    verified: int
    failed_count: int
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


_BATCH_SIZE = 200
_MAX_WORKERS = 5
verify_jobs: Dict[str, dict] = {}


@router.post("/verify-batch", response_model=BatchVerifyJob)
async def start_batch_verify(req: BatchVerifyRequest, db: Session = Depends(get_db)):
    """Start async batch verification of pending contacts."""
    try:
        from sqlalchemy import or_
        query = db.query(Contact.id).filter(
            or_(
                Contact.verification_status == 'pending',
                Contact.verification_status.is_(None)
            )
        )
        if req.source:
            query = query.filter(Contact.source == req.source)
        if req.company_id:
            query = query.filter(Contact.company_id == req.company_id)

        total = query.count()
        if total == 0:
            return BatchVerifyJob(
                job_id="", status="completed", total=0,
                processed=0, verified=0, failed_count=0,
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

        contact_ids = [row[0] for row in query.all()]
        now = datetime.now(timezone.utc)
        job_id = str(uuid.uuid4())

        job = {
            "job_id": job_id,
            "status": "running",
            "total": total,
            "processed": 0,
            "verified": 0,
            "failed_count": 0,
            "created_at": now,
            "completed_at": None,
            "error": None,
            "contact_ids": contact_ids,
            "cancelled": False,
        }
        verify_jobs[job_id] = job

        asyncio.get_running_loop().create_task(_run_batch_verify(job_id))

        return BatchVerifyJob(
            job_id=job_id, status="running", total=total,
            processed=0, verified=0, failed_count=0,
            created_at=now,
        )

    except Exception as e:
        logger.exception("Failed to start batch verification")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verify-batch/{job_id}", response_model=BatchVerifyJob)
def get_batch_verify_status(job_id: str):
    """Poll batch verification job progress."""
    job = verify_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return BatchVerifyJob(
        job_id=job["job_id"], status=job["status"],
        total=job["total"], processed=job["processed"],
        verified=job["verified"], failed_count=job["failed_count"],
        created_at=job["created_at"], completed_at=job.get("completed_at"),
        error=job.get("error"),
    )


@router.delete("/verify-batch/{job_id}")
def cancel_batch_verify(job_id: str):
    """Cancel a running batch verification job."""
    job = verify_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "running":
        raise HTTPException(status_code=400, detail="Job is not running")
    job["cancelled"] = True
    return {"message": "Cancellation requested", "job_id": job_id}


async def _run_batch_verify(job_id: str):
    """Background task: verify pending contacts in chunks via thread pool."""
    job = verify_jobs.get(job_id)
    if not job:
        return

    contact_ids = job["contact_ids"]
    db = SessionLocal()
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    loop = asyncio.get_running_loop()

    try:
        for offset in range(0, len(contact_ids), _BATCH_SIZE):
            if job.get("cancelled"):
                job["status"] = "cancelled"
                job["completed_at"] = datetime.now(timezone.utc)
                break

            batch_ids = contact_ids[offset:offset + _BATCH_SIZE]
            contacts = db.query(Contact).filter(Contact.id.in_(batch_ids)).all()

            tasks = [
                loop.run_in_executor(pool, verify_email_fast, c.email)
                for c in contacts
            ]
            results = await asyncio.gather(*tasks)

            updates = []
            v_count = 0
            f_count = 0
            for contact, result in zip(contacts, results):
                updates.append({
                    "id": contact.id,
                    "is_verified": result["is_verified"],
                    "verification_status": result["verification_status"],
                })
                if result["is_verified"]:
                    v_count += 1
                else:
                    f_count += 1

            if updates:
                db.bulk_update_mappings(Contact, updates)
                db.commit()

            job["processed"] += len(contacts)
            job["verified"] += v_count
            job["failed_count"] += f_count

            broadcast_update("verify_batch_progress", {
                "job_id": job_id,
                "status": "running",
                "total": job["total"],
                "processed": job["processed"],
                "verified": job["verified"],
                "failed_count": job["failed_count"],
            })

            await asyncio.sleep(0.5)

        if job["status"] != "cancelled":
            job["status"] = "completed"
            job["completed_at"] = datetime.now(timezone.utc)

    except Exception as e:
        logger.exception(f"Batch verify job {job_id} failed")
        job["status"] = "failed"
        job["error"] = str(e)
        job["completed_at"] = datetime.now(timezone.utc)
    finally:
        pool.shutdown(wait=False)
        db.close()