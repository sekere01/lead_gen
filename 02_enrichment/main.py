"""
Enricher Service - Main logic.
Polls Company for status='discovered' AND discovery_score >= 2.
Runs sources in priority order: theHarvester → Explicit pages → Homepage/footer.
Target: 10 emails per domain.
Entry: python main.py
"""
import os
import time
import asyncio
import logging
import logging.handlers
import json
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

import docker
from docker.errors import APIError
import httpx

from database import SessionLocal, init_db, Company, Contact, ExtractedEmail
from config import settings
from services.email_extractor import extract_emails_regex
from utils.email_utils import is_noise_email, is_placeholder_email, clean_email_prefixes

os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

formatter = logging.Formatter('%(asctime)s | %(levelname)s | enricher | %(message)s')

stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(formatter)

file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "enrichment.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(formatter)

logger = logging.getLogger("enricher")
logger.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)

POLL_INTERVAL = settings.ENRICHER_POLL_INTERVAL
MAX_CONCURRENT = settings.MAX_CONCURRENT_CONTAINERS

TARGET_EMAILS = settings.TARGET_EMAILS_PER_DOMAIN
HEARTBEAT_INTERVAL = settings.HEARTBEAT_INTERVAL
DOMAIN_TIMEOUT = settings.ENRICHMENT_TIMEOUT_DOMAIN
DOCKER_TIMEOUT = settings.ENRICHMENT_TIMEOUT_DOCKER
MAX_RETRIES = settings.ENRICHMENT_MAX_RETRIES
MAX_RETRIES_PHASE2 = settings.ENRICHMENT_MAX_RETRIES_PHASE2
WATCHDOG_MINUTES = settings.ENRICHMENT_WATCHDOG_MINUTES

CRAWLER_MAX_HOSTS = 5
CRAWLER_HTTP_TIMEOUT = settings.CRAWLER_HTTP_TIMEOUT


def get_retry_limit(status):
    """Return max retries allowed for given status."""
    return MAX_RETRIES_PHASE2 if status == 'enrich_requeued' else MAX_RETRIES

EXPLICIT_PAGES = [
    'contact', 'contact-us', 'contact.html', 'contact.php', 'contact.htm',
    'about', 'about-us', 'about.html', 'about.php',
    'team', 'team.html', 'our-team',
    'people', 'staff', 'directory',
]


def update_heartbeat(company, db) -> None:
    """Update company heartbeat timestamp."""
    company.last_heartbeat = datetime.now()
    db.commit()


def check_docker_health() -> bool:
    """Check if Docker daemon is responsive."""
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception as e:
        logger.warning(f"Docker health check failed: {e}")
        return False


def get_docker_client():
    """Get Docker client with retry logic."""
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            client = docker.from_env()
            client.ping()
            return client
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Docker connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to Docker after {max_retries} attempts: {e}")
                raise


def run_docker_harvester(domain: str) -> Tuple[List[str], List[str]]:
    """Run theHarvester in Docker container. Returns (emails, hosts)."""
    emails = []
    hosts = []
    container = None
    
    if not check_docker_health():
        logger.warning(f"Docker not healthy, skipping harvester for {domain}")
        return emails, hosts
    
    try:
        client = get_docker_client()
        logger.info(f"Starting Docker theHarvester for: {domain}")
        
        volume_path = os.path.abspath(settings.OUTPUT_DIR)
        os.makedirs(volume_path, exist_ok=True)
        
        container = client.containers.run(
            "ghcr.io/laramies/theharvester:latest",
            command=f"-d {domain} -l {settings.HARVESTER_LIMIT} -b google,bing,linkedin,duckduckgo -f /output/emails.json",
            detach=True,
            remove=True,
            volumes={volume_path: {'bind': '/output', 'mode': 'rw'}},
            environment={"PYTHONUNBUFFERED": "1"}
        )
        
        result = container.wait(timeout=DOCKER_TIMEOUT)
        
        output_file = os.path.join(volume_path, "emails.json")
        
        if os.path.exists(output_file):
            with open(output_file, 'r') as f:
                data = json.load(f)
                
                raw_emails = data.get('emails', [])
                unique_emails = list(set(e.lower() for e in raw_emails if e and '@' in e))
                emails.extend(unique_emails)
                
                raw_hosts = data.get('hosts', [])
                hosts = [h.split(':')[0] for h in raw_hosts if h]
                
                logger.info(f"Harvester: found {len(unique_emails)} emails, {len(hosts)} hosts for {domain}")
        
    except APIError as e:
        logger.warning(f"Docker API error for {domain}: {e}")
    except Exception as e:
        logger.warning(f"Docker harvester error for {domain}: {e}")
    finally:
        if container:
            try:
                container.stop(timeout=5)
            except:
                pass
    
    return emails, hosts


