"""
Enricher Service - Main logic.
Poll Company for status='discovered' AND discovery_score >= 2.
Runs sources in priority order: theHarvester → Google Dorking → Sitemap → Explicit pages → Homepage.
Entry: python main.py
"""
import os
import time
import asyncio
import logging
import logging.handlers
import json
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

import docker
from docker.errors import APIError
import httpx
from groq import Groq
from googlesearch import search as google_search

from database import SessionLocal, init_db, Company, Contact, ExtractedEmail
from config import settings
from services.email_extractor import extract_emails_regex
from utils.email_utils import is_noise_email, is_placeholder_email, clean_email_prefixes

os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

_http_client = httpx.Client(timeout=5.0)

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
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

logger = logging.getLogger("enricher")
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)

POLL_INTERVAL = settings.ENRICHER_POLL_INTERVAL
MAX_CONCURRENT = settings.MAX_CONCURRENT_CONTAINERS

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

GOOGLE_DORK_QUERIES = {
    "high_value": [
        'site:{domain} "ceo" OR "chief executive" email',
        'site:{domain} "cfo" OR "chief financial" email',
        'site:{domain} "cto" OR "chief technology" OR "chief technical" email',
        'site:{domain} "coo" OR "chief operating" email',
        'site:{domain} "vp sales" OR "sales director" OR "head of sales" email',
        'site:{domain} "cmo" OR "marketing director" OR "head of marketing" email',
        'site:{domain} "account payables" OR "accounts payable" OR "procurement" email',
        'site:{domain} "retail director" OR "retail manager" OR "ecommerce manager" email',
        'site:{domain} "vp" OR "director" OR "head of" inurl:team "@{domain}"',
        'site:{domain} "leadership" OR "executive" OR "management team" intitle:contact',
        'site:{domain} "business development" OR "bd manager" OR "partnership" email',
        'site:{domain} "supply chain" OR "logistics director" OR "operations" email',
    ],
    "low_value": [
        'site:{domain} "info@" OR "contact@" OR "hello@" email',
        'site:{domain} "support@" OR "help@" OR "admin@" email',
        'site:{domain} "careers@" OR "jobs@" OR "hr@" email',
        'site:{domain} intitle:contact inurl:contact email',
        'site:{domain} mailto: "@{domain}" -www',
        'site:{domain} "newsletter" OR "subscribe" email',
    ],
}


