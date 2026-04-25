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
from datetime import datetime

from database import SessionLocal, init_db, Contact, Company
from sqlalchemy import update
from config import settings

from services.email_verify import verify_email_fast
from services.verification import verify_email

LOG_DIR = os.getenv("LOG_DIR", "/home/fisazkido/lead_gen2/logs")
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
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)

logger = logging.getLogger("verifier")
logger.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)

POLL_INTERVAL = settings.VERIFIER_POLL_INTERVAL
SMTP_TIMEOUT = settings.SMTP_TIMEOUT


def verify_contact(contact, db) -> bool:
    """Verify a single contact using fast-track + SMTP bonus."""
    try:
        logger.info(f"Verifying contact: {contact.email}")
        
        result = verify_email_fast(contact.email)
        
        contact.is_verified = result['is_verified']
        contact.verification_status = result['verification_status']
        
        if result['is_verified']:
            logger.info(f"Fast-track verified: {contact.email} -> {result['verification_status']}")
            db.commit()
            return True
        
        if result.get('has_mx_records') and not result['is_verified']:
            logger.info(f"MX valid but fast-track failed, trying SMTP bonus for: {contact.email}")
            
            try:
                smtp_result = verify_email(contact.email)
                
                if smtp_result.get('is_deliverable'):
                    contact.is_verified = True
                    contact.verification_status = 'needs_retry'
                    logger.info(f"SMTP bonus success: {contact.email}")
                elif smtp_result.get('has_mx_records'):
                    contact.is_verified = True
                    contact.verification_status = 'needs_retry'
                    logger.info(f"SMTP timeout but MX valid: {contact.email}")
                else:
                    contact.verification_status = 'failed'
                    logger.warning(f"SMTP failed: {contact.email}")
                    
            except Exception as e:
                logger.error(f"SMTP verification error for {contact.email}: {e}")
                contact.verification_status = 'needs_retry'
                contact.is_verified = True
        
        db.commit()
        return True
        
    except Exception as e:
        logger.error(f"Error verifying contact {contact.email}: {e}")
        contact.verification_status = 'failed'
        db.commit()
        return False


def check_company_verification(company_id: int, db) -> None:
    """Check if all contacts for a company are verified. Update company status."""
    try:
        pending_count = db.query(Contact).filter(
            Contact.company_id == company_id,
            Contact.verification_status == 'pending'
        ).count()
        
        if pending_count == 0:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company and company.status != 'verified':
                company.status = 'verified'
                db.commit()
                logger.info(f"Company {company.domain} status updated to 'verified'")
    
    except Exception as e:
        logger.error(f"Error checking company verification: {e}")


def run_verifier():
    """Main watcher loop."""
    logger.info(f"Verifier service started (poll interval: {POLL_INTERVAL}s)")
    
    while True:
        db = SessionLocal()
        try:
            contacts = db.query(Contact).filter(
                Contact.verification_status == 'pending'
            ).limit(50).all()
            
            if not contacts:
                logger.debug("No contacts to verify, waiting...")
                time.sleep(POLL_INTERVAL)
                continue
            
            logger.info(f"Found {len(contacts)} contacts to verify")
            
            verification_updates = []
            processed_companies = set()
            
            for contact in contacts:
                success = verify_contact(contact, db)
                
                if success and contact.company_id:
                    processed_companies.add(contact.company_id)
                    verification_updates.append({
                        'id': contact.id,
                        'is_verified': contact.is_verified,
                        'verification_status': contact.verification_status
                    })
            
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
            
            for company_id in processed_companies:
                check_company_verification(company_id, db)
            
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
