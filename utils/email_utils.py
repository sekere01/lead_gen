"""Shared email utilities — canonical regex and validation across all services."""
import re
from typing import List, Set

EMAIL_REGEX = re.compile(
    r'[A-Za-z0-9._%+-]{2,}@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}'
)

STRICT_EMAIL_REGEX = re.compile(
    r'^[A-Za-z0-9._%+-]{2,}@'
    r'[A-Za-z0-9.-]+\.'
    r'[A-Za-z]{2,6}$'
)

FILE_EXTENSION_BLOCKLIST = {
    '.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg', '.ico', '.pdf', '.zip',
    '.mp4', '.mp3', '.css', '.js', '.json', '.xml', '.php', '.html', '.htm',
    '.JPG', '.JPEG', '.PNG', '.WEBP', '.GIF', '.SVG', '.ICO', '.PDF', '.ZIP',
}

PLACEHOLDER_DOMAINS = {
    'company.com', 'example.com', 'example.org', 'example.net', 'test.com',
    'domain.com', 'email.com', 'yoursite.com', 'localhost', 'sitename.com',
    'yourcompany.com', 'yourdomain.com', 'sample.com', 'demo.com',
}

GENERIC_LOCAL_PARTS = {
    'user', 'name', 'email', 'test', 'template', 'placeholder',
    'noreply', 'no-reply', 'donotreply', 'contact', 'admin', 'support',
    'help', 'sales', 'info', 'webmaster', 'hostmaster', 'postmaster',
}

NOISE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', 
                '.ico', '.2x', '.pdf', '.mp4', '.zip'}

EMAIL_PREFIX_NOISE = re.compile(
    r'^(u003e|u003c|\\u003e|\\u003c|&gt;|&lt;|&amp;|%3e|%3c)+',
    re.IGNORECASE
)


def clean_email_prefixes(email: str) -> str:
    """Strip HTML/Unicode entity prefixes from extracted emails."""
    return EMAIL_PREFIX_NOISE.sub('', email).strip()


def is_noise_email(email: str) -> bool:
    """
    Check if email is noise (image filenames, tracking pixels, etc).
    Layer 1: Reject if local part or domain contains file extension patterns.
    Layer 2: Reject malformed domains (consecutive dots, TLD > 6 chars, digits in TLD).
    """
    if '@' not in email:
        return True
    
    local = email.split('@')[0].lower()
    domain = email.split('@')[1].lower() if '@' in email else ''
    
    # Layer 1a: Reject URL-encoded artifacts
    if '%' in email:
        return True
    
    # Layer 1c: Reject timestamp-prefixed message IDs (e.g. 20260403191942.21410-1-user@domain.com)
    local_part = email.split('@')[0]
    if re.match(r'^\d{8,}\.', local_part):
        return True
    
    # Layer 1b: File extension rejection
    if any(ext in local for ext in NOISE_EXTENSIONS):
        return True
    if any(domain.endswith(ext) for ext in NOISE_EXTENSIONS):
        return True
    
    # Layer 2: Malformed domain rejection
    if '..' in domain:
        return True
    if '.' in domain:
        tld = domain.split('.')[-1]
        if len(tld) > 6:
            return True
        if any(c.isdigit() for c in tld):
            return True
    
    return False


def is_placeholder_email(email: str) -> bool:
    """
    Check if email is a placeholder.
    Rejects: exact placeholder domains, OR generic local + placeholder domain.
    Allows: generic local parts with real domains (e.g., noreply@realcompany.com).
    """
    if '@' not in email:
        return True
    local_part, domain = email.lower().split('@', 1)
    
    # Reject if domain is a placeholder domain
    if domain in PLACEHOLDER_DOMAINS:
        return True
    
    # Reject if generic local part AND placeholder domain (the AND condition)
    if local_part in GENERIC_LOCAL_PARTS and domain in PLACEHOLDER_DOMAINS:
        return True
    
    return False

