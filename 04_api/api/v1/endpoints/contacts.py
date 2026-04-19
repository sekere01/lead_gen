"""
Contacts API endpoints.
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, Contact

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
        return []


@router.get("/{contact_id}", response_model=ContactResponse)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    """Get a specific contact."""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact