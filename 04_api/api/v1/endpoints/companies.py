"""
Companies API endpoints.
"""
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db, Company, Contact
from sqlalchemy import func as sqlfunc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["Companies"])


class CompanyResponse(BaseModel):
    id: int
    name: str
    domain: str
    industry: Optional[str]
    lead_source: Optional[str] = None
    discovery_score: int
    status: str
    is_active: bool
    contact_count: int = 0
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class PaginatedCompanies(BaseModel):
    items: List[CompanyResponse]
    total: int
    page: int
    pages: int
    limit: int


@router.get("", response_model=PaginatedCompanies)
def list_companies(
    status: Optional[str] = Query(None),
    lead_source: Optional[str] = Query(None),
    has_failure: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(500, ge=1, le=5000),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query("desc"),
    db: Session = Depends(get_db)
):
    """List companies with pagination, search, and optional filtering."""
    try:
        query = db.query(Company)
        if status:
            query = query.filter(Company.status == status)
        if has_failure:
            query = query.filter(Company.failure_reason.isnot(None))
        if lead_source:
            query = query.filter(Company.lead_source == lead_source)
        if search:
            term = f"%{search}%"
            query = query.filter(
                or_(
                    Company.domain.ilike(term),
                    Company.industry.ilike(term),
                    Company.name.ilike(term),
                )
            )
        total = query.count()
        pages = max(1, (total + limit - 1) // limit)
        SORTABLE_COLUMNS = {
            'domain': Company.domain,
            'industry': Company.industry,
            'status': Company.status,
            'lead_source': Company.lead_source,
            'discovery_score': Company.discovery_score,
            'created_at': Company.created_at,
        }
        if sort_by == 'contact_count':
            contact_subq = (
                db.query(Contact.company_id, sqlfunc.count(Contact.id).label('cnt'))
                .group_by(Contact.company_id)
                .subquery()
            )
            query = query.outerjoin(
                contact_subq,
                contact_subq.c.company_id == Company.id
            ).order_by(
                sqlfunc.coalesce(contact_subq.c.cnt, 0).desc()
                if sort_order == 'desc'
                else sqlfunc.coalesce(contact_subq.c.cnt, 0).asc()
            )
        elif sort_by and sort_by in SORTABLE_COLUMNS:
            col = SORTABLE_COLUMNS[sort_by]
            order = col.desc() if sort_order == 'desc' else col.asc()
            query = query.order_by(order)
        else:
            query = query.order_by(Company.created_at.desc())
        items = query.offset((page - 1) * limit).limit(limit).all()
        company_ids = [c.id for c in items]
        if company_ids:
            counts = db.query(Contact.company_id, sqlfunc.count(Contact.id)).filter(
                Contact.company_id.in_(company_ids)
            ).group_by(Contact.company_id).all()
            count_map = {c_id: cnt for c_id, cnt in counts}
            for c in items:
                c.contact_count = count_map.get(c.id, 0)
        return PaginatedCompanies(items=items, total=total, page=page, pages=pages, limit=limit)
    except Exception as e:
        logger.error(f"Error listing companies: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


class BatchCompanyIds(BaseModel):
    company_ids: List[int]


@router.post("/batch/requeue")
def batch_requeue_companies(req: BatchCompanyIds, db: Session = Depends(get_db)):
    """Requeue multiple companies by resetting status to 'discovered'."""
    try:
        count = db.query(Company).filter(Company.id.in_(req.company_ids)).update(
            {"status": "discovered", "retry_count": 0},
            synchronize_session=False
        )
        db.commit()
        logger.info(f"Batch requeued {count} companies")
        return {"requeued": count}
    except Exception as e:
        logger.exception("Batch requeue companies failed")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch/delete")
def batch_delete_companies(req: BatchCompanyIds, db: Session = Depends(get_db)):
    """Delete multiple companies and their contacts and extracted emails."""
    try:
        from database import Contact, ExtractedEmail
        db.query(ExtractedEmail).filter(ExtractedEmail.company_id.in_(req.company_ids)).delete(
            synchronize_session=False
        )
        contact_count = db.query(Contact).filter(Contact.company_id.in_(req.company_ids)).delete(
            synchronize_session=False
        )
        company_count = db.query(Company).filter(Company.id.in_(req.company_ids)).delete(
            synchronize_session=False
        )
        db.commit()
        logger.info(f"Batch deleted {company_count} companies, {contact_count} contacts")
        return {"companies_deleted": company_count, "contacts_deleted": contact_count}
    except Exception as e:
        logger.exception("Batch delete companies failed")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get a specific company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Company {company_id} not found")
        raise HTTPException(status_code=404, detail="Company not found")
    logger.debug(f"Company {company_id}: {company.domain}")
    return company