async def fetch_page_async(client: httpx.AsyncClient, url: str, headers: dict) -> Tuple[str, str]:
    """Async fetch a single page."""
    try:
        response = await client.get(url, timeout=CRAWLER_HTTP_TIMEOUT, headers=headers, follow_redirects=True)
        if response.status_code == 200:
            return (url, response.text)
        return (url, "")
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
        return (url, "")


async def _extract_async(client, urls: List[str], headers: dict, target: int) -> List[Tuple[str, str]]:
    """Async helper to fetch multiple pages."""
    tasks = [fetch_page_async(client, url, headers) for url in urls]
    results = await asyncio.gather(*tasks)
    return results


def extract_emails_from_pages(domain: str, hosts: List[str], target: int) -> List[str]:
    """Extract emails from explicit pages on discovered hosts."""
    all_emails = []
    
    if not hosts:
        hosts = [domain]
    
    clean_hosts = []
    seen = set()
    for h in hosts:
        h_clean = h.replace('*.', '').split(':')[0]
        if h_clean and h_clean not in seen and not h_clean.replace('.', '').isdigit():
            clean_hosts.append(h_clean)
            seen.add(h_clean)
    
    top_hosts = clean_hosts[:CRAWLER_MAX_HOSTS]
    logger.info(f"Explicit pages: extracting from {len(top_hosts)} hosts for {domain}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    urls_to_fetch = []
    for host in top_hosts:
        for page_path in EXPLICIT_PAGES:
            for scheme in ['https', 'http']:
                if page_path:
                    urls_to_fetch.extend([
                        f"{scheme}://{host}/{page_path}",
                        f"{scheme}://www.{host}/{page_path}",
                    ])
                else:
                    urls_to_fetch.extend([
                        f"{scheme}://{host}",
                        f"{scheme}://www.{host}",
                    ])
    
    try:
        results = asyncio.run(_extract_async(httpx.AsyncClient(http2=True), urls_to_fetch, headers, target))
    except Exception:
        try:
            results = asyncio.run(_extract_async(httpx.AsyncClient(), urls_to_fetch, headers, target))
        except ImportError:
            results = asyncio.run(_extract_async(httpx.Client(), urls_to_fetch, headers, target))
    
    for url, text in results:
        if text and len(all_emails) < target:
            extracted = extract_emails_regex(text)
            for email in extracted:
                email = email.strip().lower()
                email = clean_email_prefixes(email)
                if not email or '@' not in email:
                    continue
                # N1: Reject noise (image filenames, malformed domains)
                if is_noise_email(email):
                    logger.debug(f"Noise email rejected: {email}")
                    continue
                # N1: Reject placeholders
                if is_placeholder_email(email):
                    logger.debug(f"Placeholder email rejected: {email}")
                    continue
                # Existing dedup logic
                if email not in [e.lower() for e in all_emails]:
                    all_emails.append(email)
                if len(all_emails) >= target:
                    break
        if len(all_emails) >= target:
            break
    
    logger.info(f"Explicit pages: found {len(all_emails)} unique emails for {domain}")
    return all_emails


def extract_emails_from_homepage(domain: str, target: int) -> List[str]:
    """Extract emails from homepage and footer scan."""
    all_emails = []
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    urls = [
        f"https://{domain}",
        f"http://{domain}",
        f"https://www.{domain}",
        f"http://www.{domain}",
    ]
    
    for url in urls:
        if len(all_emails) >= target:
            break
        try:
            response = httpx.Client(timeout=CRAWLER_HTTP_TIMEOUT).get(url, headers=headers, follow_redirects=True)
            if response.status_code == 200:
                extracted = extract_emails_regex(response.text)
                for email in extracted:
                    email = email.strip().lower()
                    email = clean_email_prefixes(email)
                    if not email or '@' not in email:
                        continue
                    # N1: Reject noise
                    if is_noise_email(email):
                        continue
                    # N1: Reject placeholders
                    if is_placeholder_email(email):
                        continue
                    if email not in [e.lower() for e in all_emails]:
                        all_emails.append(email)
        except Exception:
            continue
    
    logger.info(f"Homepage scan: found {len(all_emails)} emails for {domain}")
    return all_emails


def save_emails_incremental(company_id: int, emails: List[str], email_type: str, domain: str, db) -> int:
    """Save emails to DB incrementally. Returns count saved."""
    if not emails:
        return 0
    
    saved_count = 0
    contacts_to_insert = []
    emails_to_insert = []
    
    for email_addr in emails:
        contacts_to_insert.append({
            'first_name': 'Unknown',
            'last_name': 'Unknown',
            'email': email_addr,
            'company_id': company_id,
            'verification_status': 'pending',
            'is_verified': False,
            'source_url': f"https://{domain}"
        })
        emails_to_insert.append({
            'email': email_addr,
            'email_type': email_type,
            'source_url': f"https://{domain}",
            'company_id': company_id
        })
        saved_count += 1
    
    if not contacts_to_insert:
        return 0
    
    try:
        db.bulk_save_objects([Contact(**c) for c in contacts_to_insert])
        db.bulk_save_objects([ExtractedEmail(**e) for e in emails_to_insert])
        db.commit()
        logger.info(f"Incremental save: {saved_count} emails saved ({email_type})")
    except Exception as e:
        logger.warning(f"Bulk save failed, trying one by one: {e}")
        db.rollback()  # E1: Clear poisoned transaction
        for i, contact_data in enumerate(contacts_to_insert):
            try:
                contact = Contact(**contact_data)
                db.add(contact)
                email_record = ExtractedEmail(**emails_to_insert[i])
                db.add(email_record)
                db.commit()  # E1: Commit each individually
            except Exception:
                db.rollback()  # E1: Skip duplicate, continue with next
                logger.debug(f"Skipped duplicate: {contact_data.get('email')}")
    
    return saved_count


def process_company(company) -> bool:
    """Process a single company with source priority and early stop."""
    db = SessionLocal()
    try:
        domain = company.domain
        company_id = company.id
        
        # Use merge to handle potentially detached object
        company = db.merge(company)
        if company is None:
            logger.warning(f"Company {domain} not found in DB")
            return False
            
        company.status = 'enriching'
        company.last_heartbeat = datetime.now()
        db.commit()
        
        # Refresh to get database-backed object
        db.refresh(company)
        if company.status != 'enriching':
            logger.debug(f"Company {domain} already being processed, skipping")
            return False
        
        saved_count = 0
        all_emails: Set[str] = set()
        last_heartbeat_time = time.time()
        failure_reasons = []
        
        start_time = time.time()
        
        logger.info(f"Processing company: {domain}")
        
        # Source 1: theHarvester Docker
        try:
            if time.time() - start_time > DOMAIN_TIMEOUT:
                failure_reasons.append("timeout before harvester")
            else:
                emails, hosts = run_docker_harvester(domain)
                
                for email in emails:
                    all_emails.add(email.lower())
                
                if emails:
                    saved = save_emails_incremental(company.id, emails, 'harvester', domain, db)
                    saved_count += saved
                
                logger.info(f"Source 1 (Harvester): {len(emails)} emails, total: {len(all_emails)}/{TARGET_EMAILS}")
                
                if len(all_emails) >= TARGET_EMAILS:
                    raise TimeoutError("target reached")
                
                if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    update_heartbeat(company, db)
                    last_heartbeat_time = time.time()
                    
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"Source 1 (Harvester) failed for {domain}: {e}")
            failure_reasons.append(f"harvester: {str(e)[:100]}")
        
        # Source 2: Explicit pages
        try:
            if time.time() - start_time > DOMAIN_TIMEOUT:
                failure_reasons.append("timeout before explicit pages")
            else:
                hosts = [] if not all_emails else [domain]
                emails = extract_emails_from_pages(domain, hosts, TARGET_EMAILS - len(all_emails))
                
                new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
                for email in new_emails:
                    all_emails.add(email.lower())
                
                if new_emails:
                    saved = save_emails_incremental(company.id, new_emails, 'explicit_pages', domain, db)
                    saved_count += saved
                
                logger.info(f"Source 2 (Explicit pages): {len(new_emails)} new emails, total: {len(all_emails)}/{TARGET_EMAILS}")
                
                if len(all_emails) >= TARGET_EMAILS:
                    raise TimeoutError("target reached")
                
                if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    update_heartbeat(company, db)
                    last_heartbeat_time = time.time()
                    
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"Source 2 (Explicit pages) failed for {domain}: {e}")
            failure_reasons.append(f"explicit_pages: {str(e)[:100]}")
        
        # Source 3: Homepage + footer scan
        try:
            if time.time() - start_time > DOMAIN_TIMEOUT:
                failure_reasons.append("timeout before homepage")
            else:
                emails = extract_emails_from_homepage(domain, TARGET_EMAILS - len(all_emails))
                
                new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
                for email in new_emails:
                    all_emails.add(email.lower())
                
                if new_emails:
                    saved = save_emails_incremental(company.id, new_emails, 'homepage', domain, db)
                    saved_count += saved
                
                logger.info(f"Source 3 (Homepage): {len(new_emails)} new emails, total: {len(all_emails)}/{TARGET_EMAILS}")
                
        except TimeoutError:
            raise
        except Exception as e:
            logger.warning(f"Source 3 (Homepage) failed for {domain}: {e}")
            failure_reasons.append(f"homepage: {str(e)[:100]}")
        
        # Check for timeout
        if time.time() - start_time > DOMAIN_TIMEOUT:
            logger.warning(f"Domain {domain} exceeded {DOMAIN_TIMEOUT}s timeout")
            failure_reasons.append(f"timeout after {int(time.time() - start_time)}s")
        
        # All sources exhausted - mark enriched (re-fetch to ensure object is attached)
        try:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company:
                company.status = 'enriched'
                company.last_heartbeat = None
                company.failure_reason = "; ".join(failure_reasons) if failure_reasons else None
                db.commit()
        except Exception as commit_err:
            logger.warning(f"Failed to commit status for {domain}: {commit_err}")
        
        logger.info(f"Company {domain} enriched: {saved_count} contacts saved, {len(all_emails)} total emails")
        return True
        
    except TimeoutError:
        try:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company:
                company.status = 'enriched'
                company.last_heartbeat = None
                company.failure_reason = "; ".join(failure_reasons) if failure_reasons else "target reached"
                db.commit()
        except Exception as commit_err:
            logger.warning(f"Failed to commit status for {domain}: {commit_err}")
        logger.info(f"Company {domain} enriched (target reached): {len(all_emails)} emails")
        return True
    
    except Exception as e:
        logger.error(f"Error processing company {domain}: {e}")
        try:
            company = db.query(Company).filter(Company.id == company_id).first()
            if company:
                company.status = 'enriched'
                company.failure_reason = f"Error: {str(e)[:100]}"
                company.last_heartbeat = None
                db.commit()
        except Exception as commit_err:
            logger.warning(f"Failed to commit error status for {domain}: {commit_err}")
        return False
    finally:
        db.close()


