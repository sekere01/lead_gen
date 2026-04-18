"""
Email Verification Module.
Fast-track verification: Syntax → Disposable Domain → MX Records.
"""
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
import dns.resolver

try:
    from email_validator import validate_email, EmailNotValidError
except ImportError:
    validate_email = None

try:
    from disposable_email_domains import blocklist as disposable_blocklist
except ImportError:
    disposable_blocklist = set()

logger = logging.getLogger(__name__)

from utils.email_utils import EMAIL_REGEX


def validate_syntax(email: str) -> Tuple[bool, Optional[str]]:
    """Layer 1: Validate email syntax."""
    if not email or '@' not in email:
        return False, "invalid_format"
    
    if validate_email:
        try:
            validation = validate_email(email)
            return True, None
        except EmailNotValidError as e:
            return False, str(e)
    else:
        if EMAIL_REGEX.match(email.strip()):
            return True, None
        return False, "invalid_syntax"


def is_disposable_email(email: str) -> bool:
    """Layer 2: Check if email uses a disposable domain."""
    if '@' not in email:
        return False
    domain = email.split('@')[1].lower()
    if domain in disposable_blocklist:
        logger.debug(f"Disposable domain detected: {domain}")
        return True
    return False


def has_mx_record(email: str) -> Tuple[bool, Optional[List[Dict[str, Any]]]]:
    """Layer 3: Check if domain has MX records."""
    if '@' not in email:
        return False, None
    domain = email.split('@')[1].lower()
    
    try:
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_list = []
        for record in mx_records:
            mx_list.append({
                'preference': record.preference,
                'exchange': str(record.exchange).rstrip('.')
            })
        mx_list.sort(key=lambda x: x['preference'])
        return True, mx_list
    except dns.resolver.NXDOMAIN:
        return False, None
    except dns.resolver.NoAnswer:
        return False, None
    except Exception as e:
        logger.debug(f"MX lookup failed for {domain}: {e}")
        return False, None


def verify_email_fast(email: str) -> Dict[str, Any]:
    """Fast verification: Syntax + Disposable + MX (no SMTP)."""
    result = {
        "email": email,
        "is_valid_syntax": False,
        "is_disposable": False,
        "has_mx_records": False,
        "is_verified": False,
        "verification_status": "invalid",
        "details": {}
    }
    
    is_valid_syntax, syntax_error = validate_syntax(email)
    result["is_valid_syntax"] = is_valid_syntax
    result["details"]["syntax_error"] = syntax_error
    
    if not is_valid_syntax:
        result["verification_status"] = "invalid_syntax"
        return result
    
    if is_disposable_email(email):
        result["is_disposable"] = True
        result["verification_status"] = "disposable_domain"
        return result
    
    has_mx, mx_records = has_mx_record(email)
    result["has_mx_records"] = has_mx
    result["details"]["mx_records"] = mx_records
    
    if not has_mx:
        result["verification_status"] = "no_mx_records"
        return result
    
    result["is_verified"] = True
    result["verification_status"] = "valid_verified"
    
    return result
