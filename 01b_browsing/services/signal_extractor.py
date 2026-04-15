"""Signal extraction from HTML content."""
import re
import logging
from typing import Dict, List, Any, Set
from urllib.parse import urlparse

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
    'parked at', 'registrar', 'renew now',
    'this domain may be for sale'
]

# Address regex patterns
ADDRESS_PATTERNS = [
    r'\d{1,5}\s+[A-Za-z]+\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|place|pl)',
    r'box\s+\d+',
    r'[A-Z]{1,2}\d{1,2}[A-Z]{1,2}',
    r'\b\d{5}(?:-\d{4})?\b',
]

# File extension blocklist - reject emails that are actually image filenames
FILE_EXTENSION_BLOCKLIST = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.ico', '.pdf', '.zip',
    '.mp4', '.mp3', '.css', '.js', '.json', '.xml', '.php', '.html', '.htm',
    '.JPG', '.JPEG', '.PNG', '.WEBP', '.GIF', '.SVG', '.ICO', '.PDF', '.ZIP',
}

# Placeholder domain blocklist - template/placeholder emails
PLACEHOLDER_DOMAINS = {
    'company.com', 'example.com', 'test.com', 'domain.com', 
    'email.com', 'yoursite.com', 'localhost', 'sitename.com',
    'yourcompany.com', 'yourdomain.com', 'sample.com', 'demo.com',
}

# Strict email regex - enforces valid format
# Local: alphanumeric + . - _ +
# Domain: valid hostname
# TLD: 2-6 letters only (no concatenated like .com.ngcom)
STRICT_EMAIL_REGEX = re.compile(
    r'^[A-Za-z0-9._%+-]{2,}@'  # Local part: min 2 chars
    r'[A-Za-z0-9.-]+\.'         # Domain part
    r'[A-Za-z]{2,6}$'           # TLD: 2-6 letters only
)


# Common TLDs for detecting concatenated TLDs
KNOWN_TLDS = {'com', 'org', 'net', 'io', 'co', 'info', 'biz', 'edu', 'gov',
              'uk', 'au', 'ca', 'de', 'fr', 'jp', 'cn', 'in', 'ng', 'br',
              'ru', 'mx', 'es', 'it', 'nl', 'pl', 'ch', 'se', 'no', 'fi',
              'at', 'be', 'dk', 'ie', 'nz', 'sg', 'hk', 'kr', 'id', 'th',
              'vn', 'my', 'ph', 'pk', 'bd', 'za', 'eg', 'sa', 'ae', 'il'}


def is_valid_tld(tld: str, full_domain: str) -> bool:
    """Validate TLD is 2-6 characters, letters only, and not concatenated."""
    if not tld:
        return False
    if len(tld) < 2 or len(tld) > 6:
        return False
    if not tld.isalpha():
        return False
    
    # Check for duplicate TLD: e.g., nlnl = nl + nl, comcom = com + com
    # If TLD is exactly 2x a known TLD, it's invalid
    for known in KNOWN_TLDS:
        if tld == known + known:
            return False
    
    # Detect concatenated TLDs like .com.ngcom, .co.uk
    # Common valid multi-part TLDs
    valid_multi_tlds = {'.co.uk', '.com.au', '.com.br', '.com.mx', '.co.in', 
                        '.co.jp', '.com.ng', '.org.uk', '.net.au'}
    
    # Check if domain ends with a known multi-part TLD
    for multi in valid_multi_tlds:
        if full_domain.lower().endswith(multi):
            return True
    
    # Reject if the domain looks like it has concatenated TLDs
    # e.g., site.com.ngcom - the TLD 'ngcom' contains 'ng' which is a real TLD
    # This is a heuristic - if domain has 'com' followed by more letters
    lower = full_domain.lower()
    if '.com.' in lower:
        # e.g., site.com.ngcom - after .com there's 'ngcom'
        parts_after_com = lower.split('.com.')[-1]
        if len(parts_after_com) > 0 and parts_after_com.replace('', ' ').strip():
            return False  # Likely concatenated
    
    return True


