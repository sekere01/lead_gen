"""
Verifier Service - Main entry point.
Polls Contact for verification_status='pending'.
Fast-track verification: Syntax + Disposable + MX → SMTP (5s timeout)
Entry: python main.py
"""
import time
import logging
import logging.handlers
import os
import httpx
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import SessionLocal, init_db, Contact, Company
from sqlalchemy import update, or_
from config import settings

from services.email_verify import verify_email_fast

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

formatter = logging.Formatter('%(asctime)s | %(levelname)s | verifier | %(message)s')

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "verification.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

logger = logging.getLogger("verifier")
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)

POLL_INTERVAL = settings.VERIFIER_POLL_INTERVAL
SMTP_TIMEOUT = settings.SMTP_TIMEOUT

# Persistent HTTP client for API communication
_http_client = httpx.Client()


def verify_contact(contact) -> dict:
    """Verify a single contact. Returns result dict — no db operations (thread-safe).
    Rules 1 & 2: Syntax valid + MX exists → always verified (SMTP skipped for speed)
    Rule 3: Syntax valid + no MX → unverified
    Rule 4: Syntax invalid → unverified
    """
    try:
        result = verify_email_fast(contact.email)

        if not result.get('is_valid_syntax'):
            logger.info(f"Unverified (syntax/noise): {contact.email} -> {result['verification_status']}")
            return {'is_verified': False, 'verification_status': result['verification_status']}

        if not result['has_mx_records']:
            logger.info(f"Unverified (no MX): {contact.email}")
            return {'is_verified': False, 'verification_status': 'no_mx_records'}

        return {'is_verified': True, 'verification_status': 'verified'}

    except Exception as e:
        logger.error(f"Error verifying contact {contact.email}: {e}")
        return {'is_verified': False, 'verification_status': 'failed'}


def check_company_verification(company_id: int, db) -> None:
    """Check if all contacts for a company are verified. Update company status."""
    try:
        pending_count = db.query(Contact).filter(
            Contact.company_id == company_id,
            or_(
                Contact.verification_status == 'pending',
                Contact.verification_status.is_(None)
            )
        ).count()
        
        if pending_count == 0:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company and company.status != 'verified':
                company.status = 'verified'
                db.commit()
                logger.info(f"Company {company.domain} status updated to 'verified'")
    
    except Exception as e:
        logger.error(f"Error checking company verification: {e}")


def write_metrics(db):
    try:
        contacts_total = db.query(Contact).count()
        verified_count = db.query(Contact).filter(Contact.is_verified == True).count()
        invalid_count = db.query(Contact).filter(Contact.verification_status.in_(['invalid_syntax', 'no_mx_records', 'failed'])).count()
        pending_count = db.query(Contact).filter(
            or_(
                Contact.verification_status == 'pending',
                Contact.verification_status.is_(None)
            )
        ).count()
        
        api_base_url = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        metrics = [
            ('verification', 'contacts_total', contacts_total),
            ('verification', 'verified_count', verified_count),
            ('verification', 'invalid_count', invalid_count),
            ('verification', 'pending_count', pending_count),
        ]
        
        for svc, metric, value in metrics:
            try:
                _http_client.post(
                    f"{api_base_url}/dashboard/metrics",
                    json={"service": svc, "metric": metric, "value": value},
                    timeout=5.0,
                )
            except Exception as e:
                logger.debug(f"Failed to write metric {metric}: {e}")
    except Exception as e:
        logger.warning(f"Failed to write metrics: {e}")


def report_verification_progress(total: int, processed: int, verified: int, failed: int, status: str):
    """Send verification progress to the API for WebSocket broadcast."""
    try:
        api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        r = _http_client.post(
            f"{api_base}/dashboard/verification-progress",
            json={
                "total": total,
                "processed": processed,
                "verified": verified,
                "failed": failed,
                "status": status,
            },
            timeout=3.0,
        )
        logger.info(f"Progress POST -> {r.status_code} ({processed}/{total})")
    except Exception as e:
        logger.warning(f"Progress POST failed: {e}")


