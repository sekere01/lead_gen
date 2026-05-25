"""
Browsing Service - Main entry point.
Polls Company for status='discovered' or 'requeued'.
Browses homepage, extracts signals, calculates score.
Entry: python main.py
"""
import time
import logging
import logging.handlers
import os
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from database import SessionLocal, init_db, Company, Contact, ExtractedEmail
from config import settings
from shared_models import Base
from services.browser import browse_homepage, extract_emails_from_html
from services.signal_extractor import extract_signals, apply_score, get_tier

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

formatter = logging.Formatter('%(asctime)s | %(levelname)s | browser | %(message)s')

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "browsing.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

logger = logging.getLogger("browser")
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)

POLL_INTERVAL = settings.BROWSING_POLL_INTERVAL
MAX_RETRIES = settings.BROWSING_MAX_RETRIES
MAX_RETRIES_PHASE2 = settings.BROWSING_MAX_RETRIES_PHASE2
WATCHDOG_MINUTES = settings.BROWSING_WATCHDOG_MINUTES
SCORE_MAX = settings.SCORE_MAX
HEARTBEAT_INTERVAL = settings.HEARTBEAT_INTERVAL
BROWSING_WORKERS = 20


def update_heartbeat(company, db):
    """Update company browse heartbeat."""
    company.browse_heartbeat = datetime.now(timezone.utc)
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


def process_company(company_id: int) -> bool:
    """Process a single company - browse homepage and extract signals."""
    with SessionLocal() as db:
        company = db.query(Company).filter(Company.id == company_id).first()
        if not company:
            return False

        domain = company.domain
        original_status = company.status
        company.status = 'browsing'
        company.browse_heartbeat = datetime.now(timezone.utc)
        db.commit()

        try:
            logger.info(f"Processing {domain}")

            # Browse homepage (pass db for heartbeat refresh during long fetches)
            html = browse_homepage(domain, db=db, company_id=company.id)

            if not html:
                company.retry_count = (company.retry_count or 0) + 1

                if original_status == 'requeued':
                    if company.retry_count >= MAX_RETRIES_PHASE2:
                        company.status = 'failed'
                        company.failure_reason = f'No content fetched after phase 2 ({MAX_RETRIES_PHASE2} attempts)'
                        logger.warning(f"Company {domain} failed: phase 2 exhausted")
                    else:
                        company.status = 'requeued'
                        company.failure_reason = f'No content fetched (phase 2 attempt {company.retry_count}/{MAX_RETRIES_PHASE2})'
                        logger.warning(f"Company {domain} retrying phase 2: attempt {company.retry_count}")
                elif company.retry_count >= MAX_RETRIES:
                    company.status = 'requeued'
                    company.retry_count = 0
                    company.failure_reason = 'Phase 1 exhausted, moving to phase 2'
                    logger.warning(f"Company {domain} moved to phase 2 (requeued)")
                else:
                    company.status = 'discovered'
                    company.failure_reason = f'No content fetched (attempt {company.retry_count}/{MAX_RETRIES})'
                    logger.warning(f"Company {domain} retrying phase 1: attempt {company.retry_count}")
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
            company.retry_count = (company.retry_count or 0) + 1

            if original_status == 'requeued':
                if company.retry_count >= MAX_RETRIES_PHASE2:
                    company.status = 'failed'
                    company.failure_reason = str(e)[:450]
                else:
                    company.status = 'requeued'
                    company.failure_reason = f'Processing error phase 2: {str(e)[:100]}'
            elif company.retry_count >= MAX_RETRIES:
                company.status = 'requeued'
                company.retry_count = 0
                company.failure_reason = f'Error after phase 1: {str(e)[:100]}'
            else:
                company.status = 'discovered'
                company.failure_reason = f'Processing error: {str(e)[:100]}'

            db.commit()
            return False


