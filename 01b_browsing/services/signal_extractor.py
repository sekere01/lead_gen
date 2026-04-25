"""Signal extraction from HTML content."""
import re
import logging
from typing import Dict, List, Any

from utils.email_utils import (
    clean_emails,
    FILE_EXTENSION_BLOCKLIST,
    PLACEHOLDER_DOMAINS,
    STRICT_EMAIL_REGEX,
)

logger = logging.getLogger(__name__)

# Contact page patterns
CONTACT_PATTERNS = [
    '/contact', '/contact-us', '/contact.html', '/contact.php', '/about', '/about-us',
    '/team', '/our-team', '/people', '/staff'
]

# Social media domains
SOCIAL_DOMAINS = [
    'linkedin.com', 'facebook.com', 'twitter.com', 'x.com', 'instagram.com',
    'tiktok.com', 'youtube.com'
]

# Parked domain patterns
PARKED_PATTERNS = [
    'domain for sale', 'domain is available', 'coming soon',
    'parked at', 'registrar', 'renew now', 'this domain may be for sale'
]

# Address regex patterns
ADDRESS_PATTERNS = [
    r'\d{1,5}\s+[A-Za-z]+\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|place|pl)',
    r'box\s+\d+',
    r'[A-Z]{1,2}\d{1,2}[A-Z]{1,2}',
    r'\b\d{5}(?:-\d{4})?\b',
]


def extract_signals(html: str, url: str) -> Dict[str, bool]:
    """Extract signals from HTML content."""
    signals = {
        'has_contact_link': False,
        'has_address': False,
        'has_social_links': False,
        'has_email_on_homepage': False,
        'is_parked': False,
        'language_match': False,
    }
    
    html_lower = html.lower()
    
    # Check for parked/placeholder
    for pattern in PARKED_PATTERNS:
        if pattern.lower() in html_lower:
            signals['is_parked'] = True
            break
    
    # Extract contact page link
    for pattern in CONTACT_PATTERNS:
        if pattern in html_lower:
            signals['has_contact_link'] = True
            break
    
    # Check for social links
    for domain in SOCIAL_DOMAINS:
        if domain in html_lower:
            signals['has_social_links'] = True
            break
    
    # Check for address
    for pattern in ADDRESS_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            signals['has_address'] = True
            break
    
    # Check for email on homepage - using stricter extraction
    raw_email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]+\b'
    raw_emails = re.findall(raw_email_pattern, html)
    clean_email_list = clean_emails(raw_emails)
    
    if clean_email_list:
        signals['has_email_on_homepage'] = True
    
    return signals


def extract_emails_from_html(html: str) -> List[str]:
    """Extract and clean emails from HTML content."""
    raw_email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]+\b'
    raw_emails = re.findall(raw_email_pattern, html)
    return clean_emails(raw_emails)


def apply_score(signals: Dict[str, Any], base_score: int) -> int:
    """Calculate final score based on signals."""
    score = base_score
    
    # Apply bonuses (capped at SCORE_MAX)
    if signals.get('has_contact_link'):
        score += 2
    if signals.get('has_address'):
        score += 2
    if signals.get('has_social_links'):
        score += 1
    if signals.get('has_email_on_homepage'):
        score += 2
    if signals.get('language_match'):
        score += 1
    
    # Base signal for page loaded successfully
    score += 1
    
    return score


def get_tier(score: int, max_score: int = 10) -> str:
    """Get tier based on score."""
    if score >= 8:
        return 'strong'
    elif score >= 5:
        return 'good'
    elif score >= 2:
        return 'weak'
    else:
        return 'filtered'