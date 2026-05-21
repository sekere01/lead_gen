"""
Companies API endpoints.
"""
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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


@router.get("")  # response_model removed for error handling
def list_companies(
    status: Optional[str] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """List companies with optional filtering."""
    try:
        query = db.query(Company)
        if status:
            query = query.filter(Company.status == status)
        return query.order_by(Company.created_at.desc()).limit(limit).all()
    except Exception as e:
        logger.error(f"Error listing companies: {e}")
        return []


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get a specific company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        logger.warning(f"Company {company_id} not found")
        raise HTTPException(status_code=404, detail="Company not found")
    logger.debug(f"Company {company_id}: {company.domain}")
    return company