def run_verifier():
    """Main watcher loop."""
    logger.info(f"Verifier service started (poll interval: {POLL_INTERVAL}s)")
    
    metrics_counter = 0
    total_processed = 0
    total_verified = 0
    total_failed = 0
    total_pending = 0
    
    # Use ThreadPoolExecutor for concurrent processing
    with ThreadPoolExecutor(max_workers=10) as executor:
        while True:
            db = SessionLocal()
            try:
                pending_query = db.query(Contact).filter(
                    or_(
                        Contact.verification_status == 'pending',
                        Contact.verification_status.is_(None)
                    )
                )
                total_pending = pending_query.count()
                contacts = pending_query.limit(200).all()
                
                if contacts:
                    logger.info(f"Found {len(contacts)} contacts to verify")
                    
                    verification_updates = []
                    processed_companies = set()
                    contacts_done = 0
                    
                    CHUNK_SIZE = 10
                    for start_idx in range(0, len(contacts), CHUNK_SIZE):
                        chunk = contacts[start_idx:start_idx + CHUNK_SIZE]
                        
                        future_to_contact = {}
                        for contact in chunk:
                            future = executor.submit(verify_contact, contact)
                            future_to_contact[future] = contact
                        
                        for future in as_completed(future_to_contact):
                            contact = future_to_contact[future]
                            try:
                                result = future.result()
                                if contact.company_id:
                                    processed_companies.add(contact.company_id)
                                verification_updates.append({
                                    'id': contact.id,
                                    'is_verified': result['is_verified'],
                                    'verification_status': result['verification_status']
                                })
                                if result['is_verified']:
                                    total_verified += 1
                                else:
                                    total_failed += 1
                            except Exception as e:
                                logger.error(f"Error verifying contact {contact.email}: {e}")
                                total_failed += 1
                            
                            contacts_done += 1
                            if contacts_done % 5 == 0 or contacts_done == len(contacts):
                                effective_processed = total_processed + contacts_done
                                report_verification_progress(
                                    total=total_pending or effective_processed,
                                    processed=effective_processed,
                                    verified=total_verified,
                                    failed=total_failed,
                                    status="running"
                                )
                    
                    # Bulk update database with verification results
                    if verification_updates:
                        try:
                            for update_data in verification_updates:
                                stmt = update(Contact).where(
                                    Contact.id == update_data['id']
                                ).values(
                                    is_verified=update_data['is_verified'],
                                    verification_status=update_data['verification_status']
                                )
                                db.execute(stmt)
                            db.commit()
                            logger.info(f"Batch update completed: {len(verification_updates)} contacts updated")
                        except Exception as e:
                            logger.error(f"Batch update failed: {e}")
                            db.rollback()
                            return
                    
                    # Update company verification status
                    for company_id in processed_companies:
                        check_company_verification(company_id, db)
                    
                    # Log progress
                    total_processed += len(contacts)
                    logger.info(
                        f"Progress: {total_processed} processed, "
                        f"{total_verified} verified, {total_failed} failed"
                    )
                    
                    # Check if fully complete
                    remaining = db.query(Contact).filter(
                        or_(
                            Contact.verification_status == 'pending',
                            Contact.verification_status.is_(None)
                        )
                    ).count()
                    if remaining == 0:
                        report_verification_progress(
                            total=total_pending or total_processed,
                            processed=total_processed,
                            verified=total_verified,
                            failed=total_failed,
                            status="completed"
                        )
                else:
                    logger.debug("No contacts to verify, waiting...")
                    if total_processed > 0:
                        report_verification_progress(
                            total=total_pending or total_processed,
                            processed=total_processed,
                            verified=total_verified,
                            failed=total_failed,
                            status="completed"
                        )
                
                # Write metrics every 60 seconds
                metrics_counter += POLL_INTERVAL if not contacts else 5
                if metrics_counter >= 60:
                    write_metrics(db)
                    metrics_counter = 0
                
                if contacts:
                    time.sleep(0.5)
                else:
                    time.sleep(POLL_INTERVAL)
                
            except Exception as e:
                logger.error(f"Verifier error: {e}")
                time.sleep(POLL_INTERVAL)
            finally:
                db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Verification Service Starting...")
    print("=" * 50)
    init_db()
    run_verifier()
