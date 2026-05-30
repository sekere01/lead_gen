"""
Sky Email Sorter — MX-based email classification, sorting, and export.
"""
import io
import zipfile
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db, EmailList
from shared_models import Contact
from services.sorter_service import (
    extract_mx_domain, bulk_resolve_mx, update_contact_provider,
)
from utils.email_utils import classify_provider, PROVIDER_MAP

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sorter", tags=["Sorter"])


class ProviderBreakdown(BaseModel):
    provider: str
    total: int
    verified: int


class ProviderBreakdownResponse(BaseModel):
    breakdown: List[ProviderBreakdown]
    total_contacts: int


class ProcessResponse(BaseModel):
    processed: int
    classified: int
    failed: int
    by_provider: dict


class DomainItem(BaseModel):
    domain: str
    mx_domain: str
    provider: str
    count: int


class ExportResponse(BaseModel):
    success: bool
    message: str
    providers: List[str]
    total_emails: int


class DedupResponse(BaseModel):
    removed: int
    kept: int


class TagRequest(BaseModel):
    contact_ids: List[int]
    tag: str


class TagResponse(BaseModel):
    tagged: int


@router.get("/stats")
def get_sorter_stats(db: Session = Depends(get_db)):
    """Get sorter processing counts — unresolved, unclassified, duplicates."""
    from sqlalchemy import text as sql_text
    total = db.query(Contact).count()
    unresolved = db.query(Contact).filter(
        (Contact.mx_domain.is_(None)) | (Contact.mx_domain == ''),
        (Contact.verification_status.is_(None)) | (Contact.verification_status == 'pending')
    ).count()
    unclassified = db.query(Contact).filter(
        Contact.mx_domain.isnot(None), Contact.mx_domain != '',
        (Contact.provider.is_(None) | (Contact.provider == ''))
    ).count()
    dup = db.execute(sql_text(
        "SELECT COUNT(*) - COUNT(DISTINCT LOWER(email)) FROM contacts"
    )).scalar() or 0
    failed = db.query(Contact).filter(
        Contact.verification_status.in_(['invalid_syntax', 'no_mx_records', 'failed'])
    ).count()
    return {
        "total_contacts": total,
        "unresolved": unresolved,
        "unclassified": unclassified,
        "failed": failed,
        "duplicates": dup,
    }


@router.get("/provider-breakdown", response_model=ProviderBreakdownResponse)
def get_provider_breakdown(db: Session = Depends(get_db)):
    """Get email count grouped by provider."""
    rows = db.query(
        func.coalesce(Contact.provider, 'Unknown').label('provider'),
        func.count(Contact.id).label('total'),
        func.count(Contact.id).filter(Contact.is_verified == True).label('verified'),
    ).group_by(func.coalesce(Contact.provider, 'Unknown')).order_by(func.count(Contact.id).desc()).all()

    total = sum(r.total for r in rows)
    breakdown = [ProviderBreakdown(provider=r.provider, total=r.total, verified=r.verified) for r in rows]
    return ProviderBreakdownResponse(breakdown=breakdown, total_contacts=total)


@router.get("/providers")
def get_providers(db: Session = Depends(get_db)):
    """List distinct providers found in contacts."""
    rows = db.query(Contact.provider).filter(
        Contact.provider.isnot(None), Contact.provider != ''
    ).distinct().order_by(Contact.provider).all()
    return {"providers": [r[0] for r in rows]}


@router.get("/domains")
def get_domains(db: Session = Depends(get_db)):
    """List distinct mx_domains with provider and count."""
    rows = db.query(
        Contact.mx_domain, Contact.provider, func.count(Contact.id).label('count')
    ).filter(
        Contact.mx_domain.isnot(None), Contact.mx_domain != ''
    ).group_by(Contact.mx_domain, Contact.provider).order_by(func.count(Contact.id).desc()).limit(100).all()

    items = [DomainItem(domain='', mx_domain=r[0] or '', provider=r[1] or '', count=r[2]) for r in rows]
    return {"domains": items}