def update_heartbeat(company, db) -> None:
    """Update company heartbeat timestamp."""
    company.last_heartbeat = datetime.now(timezone.utc)
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
        
        sources = settings.HARVESTER_SOURCES
        # Filter to only supported sources (theHarvester 4.10.1 dropped google/bing)
        supported = {"baidu", "bevigil", "bitbucket", "brave", "bufferoverun", "builtwith",
                     "censys", "certspotter", "chaos", "commoncrawl", "criminalip", "crtsh",
                     "dehashed", "dnsdumpster", "duckduckgo", "dymo", "fofa", "fullhunt",
                     "github-code", "gitlab", "hackertarget", "haveibeenpwned", "hudsonrock",
                     "hunter", "hunterhow", "intelx", "leakix", "leaklookup", "mojeek",
                     "netlas", "onyphe", "otx", "pentesttools", "projectdiscovery", "rapiddns",
                     "robtex", "rocketreach", "securityscorecard", "securitytrails", "shodan",
                     "shodanInternetDB", "subdomaincenter", "subdomainfinderc99", "thc",
                     "threatcrowd", "tomba", "urlscan", "venacus", "virustotal",
                     "waybackarchive", "whoisxml", "windvane", "yahoo", "zoomeye"}
        chosen = [s.strip() for s in sources.split(",") if s.strip() in supported]
        if not chosen:
            chosen = ["duckduckgo"]
        source_str = ",".join(chosen)

        # Clean stale output from prior runs
        for f in ["emails.json", "emails.xml"]:
            p = os.path.join(volume_path, f)
            if os.path.exists(p):
                os.remove(p)

        container = client.containers.run(
            "ghcr.io/laramies/theharvester:latest",
            entrypoint="theHarvester",
            command=f"-d {domain} -l {settings.HARVESTER_LIMIT} -b {source_str} -f /output/emails.json",
            detach=True,
            remove=True,
            mem_limit="512m",
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



async def _extract_async(client, urls: List[str], headers: dict) -> List[Tuple[str, str]]:
    """Async helper to fetch multiple pages with concurrency limit."""
    sem = asyncio.Semaphore(20)
    async def bounded_fetch(url):
        async with sem:
            return await fetch_page_async(client, url, headers)
    tasks = [bounded_fetch(url) for url in urls]
    results = await asyncio.gather(*tasks)
    return results


def extract_emails_from_pages(domain: str, hosts: List[str]) -> List[str]:
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
    
    async def _run_extract(urls, headers):
        try:
            async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
                return await _extract_async(client, urls, headers)
        except Exception:
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await _extract_async(client, urls, headers)

    results = asyncio.run(_run_extract(urls_to_fetch, headers))
    
    for url, text in results:
        if text:
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
    
    logger.info(f"Explicit pages: found {len(all_emails)} unique emails for {domain}")
    return all_emails


def extract_emails_from_homepage(domain: str) -> List[str]:
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
        db.rollback()
        for i, contact_data in enumerate(contacts_to_insert):
            try:
                with db.begin_nested():
                    contact = Contact(**contact_data)
                    db.add(contact)
                    email_record = ExtractedEmail(**emails_to_insert[i])
                    db.add(email_record)
                db.commit()
            except Exception:
                logger.debug(f"Skipped duplicate: {contact_data.get('email')}")
    
    return saved_count


def generate_google_dork_queries(domain: str) -> List[str]:
    """Generate Google dork queries via LLM. Falls back to editable static dict."""
    api_key = getattr(settings, 'GROQ_API_KEY', None)
    if api_key:
        try:
            client = Groq(api_key=api_key)
            model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')
            prompt = f"""You are an OSINT email discovery specialist. Generate 15 Google dork queries to find email addresses on {domain}.

SPLIT 70/30:
- 70% targeting HIGH-VALUE decision-maker roles (C-suite, Sales, Marketing, Finance, Procurement, Retail management)
- 30% targeting general catch-all, contact, and support emails

HIGH-VALUE roles to target:
- CEO, CFO, CTO, COO, CIO, Founder
- VP Sales, Sales Director, Head of Sales, Business Development
- CMO, Marketing Director, Head of Marketing, Growth
- Account Payables, Procurement, Purchasing Manager
- Retail Director, Retail Manager, E-commerce Manager
- Finance Director, Controller
- Leadership/executive team pages with email contacts

GENERAL/CATCH-ALL roles:
- info@, contact@, hello@, admin@
- support@, help@
- newsletter, subscribe, careers

Use diverse dork patterns like:
- site:{domain} "ceo" OR "chief executive" email
- site:{domain} inurl:team "sales director" email
- site:{domain} intitle:contact "info@"

Return ONLY a JSON array of 15 query strings. No explanation. Example: ["site:example.com \"ceo\" OR \"chief executive\" email", ...]"""

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=1000
            )
            raw = response.choices[0].message.content.strip()
            queries = json.loads(raw)
            return queries[:15]
        except Exception as e:
            logger.warning(f"Groq dork generation failed: {e}, using static fallback")

    all_queries = []
    for q in GOOGLE_DORK_QUERIES.get("high_value", []):
        all_queries.append(q.format(domain=domain))
    for q in GOOGLE_DORK_QUERIES.get("low_value", []):
        all_queries.append(q.format(domain=domain))
    return all_queries


def extract_emails_from_google_dorking(domain: str) -> List[str]:
    """Extract emails via Google dorking with role-targeted queries."""
    all_emails = []
    queries = generate_google_dork_queries(domain)

    logger.info(f"Google Dorking: {len(queries)} queries for {domain}")

    for query in queries:
        try:
            for result in google_search(query, num_results=30, sleep_interval=2):
                snippet = result.description if hasattr(result, 'description') else ""
                title = result.title if hasattr(result, 'title') else ""
                text = f"{title} {snippet}"
                extracted = extract_emails_regex(text)
                for email in extracted:
                    email = email.strip().lower()
                    if email and '@' in email and not is_noise_email(email) and not is_placeholder_email(email):
                        if email not in all_emails:
                            all_emails.append(email)
        except Exception as e:
            logger.debug(f"Google dork query failed: {query[:60]}... {e}")
            continue

    logger.info(f"Google Dorking: found {len(all_emails)} emails for {domain}")
    return all_emails