def watchdog_reset_stuck_companies(db) -> int:
    """Watchdog: Reset companies stuck in browsing for too long."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=WATCHDOG_MINUTES)

    stuck = db.query(Company).filter(
        Company.status == 'browsing',
        Company.browse_heartbeat.isnot(None),
        Company.browse_heartbeat < cutoff_time
    ).all()

    reset_count = 0
    for company in stuck:
        if company.retry_count is None:
            company.retry_count = 1
        else:
            company.retry_count += 1

        max_total = MAX_RETRIES + MAX_RETRIES_PHASE2
        if company.retry_count >= max_total:
            company.status = 'failed'
            company.failure_reason = f'Watchdog: stuck >{WATCHDOG_MINUTES}min, all retries exhausted'
            logger.error(f"Company {company.domain} permanently failed after watchdog timeout")
        elif company.retry_count >= MAX_RETRIES:
            company.status = 'requeued'
            company.failure_reason = f'Watchdog: stuck >{WATCHDOG_MINUTES}min, moved to phase 2'
            logger.warning(f"Company {company.domain} moved to phase 2 by watchdog")
        else:
            company.status = 'discovered'
            company.failure_reason = f'Watchdog: stuck >{WATCHDOG_MINUTES}min, phase 1 retry'
            logger.warning(f"Company {company.domain} retrying phase 1 from watchdog")

        company.browse_heartbeat = None
        reset_count += 1

    if reset_count > 0:
        db.commit()
        logger.info(f"Watchdog reset {reset_count} stuck companies")

    return reset_count



def write_metrics(db):
    """Write service metrics for graphing via API."""
    try:
        import httpx
        api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        
        pages_browsed = db.query(Company).filter(Company.status == 'browsed').count()
        domain_browsed = db.query(Company).filter(Company.status == 'browsing').count()
        domain_failed = db.query(Company).filter(Company.status == 'failed').count()
        enrich_requeued = db.query(Company).filter(Company.status == 'requeued').count()
        
        metrics = [
            ('browsing', 'pages_browsed', pages_browsed),
            ('browsing', 'domain_browsed', domain_browsed),
            ('browsing', 'domain_failed', domain_failed),
            ('browsing', 'enrich_requeued', enrich_requeued),
        ]
        
        for svc, metric, value in metrics:
            try:
                httpx.post(
                    f"{api_base}/dashboard/metrics",
                    json={"service": svc, "metric": metric, "value": value},
                    timeout=5.0,
                )
            except Exception as e:
                logger.debug(f"Failed to write metric {metric}: {e}")
                
    except Exception as e:
        logger.warning(f"Failed to write metrics: {e}")


def run_browser():
    """Main watcher loop."""
    logger.info(f"Browsing service started (poll: {POLL_INTERVAL}s, watchdog: {WATCHDOG_MINUTES}min, phase1: {MAX_RETRIES}, phase2: {MAX_RETRIES_PHASE2})")
    
    metrics_counter = 0
    
    while True:
        db = SessionLocal()
        try:
            watchdog_reset_stuck_companies(db)
            
            # Two-phase: pick up both 'discovered' and 'requeued' companies
            companies = db.query(Company).filter(
                Company.status.in_(['discovered', 'requeued']),
            ).order_by(Company.discovery_score.desc()).limit(50).all()
            
            if companies:
                company_ids = [c.id for c in companies]
                logger.info(f"Found {len(company_ids)} companies to browse")
                
                with ThreadPoolExecutor(max_workers=BROWSING_WORKERS) as executor:
                    futures = {
                        executor.submit(process_company, cid): cid
                        for cid in company_ids
                    }
                    
                    for future in as_completed(futures):
                        cid = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            logger.error(f"Unhandled error in thread for company {cid}: {e}")
            else:
                logger.debug("No companies to browse, waiting...")
            
            # Write metrics every 60 seconds
            metrics_counter += POLL_INTERVAL
            if metrics_counter >= 60:
                write_metrics(db)
                metrics_counter = 0
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            logger.exception(f"Browser error: {e}")
            time.sleep(POLL_INTERVAL)
        finally:
            db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Browsing Service Starting...")
    print("=" * 50)
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        raise
    run_browser()