@router.get("/contacts/{provider}")
def get_contacts_by_provider(
    provider: str,
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List contacts for a specific provider."""
    query = db.query(Contact).filter(Contact.provider == provider)
    total = query.count()
    contacts = query.order_by(Contact.email).offset(offset).limit(limit).all()

    return {
        "provider": provider,
        "total": total,
        "contacts": [
            {
                "id": c.id,
                "email": c.email,
                "mx_domain": c.mx_domain,
                "is_verified": c.is_verified,
                "verification_status": c.verification_status,
            }
            for c in contacts
        ],
    }


@router.post("/process", response_model=ProcessResponse)
def process_unclassified(db: Session = Depends(get_db)):
    """Bulk-classify contacts that have mx_domain but no provider."""
    contacts = db.query(Contact).filter(
        Contact.mx_domain.isnot(None),
        Contact.mx_domain != '',
        (Contact.provider.is_(None) | (Contact.provider == '')),
    ).limit(1000).all()

    if not contacts:
        return ProcessResponse(processed=0, classified=0, failed=0, by_provider={})

    by_provider = {}
    classified = 0
    failed = 0

    for contact in contacts:
        try:
            provider = classify_provider(contact.mx_domain)
            update_contact_provider(db, contact.id, contact.mx_domain, provider)
            by_provider[provider] = by_provider.get(provider, 0) + 1
            classified += 1
        except Exception as e:
            logger.warning(f"Failed to classify contact {contact.id}: {e}")
            failed += 1

    db.commit()
    return ProcessResponse(
        processed=len(contacts), classified=classified, failed=failed, by_provider=by_provider
    )


@router.post("/resolve-mx", response_model=ProcessResponse)
def resolve_mx_unclassified(db: Session = Depends(get_db)):
    """Resolve MX records for contacts without mx_domain.
    For unverified or pending contacts, runs DNS MX lookup.
    """
    contacts = db.query(Contact).filter(
        (Contact.mx_domain.is_(None) | (Contact.mx_domain == '')),
    ).limit(500).all()

    if not contacts:
        return ProcessResponse(processed=0, classified=0, failed=0, by_provider={})

    # Collect unique email domains
    email_domains = set()
    contact_map = {}
    for c in contacts:
        if '@' in c.email:
            domain = c.email.split('@')[1].lower()
            email_domains.add(domain)
            if domain not in contact_map:
                contact_map[domain] = []
            contact_map[domain].append(c)

    # Bulk resolve MX
    mx_results = bulk_resolve_mx(list(email_domains))

    by_provider = {}
    classified = 0
    failed = 0

    for domain, mx_exchange in mx_results.items():
        for contact in contact_map.get(domain, []):
            try:
                mx_domain = extract_mx_domain(mx_exchange) if mx_exchange else ''
                provider = classify_provider(mx_exchange) if mx_exchange else 'Unknown'
                db.query(Contact).filter(Contact.id == contact.id).update({
                    'mx_domain': mx_domain,
                    'provider': provider,
                })
                by_provider[provider] = by_provider.get(provider, 0) + 1
                classified += 1
            except Exception as e:
                logger.warning(f"Failed to update contact {contact.id}: {e}")
                failed += 1

    db.commit()
    return ProcessResponse(
        processed=len(contacts), classified=classified, failed=failed, by_provider=by_provider
    )


@router.post("/dedup", response_model=DedupResponse)
def dedup_contacts(db: Session = Depends(get_db)):
    """Remove duplicate email addresses (case-insensitive), keeping the oldest."""
    from sqlalchemy import text

    result = db.execute(text("""
        DELETE FROM contacts a USING contacts b
        WHERE a.id > b.id AND LOWER(a.email) = LOWER(b.email)
    """))
    db.commit()
    removed = result.rowcount
    return DedupResponse(removed=removed, kept=db.query(Contact).count() - removed)


@router.get("/export")
def export_by_provider(db: Session = Depends(get_db)):
    """Export contacts grouped by provider as per-provider TXT files in a ZIP."""
    rows = db.query(
        Contact.provider, func.count(Contact.id).label('count')
    ).filter(
        Contact.provider.isnot(None), Contact.provider != ''
    ).group_by(Contact.provider).all()

    if not rows:
        raise HTTPException(status_code=404, detail="No classified contacts to export")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for provider, count in rows:
            contacts = db.query(Contact.email).filter(
                Contact.provider == provider
            ).order_by(Contact.email).all()
            content = '\n'.join(c[0] for c in contacts)
            filename = f"{provider.lower().replace(' ', '_')}.txt"
            zf.writestr(filename, content)

    buf.seek(0)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="emails_by_provider_{datetime.now(timezone.utc).strftime("%Y%m%d")}.zip"'
        }
    )


@router.post("/tags", response_model=TagResponse)
def tag_contacts(payload: TagRequest, db: Session = Depends(get_db)):
    """Tag a list of contacts. Tags are comma-separated, stored as text."""
    count = 0
    for cid in payload.contact_ids:
        contact = db.query(Contact).filter(Contact.id == cid).first()
        if contact:
            existing = (contact.tags or '').split(',')
            if payload.tag not in existing:
                new_tags = ','.join(filter(None, existing + [payload.tag]))
                contact.tags = new_tags
                count += 1
    db.commit()
    return TagResponse(tagged=count)


class ListCreate(BaseModel):
    name: str
    description: Optional[str] = None
    provider_filter: Optional[str] = None
    contact_ids: Optional[List[int]] = None


class ListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    total_emails: int
    provider_breakdown: Optional[dict]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.post("/lists", response_model=ListResponse)
def create_list(payload: ListCreate, db: Session = Depends(get_db)):
    """Save a sorted email list. Either by provider filter or explicit contact IDs."""
    if payload.provider_filter:
        count = db.query(Contact).filter(Contact.provider == payload.provider_filter).count()
        rows = db.query(
            Contact.provider, func.count(Contact.id).label('count')
        ).filter(Contact.provider == payload.provider_filter).group_by(Contact.provider).all()
    elif payload.contact_ids:
        count = db.query(Contact).filter(Contact.id.in_(payload.contact_ids)).count()
        rows = db.query(
            Contact.provider, func.count(Contact.id).label('count')
        ).filter(Contact.id.in_(payload.contact_ids)).group_by(Contact.provider).all()
    else:
        raise HTTPException(status_code=400, detail="provider_filter or contact_ids required")

    breakdown = {r[0]: r[1] for r in rows}
    obj = EmailList(
        name=payload.name,
        description=payload.description,
        total_emails=count,
        provider_breakdown=breakdown,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/lists")
def list_lists(db: Session = Depends(get_db)):
    """List saved email lists."""
    lists = db.query(EmailList).order_by(EmailList.created_at.desc()).limit(50).all()
    return {"lists": lists}


@router.get("/lists/{list_id}/export")
def export_list(list_id: int, db: Session = Depends(get_db)):
    """Export a saved list as per-provider TXT files in a ZIP."""
    lst = db.query(EmailList).filter(EmailList.id == list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    providers = list(lst.provider_breakdown.keys()) if lst.provider_breakdown else []
    if not providers:
        raise HTTPException(status_code=404, detail="No providers in list")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for provider in providers:
            contacts = db.query(Contact.email).filter(Contact.provider == provider).order_by(Contact.email).all()
            content = '\n'.join(c[0] for c in contacts)
            zf.writestr(f"{provider.lower().replace(' ', '_')}.txt", content)

    buf.seek(0)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="{lst.name.lower().replace(" ", "_")}.zip"'
        }
    )


@router.delete("/lists/{list_id}")
def delete_list(list_id: int, db: Session = Depends(get_db)):
    """Delete a saved list."""
    lst = db.query(EmailList).filter(EmailList.id == list_id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    db.delete(lst)
    db.commit()
    return {"ok": True}