def extract_emails_from_sitemap(domain: str) -> List[str]:
    """Extract emails by crawling sitemap-discovered pages."""
    all_emails = []
    sitemap_urls = set()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    urls_to_check = [
        f"https://{domain}/robots.txt",
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"http://{domain}/sitemap.xml",
    ]

    for url in urls_to_check:
        try:
            response = httpx.get(url, timeout=CRAWLER_HTTP_TIMEOUT, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                continue
            body = response.text.lower()
            if "sitemap:" in body:
                for line in body.splitlines():
                    if line.strip().startswith("sitemap:"):
                        sm_url = line.split(":", 1)[1].strip()
                        sitemap_urls.add(sm_url)
            if ".xml" in url and ("<urlset" in body or "<sitemapindex" in body):
                sitemap_urls.add(url)
        except Exception:
            continue

    page_urls = []
    for sm_url in sitemap_urls:
        try:
            response = httpx.get(sm_url, timeout=CRAWLER_HTTP_TIMEOUT, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                continue
            root = ET.fromstring(response.text)
            ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for loc in root.iterfind('.//s:loc', ns):
                loc_text = loc.text.strip()
                if domain in loc_text and loc_text not in page_urls:
                    page_urls.append(loc_text)
        except Exception:
            continue

    if not page_urls:
        return []

    page_urls = page_urls[:50]
    logger.info(f"Sitemap: {len(page_urls)} pages to scrape for {domain}")

    async def _run_sitemap(urls, headers):
        try:
            async with httpx.AsyncClient(http2=True, timeout=10.0) as client:
                return await _extract_async(client, urls, headers)
        except Exception:
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await _extract_async(client, urls, headers)

    results = asyncio.run(_run_sitemap(page_urls, headers))

    for url, text in results:
        if not text:
            continue
        extracted = extract_emails_regex(text)
        for email in extracted:
            email = email.strip().lower()
            email = clean_email_prefixes(email)
            if not email or '@' not in email:
                continue
            if is_noise_email(email) or is_placeholder_email(email):
                continue
            if email not in all_emails:
                all_emails.append(email)

    logger.info(f"Sitemap: found {len(all_emails)} emails for {domain}")
    return all_emails


def process_company(company) -> tuple:
    """Process a single company through all email extraction sources. Returns (bool, dict)."""
    db = SessionLocal()
    source_stats = {
        "harvester": {"total": 0, "success": 0},
        "google_dorking": {"total": 0, "success": 0},
        "sitemap": {"total": 0, "success": 0},
        "explicit_pages": {"total": 0, "success": 0},
        "homepage": {"total": 0, "success": 0},
    }
    try:
        domain = company.domain
        company_id = company.id
        
        # Use merge to handle potentially detached object
        company = db.merge(company)
        if company is None:
            logger.warning(f"Company {domain} not found in DB")
            return False, source_stats
            
        company.status = 'enriching'
        company.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        
        # Refresh to get database-backed object
        db.refresh(company)
        if company.status != 'enriching':
            logger.debug(f"Company {domain} already being processed, skipping")
            return False, source_stats
        
        saved_count = 0
        all_emails: Set[str] = set()
        last_heartbeat_time = time.time()
        failure_reasons = []
        
        total_start = time.time()
        
        logger.info(f"Processing company: {domain}")
        
        # Source 1: theHarvester Docker
        try:
            source_start = time.time()
            emails, hosts = run_docker_harvester(domain)
            elapsed = time.time() - source_start
            if elapsed > DOMAIN_TIMEOUT:
                failure_reasons.append(f"harvester exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
                logger.warning(f"Source 1 (Harvester) for {domain} exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
            
            source_stats["harvester"]["total"] = len(emails)
            
            for email in emails:
                all_emails.add(email.lower())
            
            if emails:
                saved = save_emails_incremental(company.id, emails, 'harvester', domain, db)
                saved_count += saved
                source_stats["harvester"]["success"] = saved
            
            logger.info(f"Source 1 (Harvester): {len(emails)} emails, total: {len(all_emails)}")
            
            if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                update_heartbeat(company, db)
                last_heartbeat_time = time.time()
                    
        except Exception as e:
            logger.warning(f"Source 1 (Harvester) failed for {domain}: {e}")
            failure_reasons.append(f"harvester: {str(e)[:100]}")
        
        # Source 2: Google Dorking
        try:
            source_start = time.time()
            emails = extract_emails_from_google_dorking(domain)
            elapsed = time.time() - source_start
            if elapsed > DOMAIN_TIMEOUT:
                failure_reasons.append(f"google_dork exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
                logger.warning(f"Source 2 (Google Dorking) for {domain} exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
            
            source_stats["google_dorking"]["total"] = len(emails)
            
            new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
            for email in new_emails:
                all_emails.add(email.lower())
            
            if new_emails:
                saved = save_emails_incremental(company.id, new_emails, 'google_dork', domain, db)
                saved_count += saved
                source_stats["google_dorking"]["success"] = saved
            
            logger.info(f"Source 2 (Google Dorking): {len(new_emails)} new emails, total: {len(all_emails)}")
            
            if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                update_heartbeat(company, db)
                last_heartbeat_time = time.time()
                    
        except Exception as e:
            logger.warning(f"Source 2 (Google Dorking) failed for {domain}: {e}")
            failure_reasons.append(f"google_dork: {str(e)[:100]}")
        
        # Source 3: Sitemap crawl
        try:
            source_start = time.time()
            emails = extract_emails_from_sitemap(domain)
            elapsed = time.time() - source_start
            if elapsed > DOMAIN_TIMEOUT:
                failure_reasons.append(f"sitemap exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
                logger.warning(f"Source 3 (Sitemap) for {domain} exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
            
            source_stats["sitemap"]["total"] = len(emails)
            
            new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
            for email in new_emails:
                all_emails.add(email.lower())
            
            if new_emails:
                saved = save_emails_incremental(company.id, new_emails, 'sitemap', domain, db)
                saved_count += saved
                source_stats["sitemap"]["success"] = saved
            
            logger.info(f"Source 3 (Sitemap): {len(new_emails)} new emails, total: {len(all_emails)}")
            
            if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                update_heartbeat(company, db)
                last_heartbeat_time = time.time()
                    
        except Exception as e:
            logger.warning(f"Source 3 (Sitemap) failed for {domain}: {e}")
            failure_reasons.append(f"sitemap: {str(e)[:100]}")
        
        # Source 4: Explicit pages
        try:
            page_hosts = [h for h in hosts if h] if hosts else [domain]
            source_start = time.time()
            emails = extract_emails_from_pages(domain, page_hosts)
            elapsed = time.time() - source_start
            if elapsed > DOMAIN_TIMEOUT:
                failure_reasons.append(f"explicit_pages exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
                logger.warning(f"Source 4 (Explicit pages) for {domain} exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
            
            source_stats["explicit_pages"]["total"] = len(emails)
            
            new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
            for email in new_emails:
                all_emails.add(email.lower())
            
            if new_emails:
                saved = save_emails_incremental(company.id, new_emails, 'explicit_pages', domain, db)
                saved_count += saved
                source_stats["explicit_pages"]["success"] = saved
            
            logger.info(f"Source 4 (Explicit pages): {len(new_emails)} new emails, total: {len(all_emails)}")
            
            if time.time() - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                update_heartbeat(company, db)
                last_heartbeat_time = time.time()
                    
        except Exception as e:
            logger.warning(f"Source 4 (Explicit pages) failed for {domain}: {e}")
            failure_reasons.append(f"explicit_pages: {str(e)[:100]}")
        
        # Source 5: Homepage + footer scan
        try:
            source_start = time.time()
            emails = extract_emails_from_homepage(domain)
            elapsed = time.time() - source_start
            if elapsed > DOMAIN_TIMEOUT:
                failure_reasons.append(f"homepage exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
                logger.warning(f"Source 5 (Homepage) for {domain} exceeded {DOMAIN_TIMEOUT}s ({elapsed:.0f}s)")
            
            source_stats["homepage"]["total"] = len(emails)
            
            new_emails = [e for e in emails if e.lower() not in [e2.lower() for e2 in all_emails]]
            for email in new_emails:
                all_emails.add(email.lower())
            
            if new_emails:
                saved = save_emails_incremental(company.id, new_emails, 'homepage', domain, db)
                saved_count += saved
                source_stats["homepage"]["success"] = saved
            
            logger.info(f"Source 5 (Homepage): {len(new_emails)} new emails, total: {len(all_emails)}")
                
        except Exception as e:
            logger.warning(f"Source 5 (Homepage) failed for {domain}: {e}")
            failure_reasons.append(f"homepage: {str(e)[:100]}")
        
        # Log total elapsed time (informational only, each source had its own budget)
        total_elapsed = time.time() - total_start
        if total_elapsed > DOMAIN_TIMEOUT:
            logger.info(f"Domain {domain} total time: {total_elapsed:.0f}s (per-source timeout used)")
        
        # All sources exhausted - mark enriched
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
        return True, source_stats
        
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
        return False, source_stats
    finally:
        db.close()


def watchdog_reset_stuck_companies(db) -> int:
    """Watchdog: Reset companies stuck in 'enriching' for too long."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=WATCHDOG_MINUTES)
    
    stuck_companies = db.query(Company).filter(
        Company.status == 'enriching',
        Company.last_heartbeat < cutoff_time
    ).all()
    
    reset_count = 0
    for company in stuck_companies:
        old_retry = company.retry_count or 0
        company.retry_count = old_retry + 1
        
        # Two-phase retry: browsed → enrich_requeued → failed
        if company.retry_count >= MAX_RETRIES + MAX_RETRIES_PHASE2:
            company.status = 'failed'
            company.failure_reason = f"Watchdog: stuck >{WATCHDOG_MINUTES}min, all phases exhausted"
            logger.error(f"Company {company.domain} permanently failed: retries exhausted")
        elif company.retry_count >= MAX_RETRIES:
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



def write_metrics(db):
    """Write service metrics for graphing via API."""
    try:
        import httpx
        api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        
        emails_collected = db.query(Contact).count()
        domains_processed = db.query(Company).filter(Company.status == 'enriched').count()
        enrich_requeued = db.query(Company).filter(Company.status == 'enrich_requeued').count()
        domain_enriching = db.query(Company).filter(Company.status == 'enriching').count()
        
        metrics = [
            ('enrichment', 'emails_collected', emails_collected),
            ('enrichment', 'domains_processed', domains_processed),
            ('enrichment', 'enrich_requeued', enrich_requeued),
            ('enrichment', 'domain_enriching', domain_enriching),
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


def report_enrichment_progress(companies_total, companies_processed, emails_collected, failed, status):
    """Post live enrichment progress to the dashboard API."""
    try:
        api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
        _http_client.post(
            f"{api_base}/dashboard/enrichment-progress",
            json={
                "companies_total": companies_total,
                "companies_processed": companies_processed,
                "emails_collected": emails_collected,
                "failed_companies": failed,
                "status": status,
            },
        )
    except Exception as e:
        logger.debug(f"Progress POST failed: {e}")


def run_enricher():
    """Main watcher loop."""
    logger.info(f"Enricher service started (poll: {POLL_INTERVAL}s, concurrent: {MAX_CONCURRENT}, watchdog: {WATCHDOG_MINUTES}min)")
    
    metrics_counter = 0
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
            
            if companies:
                logger.info(f"Found {len(companies)} companies to enrich")
                aggregated_stats = {
                    "harvester": {"total": 0, "success": 0},
                    "google_dorking": {"total": 0, "success": 0},
                    "sitemap": {"total": 0, "success": 0},
                    "explicit_pages": {"total": 0, "success": 0},
                    "homepage": {"total": 0, "success": 0},
                }
                
                companies_processed = 0
                total_emails = 0
                failed_count = 0
                
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
                    futures = {executor.submit(process_company, company): company for company in companies}
                    
                    for future in as_completed(futures):
                        company = futures[future]
                        try:
                            result, stats = future.result()
                            companies_processed += 1
                            for src_key in aggregated_stats:
                                aggregated_stats[src_key]["total"] += stats[src_key]["total"]
                                aggregated_stats[src_key]["success"] += stats[src_key]["success"]
                            batch_emails = sum(stats[k]["success"] for k in stats)
                            total_emails += batch_emails
                            if not result:
                                failed_count += 1
                            logger.info(f"Company {company.domain} processed: {result}")
                        except Exception as e:
                            companies_processed += 1
                            failed_count += 1
                            logger.error(f"Error processing {company.domain}: {e}")
                        
                        # Report live progress after each company
                        report_enrichment_progress(
                            len(companies), companies_processed, total_emails, failed_count, "running"
                        )
                
                # Final batch report
                report_enrichment_progress(
                    len(companies), companies_processed, total_emails, failed_count, "idle"
                )
                
                # POST aggregated source stats
                try:
                    api_base = os.getenv('API_BASE', 'http://localhost:8000/api/v1')
                    httpx.post(
                        f"{api_base}/dashboard/source-status",
                        json={"node": "enrichment", "sources": aggregated_stats},
                        timeout=5.0,
                    )
                except Exception as e:
                    logger.debug(f"Failed to post source status: {e}")
            else:
                logger.debug("No companies to enrich, waiting...")
            
            # Write metrics every 60 seconds
            metrics_counter += POLL_INTERVAL
            if metrics_counter >= 60:
                write_metrics(db)
                metrics_counter = 0
            
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