def repair_concatenated_tld(email: str) -> str | None:
    """
    Attempt to repair an email with a concatenated TLD.
    e.g., info@site.com.ngcom → info@site.com.ng
    e.g., info@company.nlnl → info@company.nl (duplicate TLD)
    Returns None if repair fails.
    """
    if '@' not in email:
        return None
    
    local, domain = email.lower().split('@', 1)
    
    # Split domain into parts
    parts = domain.split('.')
    if len(parts) < 2:
        return None
    
    # Get the TLD (last part)
    tld = parts[-1]
    
    # Check for duplicate TLD: e.g., nlnl = nl + nl, comcom = com + com
    # If TLD is exactly 2x a known TLD, strip the duplicate
    for known in KNOWN_TLDS:
        if tld == known + known:
            # Found duplicate like "nlnl" = "nl" + "nl"
            repaired_parts = parts[:-1] + [known]
            repaired_domain = '.'.join(repaired_parts)
            repaired_email = f"{local}@{repaired_domain}"
            return repaired_email
    
    # Check if TLD can be split into two known TLDs
    # e.g., "ngcom" = "ng" + "com" → try "ng" as TLD
    for known in KNOWN_TLDS:
        if tld.startswith(known):
            remaining = tld[len(known):]
            if remaining in KNOWN_TLDS:
                # Found split: "ngcom" = "ng" + "com"
                # Try the first part as the real TLD
                if len(known) >= 2 and len(known) <= 6:
                    potential_tld = known
                    repaired_parts = parts[:-1] + [potential_tld]
                    repaired_domain = '.'.join(repaired_parts)
                    
                    if is_valid_tld(potential_tld, f"x@{repaired_domain}"):
                        repaired_email = f"{local}@{repaired_domain}"
                        return repaired_email
    
    # Fallback: check if TLD ends with known TLD
    # e.g., "xyzcom" ends with "com"
    for known in KNOWN_TLDS:
        if tld.endswith(known) and tld != known:
            potential_tld = known
            if len(potential_tld) >= 2 and len(potential_tld) <= 6:
                repaired_parts = parts[:-1] + [potential_tld]
                repaired_domain = '.'.join(repaired_parts)
                
                if is_valid_tld(potential_tld, f"x@{repaired_domain}"):
                    repaired_email = f"{local}@{repaired_domain}"
                    return repaired_email
    
    return None


def clean_emails(raw_emails: List[str]) -> List[str]:
    """
    Clean and validate extracted emails with multiple filters.
    Returns only valid, unique emails.
    """
    valid_emails: Set[str] = set()
    
    for email in raw_emails:
        email = email.strip()
        if not email or '@' not in email:
            continue
        
        # Check local part min length (before @)
        local_part = email.split('@')[0] if '@' in email else ''
        if len(local_part) < 2:
            logger.debug(f"Rejected {email} — local part too short")
            continue
        
        # Check for file extension at the end (image filename fake emails)
        lower_email = email.lower()
        has_extension = any(lower_email.endswith(ext) for ext in FILE_EXTENSION_BLOCKLIST)
        if has_extension:
            logger.debug(f"Rejected {email} — file extension")
            continue
        
        # Check placeholder domains
        domain = email.lower().split('@')[1] if '@' in email else ''
        if domain in PLACEHOLDER_DOMAINS:
            logger.debug(f"Rejected {email} — placeholder domain")
            continue
        
        # Strict regex validation
        if not STRICT_EMAIL_REGEX.match(email.lower()):
            logger.debug(f"Rejected {email} — invalid format")
            continue
        
        # Validate TLD (last part after final dot)
        parts = email.lower().split('.')
        if len(parts) >= 2:
            tld = parts[-1]
            full_domain = email.lower()
            if not is_valid_tld(tld, full_domain):
                # Try to repair concatenated TLD
                repaired = repair_concatenated_tld(email)
                if repaired and is_valid_tld(repaired.split('@')[1].split('.')[-1], repaired):
                    logger.info(f"Repaired {email} → {repaired}")
                    valid_emails.add(repaired)
                else:
                    logger.debug(f"Rejected {email} — invalid TLD ({tld}), repair failed")
                continue
        
        valid_emails.add(email.lower())
    
    return sorted(list(valid_emails))


def extract_signals(html: str, url: str, region: str = "") -> Dict[str, Any]:
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
    
    # Check language match (simple check)
    if region:
        region_langs = {
            'china': ['zh', 'cn'],
            'germany': ['de'],
            'france': ['fr'],
            'japan': ['ja'],
            'korea': ['ko'],
            'brazil': ['pt'],
            'russia': ['ru'],
            'spain': ['es'],
            'italy': ['it'],
            'india': ['hi'],
        }
        lang_codes = region_langs.get(region.lower(), [])
        for lang in lang_codes:
            if f'lang="{lang}' in html_lower or f"lang='{lang}" in html_lower:
                signals['language_match'] = True
                break
    
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