"""
Browsing Service - Main entry point.
Polls Company for status='discovered' AND discovery_score >= 2.
Browses homepage, extracts signals, calculates score.
Entry: python main.py
"""
import time
import logging
from datetime import datetime, timedelta

from database import SessionLocal, init_db, Company, Contact, ExtractedEmail
from config import settings
from services.browser import browse_homepage, extract_emails_from_html
from services.signal_extractor import extract_signals, apply_score, get_tier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | browser | %(message)s'
)
logger = logging.getLogger("browser")

POLL_INTERVAL = settings.BROWSING_POLL_INTERVAL
MAX_RETRIES = settings.BROWSING_MAX_RETRIES
WATCHDOG_MINUTES = settings.BROWSING_WATCHDOG_MINUTES
SCORE_MAX = settings.SCORE_MAX
HEARTBEAT_INTERVAL = settings.HEARTBEAT_INTERVAL


def update_heartbeat(company, db) -> None:
    """Update company browse heartbeat."""
    company.browse_heartbeat = datetime.now()
    db.commit()


def save_emails(company_id: int, emails: list, domain: str, db) -> int:
    """Save extracted emails to contacts table."""
    if not emails:
        return 0
    
    saved = 0
    for email in emails:
        try:
            existing = db.query(Contact).filter(Contact.email == email).first()
            if not existing:
                contact = Contact(
                    first_name='Unknown',
                    last_name='Unknown',
                    email=email,
                    company_id=company_id,
                    verification_status='pending',
                    is_verified=False,
                    source_url=f"https://{domain}"
                )
                db.add(contact)
                
                extracted = ExtractedEmail(
                    email=email,
                    email_type='homepage_browse',
                    source_url=f"https://{domain}",
                    company_id=company_id
                )
                db.add(extracted)
                saved += 1
        except Exception as e:
            logger.debug(f"Error saving email {email}: {e}")
            continue
    
    if saved > 0:
        db.commit()
        logger.info(f"Saved {saved} emails for {domain}")
    
    return saved


def process_company(company, db) -> bool:
    """Process a single company - browse homepage and extract signals."""
    domain = company.domain
    company.status = 'browsing'
    company.browse_heartbeat = datetime.now()
    db.commit()
    
    last_heartbeat_time = time.time()
    start_time = time.time()
    
    try:
        logger.info(f"Processing {domain}")
        
        # Browse homepage
        html = browse_homepage(domain)
        
        if not html:
            logger.warning(f"No content for {domain}")
            company.status = 'discovered'
            company.failure_reason = 'No content fetched'
            db.commit()
            return False
        
        # Check for parked
        signals = extract_signals(html, domain)
        
        if signals.get('is_parked'):
            company.is_parked = True
            company.discovery_score = 0
            company.status = 'browsed'
            company.browse_heartbeat = None
            company.failure_reason = 'Parked domain'
            db.commit()
            logger.info(f"Company {domain} is parked - filtered out")
            return True
        
        # Extract emails
        emails = extract_emails_from_html(html)
        if emails:
            save_emails(company.id, emails, domain, db)
        
        # Calculate score
        base_score = company.discovery_score or 1
        final_score = apply_score(signals, base_score)
        
        # Cap at max
        if final_score > SCORE_MAX:
            final_score = SCORE_MAX
        
        tier = get_tier(final_score, SCORE_MAX)
        
        # Update company
        company.has_contact_link = signals.get('has_contact_link', False)
        company.has_address = signals.get('has_address', False)
        company.has_social_links = signals.get('has_social_links', False)
        company.has_email_on_homepage = signals.get('has_email_on_homepage', False)
        company.is_parked = signals.get('is_parked', False)
        company.language_match = signals.get('language_match', False)
        company.discovery_score = final_score
        company.status = 'browsed'
        company.browse_heartbeat = None
        company.last_heartbeat = None
        db.commit()
        
        logger.info(f"Company {domain}: score={final_score} ({tier})")
        return True
        
    except Exception as e:
        logger.error(f"Error processing {domain}: {e}")
        return False


def watchdog_reset_stuck_companies(db) -> int:
    """Watchdog: Reset companies stuck in browsing for too long."""
    cutoff_time = datetime.now() - timedelta(minutes=WATCHDOG_MINUTES)
    
    stuck = db.query(Company).filter(
        Company.status == 'browsing',
        Company.browse_heartbeat < cutoff_time
    ).all()
    
    reset_count = 0
    for company in stuck:
        old_retry = company.retry_count or 0
        company.retry_count = old_retry + 1
        
        if company.retry_count >= MAX_RETRIES:
            company.status = 'failed'
            company.failure_reason = f'Watchdog: stuck >{WATCHDOG_MINUTES}min, max retries exceeded'
            logger.error(f"Company {company.domain} permanently failed")
        else:
            company.status = 'discovered'
            company.failure_reason = f'Watchdog: stuck >{WATCHDOG_MINUTES}min, retry {company.retry_count}/{MAX_RETRIES}'
            logger.warning(f"Company {company.domain} reset by watchdog")
        
        reset_count += 1
    
    if reset_count > 0:
        db.commit()
        logger.info(f"Watchdog reset {reset_count} stuck companies")
    
    return reset_count


def run_browser():
    """Main watcher loop."""
    logger.info(f"Browsing service started (poll: {POLL_INTERVAL}s, watchdog: {WATCHDOG_MINUTES}min, max: {SCORE_MAX})")
    
    while True:
        db = SessionLocal()
        try:
            watchdog_reset_stuck_companies(db)
            
            companies = db.query(Company).filter(
                Company.status == 'discovered',
                Company.discovery_score >= 2,
                Company.retry_count < MAX_RETRIES
            ).order_by(Company.discovery_score.desc()).limit(20).all()
            
            if not companies:
                logger.debug("No companies to browse, waiting...")
                time.sleep(POLL_INTERVAL)
                continue
            
            logger.info(f"Found {len(companies)} companies to browse")
            
            for company in companies:
                try:
                    process_company(company, db)
                except Exception as e:
                    logger.error(f"Error processing {company.domain}: {e}")
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            logger.error(f"Browser error: {e}")
            time.sleep(POLL_INTERVAL)
        finally:
            db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Browsing Service Starting...")
    print("=" * 50)
    init_db()
    run_browser()