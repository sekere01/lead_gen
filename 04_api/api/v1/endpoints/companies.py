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

from database import get_db, Company

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["Companies"])


class CompanyResponse(BaseModel):
    id: int
    name: str
    domain: str
    industry: Optional[str]
    discovery_score: int
    status: str
    is_active: bool
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
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db)
):
    """List companies with pagination, search, and optional filtering."""
    try:
        query = db.query(Company)
        if status:
            query = query.filter(Company.status == status)
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
        items = query.order_by(Company.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        return PaginatedCompanies(items=items, total=total, page=page, pages=pages, limit=limit)
    except Exception as e:
        logger.error(f"Error listing companies: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get a specific company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Company {company_id} not found")
        raise HTTPException(status_code=404, detail="Company not found")
    logger.debug(f"Company {company_id}: {company.domain}")
    return company