def watchdog_reset_stuck_companies(db) -> int:
    """Watchdog: Reset companies stuck in 'enriching' for too long."""
    cutoff_time = datetime.now() - timedelta(minutes=WATCHDOG_MINUTES)
    
    stuck_companies = db.query(Company).filter(
        Company.status == 'enriching',
        Company.last_heartbeat < cutoff_time
    ).all()
    
    reset_count = 0
    for company in stuck_companies:
        old_retry = company.retry_count or 0
        company.retry_count = old_retry + 1
        
        # Two-phase retry: browsed → enrich_requeued → failed
        if company.status == 'enrich_requeued' and company.retry_count >= MAX_RETRIES_PHASE2:
            company.status = 'failed'
            company.failure_reason = f"Watchdog: stuck >{WATCHDOG_MINUTES}min, phase 2 exhausted"
            logger.error(f"Company {company.domain} permanently failed: phase 2 exhausted")
        elif company.status == 'browsed' and company.retry_count >= MAX_RETRIES:
            company.status = 'enrich_requeued'
            company.retry_count = 0
            company.failure_reason = f"Watchdog: stuck >{WATCHDOG_MINUTES}min, phase 1 exhausted"
            logger.warning(f"Company {company.domain} moved to phase 2 (enrich_requeued)")
        else:
            company.status = 'browsed'
            company.failure_reason = f"Watchdog: stuck >{WATCHDOG_MINUTES}min, retry {company.retry_count}"
            logger.warning(f"Company {company.domain} reset by watchdog: retry {company.retry_count}")
        
        reset_count += 1
    
    if reset_count > 0:
        db.commit()
        logger.info(f"Watchdog reset {reset_count} stuck companies")
    
    return reset_count


