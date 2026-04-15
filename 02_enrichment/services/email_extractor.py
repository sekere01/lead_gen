"""Email extractor using regex patterns."""
import re
from typing import List

EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)


def extract_emails_regex(text: str) -> List[str]:
    """
    Extract email addresses from text using regex.
    
    Args:
        text: HTML or plain text to search
    
    Returns:
        List of unique email addresses found
    """
    if not text:
        return []
    
    matches = EMAIL_REGEX.findall(text)
    
    valid_emails = []
    seen = set()
    
    for email in matches:
        email = email.lower().strip()
        
        if email in seen:
            continue
        if len(email) < 5 or '@' not in email:
            continue
        if email.count('@') != 1:
            continue
        
        local, domain = email.rsplit('@', 1)
        if not local or not domain or '.' not in domain:
            continue
        if len(domain) < 3:
            continue
        
        seen.add(email)
        valid_emails.append(email)
    
    return valid_emails
