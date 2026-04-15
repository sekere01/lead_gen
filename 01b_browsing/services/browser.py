"""Browser service - httpx + Playwright logic."""
import logging
import httpx
from typing import Tuple, Optional
from config import settings

logger = logging.getLogger(__name__)

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
        f"http://{domain}",
        f"https://www.{domain}",
        f"http://www.{domain}",
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


def fetch_with_playwright(domain: str) -> str:
    """Fetch homepage with Playwright (JS rendering)."""
    urls = [
        f"https://{domain}",
        f"http://{domain}",
    ]
    
    for url in urls:
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=settings.BROWSING_TIMEOUT_PLAYWRIGHT * 1000)
                page.wait_for_load_state('networkidle', timeout=settings.BROWSING_TIMEOUT_PLAYWRIGHT * 1000)
                
                html = page.content()
                browser.close()
                
                logger.debug(f"Playwright fetched {url}")
                return html
                
        except Exception as e:
            logger.debug(f"Playwright error for {url}: {e}")
            continue
    
    return ""


def browse_homepage(domain: str) -> str:
    """Main browse function - httpx first, escalate to Playwright if needed."""
    logger.info(f"Browsing {domain}")
    
    # Try httpx first
    html, needs_pw = fetch_with_httpx(domain)
    
    if not html:
        logger.info(f"httpx failed for {domain}, trying Playwright")
        html = fetch_with_playwright(domain)
        needs_pw = False
    
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