"""
Verification API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/verification", tags=["Verification"])


class EmailVerifyRequest(BaseModel):
    email: str


class EmailVerifyResponse(BaseModel):
    email: str
    is_verified: bool
    verification_status: str
    is_valid_syntax: bool
    is_disposable: bool
    has_mx_records: bool


@router.post("/verify-single", response_model=EmailVerifyResponse)
def verify_single_email(request: EmailVerifyRequest, db=None):
    """Verify a single email address."""
    try:
        from services.email_verify import verify_email_fast
        
        result = verify_email_fast(request.email)
        
        return EmailVerifyResponse(
            email=request.email,
            is_verified=result['is_verified'],
            verification_status=result['verification_status'],
            is_valid_syntax=result['is_valid_syntax'],
            is_disposable=result['is_disposable'],
            has_mx_records=result['has_mx_records']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
