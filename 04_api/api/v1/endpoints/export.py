"""
Export API endpoints for contacts and metrics.
"""
from typing import Optional, Union
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session

from database import get_db, Contact, Company, DiscoveryJob

router = APIRouter(prefix="/export", tags=["Export"])


@router.get("/emails")
def export_emails(
    format: str = Query("txt", description="Export format: csv or txt"),
    is_verified: bool = Query(True, description="Only verified emails"),
    limit: Union[int, str] = Query("all", description="Number of records or 'all'"),
    search: Optional[str] = Query(None, description="Search keywords (space-separated)"),
    db: Session = Depends(get_db)
):
    """Export contacts as CSV or TXT file."""
    
    query = db.query(Contact.email).filter(
        Contact.email.isnot(None),
        Contact.email != ''
    )
    
    if is_verified:
        query = query.filter(Contact.is_verified == True)
    
    if search:
        keywords = search.strip().split()
        if keywords:
            from sqlalchemy import or_
            filters = []
            for kw in keywords:
                if kw:
                    filters.append(Contact.email.ilike(f"%{kw}%"))
            if filters:
                query = query.filter(or_(*filters))
    
    if limit != "all":
        try:
            limit = int(limit)
            query = query.limit(limit)
        except ValueError:
            pass
    
    emails = query.distinct().all()
    email_list = [e[0] for e in emails]
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Generate filename with search filter
    def clean_keyword(kw):
        # Replace special chars with dash, truncate to 15 chars
        kw = kw.replace('@', '-').replace('.', '-')
        return kw[:15]
    
    def make_filename(base, ext):
        if search and search.strip():
            keywords = search.strip().split()[:5]  # max 5 keywords
            cleaned = [clean_keyword(kw) for kw in keywords if kw]
            filter_part = '_'.join(cleaned)
            # Truncate total filter part to 20 chars
            filter_part = filter_part[:20]
            return f"{base}_{filter_part}_{today}.{ext}"
        return f"{base}_{today}.{ext}"
    
    if format == "csv":
        content = "email\n" + "\n".join(email_list)
        filename = make_filename("emails", "csv")
        return PlainTextResponse(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    else:
        content = "\n".join(email_list)
        filename = make_filename("emails", "txt")
        return PlainTextResponse(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )


@router.get("/emails/preview")
def preview_emails(
    is_verified: bool = Query(True),
    limit: int = Query(50, ge=1, le=5000),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Preview emails - returns JSON with total count."""
    
    base_query = db.query(Contact.email).filter(
        Contact.email.isnot(None),
        Contact.email != ''
    )
    
    if is_verified:
        base_query = base_query.filter(Contact.is_verified == True)
    
    if search:
        keywords = search.strip().split()
        if keywords:
            from sqlalchemy import or_
            filters = []
            for kw in keywords:
                if kw:
                    filters.append(Contact.email.ilike(f"%{kw}%"))
            if filters:
                base_query = base_query.filter(or_(*filters))
    
    # Get total count
    total_count = base_query.distinct().count()
    
    # Get limited results
    emails = base_query.distinct().limit(limit).all()
    email_list = [e[0] for e in emails]
    
    return JSONResponse({"count": total_count, "emails": email_list})


@router.get("/emails/jobs")
def get_jobs_for_export(
    limit: int = Query(10),
    db: Session = Depends(get_db)
):
    """Get recent jobs for autocomplete."""
    jobs = db.query(DiscoveryJob).order_by(
        DiscoveryJob.created_at.desc()
    ).limit(limit).all()
    return [{"id": j.id, "keyword": j.keyword, "region": j.region, "created_at": j.created_at.isoformat() if j.created_at else None} for j in jobs]