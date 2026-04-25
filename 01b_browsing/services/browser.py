"""Browser service - httpx + Playwright logic."""
import logging
import httpx
import re
from datetime import datetime
from typing import Tuple, Optional
from contextlib import contextmanager
from config import settings
from shared_models.company import Company
from shared_models import Base

logger = logging.getLogger(__name__)

_playwright_installed: Optional[bool] = None


def _update_heartbeat(db, company_id: int) -> None:
    """Update browse_heartbeat every 5 minutes to prevent premature watchdog triggers."""
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            company.browse_heartbeat = datetime.now()
            db.commit()
            logger.debug(f"Heartbeat refreshed for company {company_id}")
    except Exception as e:
        logger.warning(f"Heartbeat refresh failed for {company_id}: {e}")


def _check_playwright_available() -> bool:
    """Check if Playwright is available without importing it."""
    global _playwright_installed
    if _playwright_installed is not None:
        return _playwright_installed
    try:
        from playwright.sync_api import sync_playwright
        _playwright_installed = True
        return True
    except ImportError:
        _playwright_installed = False
        return False

EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)


class BrowserContext:
    """Context manager for Playwright browser lifecycle — ensures cleanup on any exception."""

    def __init__(self, timeout_playwright: int = 30):
        self.timeout = timeout_playwright
        self.playwright = None
        self.browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().__enter__()
        self.browser = self.playwright.chromium.launch(headless=True)
        return self

    def __exit__(self, *args):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.__exit__(*args)

    def new_page(self):
        return self.browser.new_page()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def check_needs_playwright(html: str) -> bool:
    """Check if HTML appears JS-rendered (minimal content)."""
    if not html:
        return True
    
    # Very short content suggests JS rendering
    if len(html.strip()) < 500:
        return True
    
    # Check for common empty/skeleton patterns
    if '<html>' in html.lower() and '<body>' in html.lower():
        body_start = html.lower().find('<body>')
        body_end = html.lower().find('</body>')
        if body_end > body_start:
            body_content = html[body_start:body_end]
            # Very minimal body content
            if len(body_content.strip()) < 200:
                return True
    
    return False


def fetch_with_httpx(domain: str) -> Tuple[str, bool]:
    """Fetch homepage with httpx. Returns (html, needs_playwright)."""
    urls = [
        f"https://{domain}",
        f"https://www.{domain}",
    ]
    
    for url in urls:
        try:
            response = httpx.get(
                url,
                timeout=settings.BROWSING_TIMEOUT_HTTP,
                headers=HEADERS,
                follow_redirects=True
            )
            
            if response.status_code == 200:
                html = response.text
                # Rich content — skip playwright check entirely
                if len(html) >= 2000:
                    return html, False
                # Short content — check if it looks JS-rendered
                needs_pw = check_needs_playwright(html)
                logger.debug(f"httpx fetched {url}: status={response.status_code}, needs_pw={needs_pw}")
                return html, needs_pw
                
        except httpx.TimeoutException:
            logger.debug(f"httpx timeout for {url}")
            continue
        except Exception as e:
            logger.debug(f"httpx error for {url}: {e}")
            continue
    
    return "", False


def fetch_with_playwright(domain: str) -> Tuple[str, Optional[str]]:
    """
    Fetch homepage with Playwright (JS rendering).
    Returns (html, error_reason). error_reason is None on success,
    or a string describing the failure.
    """
    if not _check_playwright_available():
        return "", "playwright_not_installed"

    urls = [
        f"https://{domain}",
    ]

    for url in urls:
        try:
            with BrowserContext(timeout_playwright=settings.BROWSING_TIMEOUT_PLAYWRIGHT) as ctx:
                page = ctx.new_page()
                page.goto(url, timeout=settings.BROWSING_TIMEOUT_PLAYWRIGHT * 1000)
                page.wait_for_load_state(
                    'networkidle', timeout=settings.BROWSING_TIMEOUT_PLAYWRIGHT * 1000
                )
                html = page.content()
            logger.debug(f"Playwright fetched {url}")
            return html, None

        except ImportError as e:
            return "", f"playwright_not_installed: {e}"
        except httpx.TimeoutException as e:
            return "", f"playwright_timeout: {e}"
        except Exception as e:
            err_str = str(e).lower()
            if 'name' in err_str and 'headers' in err_str:
                return "", f"playwright_not_installed: {e}"
            logger.debug(f"Playwright error for {url}: {e}")
            continue

    return "", "all_urls_failed"


def browse_homepage(domain: str, db=None, company_id: int = None) -> str:
    """Main browse function - httpx first, escalate to Playwright if needed."""
    # Heartbeat refresh after HTTP fetch (before potentially slow Playwright)
    if db and company_id:
        _update_heartbeat(db, company_id)
    
    html, needs_pw = fetch_with_httpx(domain)
    
    if not html:
        # httpx failed entirely — try Playwright
        logger.info(f"httpx failed for {domain}, trying Playwright")
        html, pw_error = fetch_with_playwright(domain)
        if pw_error:
            if pw_error == "playwright_not_installed":
                logger.warning(f"Playwright not installed — skipping JS rendering for {domain}")
            elif "timeout" in pw_error:
                logger.warning(f"Playwright timeout for {domain}: {pw_error}")
            else:
                logger.warning(f"Playwright failed for {domain}: {pw_error}")
    elif needs_pw:
        # httpx succeeded but content looks JS-rendered — try Playwright
        logger.info(f"httpx returned short content for {domain}, trying Playwright")
        html, pw_error = fetch_with_playwright(domain)
        if pw_error:
            logger.warning(f"Playwright failed for {domain}: {pw_error}")
    
    if not html:
        logger.warning(f"No content fetched for {domain}")
        return ""
    
    return html


def extract_emails_from_html(html: str) -> list:
    """Extract email addresses from HTML."""
    import re
    
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, html)
    
    # Dedupe and lowercase
    unique = list(set(e.lower() for e in emails if '@' in e))
    return unique