KNOWN_TLDS = {
    'com', 'org', 'net', 'io', 'co', 'info', 'biz', 'edu', 'gov',
    'uk', 'au', 'ca', 'de', 'fr', 'jp', 'cn', 'in', 'ng', 'br',
    'ru', 'mx', 'es', 'it', 'nl', 'pl', 'ch', 'se', 'no', 'fi',
    'at', 'be', 'dk', 'ie', 'nz', 'sg', 'hk', 'kr', 'id', 'th',
    'vn', 'my', 'ph', 'pk', 'bd', 'za', 'eg', 'sa', 'ae', 'il',
}


def is_valid_tld(tld: str, full_domain: str) -> bool:
    """Validate TLD is 2-6 characters, letters only, and not concatenated."""
    if not tld or len(tld) < 2 or len(tld) > 6 or not tld.isalpha():
        return False
    for known in KNOWN_TLDS:
        if tld == known + known:
            return False
    valid_multi_tlds = {
        '.co.uk', '.com.au', '.com.br', '.com.mx', '.co.in',
        '.co.jp', '.com.ng', '.org.uk', '.net.au',
    }
    for multi in valid_multi_tlds:
        if full_domain.lower().endswith(multi):
            return True
    lower = full_domain.lower()
    if '.com.' in lower:
        parts_after_com = lower.split('.com.')[-1]
        if parts_after_com and parts_after_com.replace('', ' ').strip():
            return False
    return True


def repair_concatenated_tld(email: str):
    """Attempt to repair an email with a concatenated TLD."""
    if '@' not in email:
        return None
    local, domain = email.lower().split('@', 1)
    parts = domain.split('.')
    if len(parts) < 2:
        return None
    tld = parts[-1]
    for known in KNOWN_TLDS:
        if tld == known + known:
            repaired_parts = parts[:-1] + [known]
            return f"{local}@{'.'.join(repaired_parts)}"
    for known in KNOWN_TLDS:
        if tld.startswith(known):
            remaining = tld[len(known):]
            if remaining in KNOWN_TLDS:
                potential_tld = known
                repaired_parts = parts[:-1] + [potential_tld]
                repaired_domain = '.'.join(repaired_parts)
                if is_valid_tld(potential_tld, f"x@{repaired_domain}"):
                    return f"{local}@{repaired_domain}"
    for known in KNOWN_TLDS:
        if tld.endswith(known) and tld != known:
            potential_tld = known
            repaired_parts = parts[:-1] + [potential_tld]
            repaired_domain = '.'.join(repaired_parts)
            if is_valid_tld(potential_tld, f"x@{repaired_domain}"):
                return f"{local}@{repaired_domain}"
    return None


def extract_emails_from_text(text: str) -> List[str]:
    """Extract email addresses from raw text using regex."""
    if not text:
        return []
    matches = EMAIL_REGEX.findall(text)
    valid_emails: Set[str] = set()
    for email in matches:
        email = email.strip().lower()
        if len(email) < 5 or '@' not in email or email.count('@') != 1:
            continue
        local, domain = email.rsplit('@', 1)
        if not local or not domain or '.' not in domain or len(domain) < 3:
            continue
        valid_emails.add(email)
    return sorted(valid_emails)


def extract_emails_regex(text: str) -> List[str]:
    """Alias for extract_emails_from_text for backwards compatibility."""
    return extract_emails_from_text(text)


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
        lower_email = email.lower()
        local_part = lower_email.split('@')[0]
        if len(local_part) < 2:
            continue
        if any(lower_email.endswith(ext) for ext in FILE_EXTENSION_BLOCKLIST):
            continue
        # E2: Use comprehensive placeholder check (generic local + placeholder domain)
        if is_placeholder_email(lower_email):
            continue
        if not STRICT_EMAIL_REGEX.match(lower_email):
            continue
        parts = lower_email.split('.')
        if len(parts) >= 2:
            tld = parts[-1]
            full_domain = lower_email
            if not is_valid_tld(tld, full_domain):
                repaired = repair_concatenated_tld(email)
                if repaired and is_valid_tld(repaired.split('@')[1].split('.')[-1], repaired):
                    valid_emails.add(repaired.lower())
                    continue
            valid_emails.add(lower_email)
    return sorted(list(valid_emails))


def validate_email_format(email: str) -> bool:
    """Basic email format validation."""
    if not email or '@' not in email:
        return False
    return bool(EMAIL_REGEX.match(email.strip()))