def run_enricher():
    """Main watcher loop."""
    logger.info(f"Enricher service started (poll: {POLL_INTERVAL}s, concurrent: {MAX_RETRIES}, watchdog: {WATCHDOG_MINUTES}min)")
    
    consecutive_failures = 0
    max_failures_before_wait = 3
    
    while True:
        db = SessionLocal()
        try:
            if not check_docker_health():
                consecutive_failures += 1
                logger.warning(f"Docker not healthy. Failures: {consecutive_failures}")
                
                if consecutive_failures >= max_failures_before_wait:
                    wait_time = min(POLL_INTERVAL * 5, 300)
                    logger.error(f"Docker unavailable. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    time.sleep(POLL_INTERVAL)
                continue
            
            consecutive_failures = 0
            
            watchdog_reset_stuck_companies(db)
            
            # Two-phase: pick up both 'browsed' and 'enrich_requeued' companies
            companies = db.query(Company).filter(
                Company.status.in_(['browsed', 'enrich_requeued']),
            ).order_by(Company.discovery_score.desc()).limit(10).all()
            
            if not companies:
                logger.debug("No companies to enrich, waiting...")
                time.sleep(POLL_INTERVAL)
                continue
            
            logger.info(f"Found {len(companies)} companies to enrich")
            
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
                futures = {executor.submit(process_company, company): company for company in companies}
                
                for future in as_completed(futures):
                    company = futures[future]
                    try:
                        result = future.result()
                        logger.info(f"Company {company.domain} processed: {result}")
                    except Exception as e:
                        logger.error(f"Error processing {company.domain}: {e}")
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            logger.error(f"Enricher error: {e}")
            time.sleep(POLL_INTERVAL)
        finally:
            db.close()


if __name__ == "__main__":
    print("=" * 50)
    print("Enrichment Service Starting...")
    print("=" * 50)
    init_db()
    run_enricher()