"""
Waterfall Verification Engine for email validation.
Implements multi-step verification: syntax -> MX records -> SMTP handshake.
"""
import re
import smtplib
import socket
import dns.resolver
from typing import Tuple, Optional
from email.utils import parseaddr

import logging
logger = logging.getLogger(__name__)

from utils.email_utils import EMAIL_REGEX


def validate_email_syntax(email: str) -> bool:
    """Step 1: Validate email syntax using regex."""
    if not email or not isinstance(email, str):
        return False
    email_addr = parseaddr(email)[1] if '@' in email else email
    return bool(EMAIL_REGEX.match(email_addr.strip()))


def check_mx_records(domain: str) -> Tuple[bool, Optional[list]]:
    """Step 2: Check MX records for domain existence."""
    try:
        domain = domain.strip().lower()
        mx_records = dns.resolver.resolve(domain, 'MX')
        mx_list = []
        for record in mx_records:
            mx_list.append({
                'preference': record.preference,
                'exchange': str(record.exchange).rstrip('.')
            })
        mx_list.sort(key=lambda x: x['preference'])
        return True, mx_list
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception:
        return False, None


def smtp_handshake(email: str, mx_records: list, timeout: int = 5) -> Tuple[bool, str]:
    """Step 3: Perform SMTP RCPT TO handshake to verify mailbox."""
    if not mx_records:
        return False, "No MX records available"

    for mx_info in mx_records:
        mx_host = mx_info['exchange']
        try:
            server = smtplib.SMTP(timeout=timeout)
            server.connect(mx_host, 25)
            server.sock.settimeout(timeout)
            server.helo()
            server.mail('')
            code, message = server.rcpt(str(email))
            server.quit()

            if code in [250, 251]:
                return True, f"SMTP success: {message.decode('utf-8') if isinstance(message, bytes) else message}"
            elif code in [450, 550, 551, 554]:
                return False, f"SMTP failed: {message.decode('utf-8') if isinstance(message, bytes) else message}"
            else:
                return False, f"SMTP temporary error {code}: {message.decode('utf-8') if isinstance(message, bytes) else message}"

        except smtplib.SMTPConnectError as e:
            logger.debug(f"SMTP connect failed for {mx_host}: {e}")
            continue
        except smtplib.SMTPServerDisconnected as e:
            logger.debug(f"SMTP disconnected for {mx_host}: {e}")
            continue
        except socket.timeout as e:
            logger.debug(f"SMTP socket timeout for {mx_host}: {e}")
            continue
        except Exception as e:
            logger.warning(f"SMTP error for {email} on {mx_host}: {e}")
            continue

    return False, "Could not connect to any mail server"


def verify_email(email: str) -> dict:
    """Main verification function that runs the waterfall verification process."""
    result = {
        'email': email,
        'is_valid_syntax': False,
        'has_mx_records': False,
        'mx_records': None,
        'is_deliverable': False,
        'smtp_message': '',
        'is_catch_all': False,
        'overall_result': 'invalid'
    }
    
    if not validate_email_syntax(email):
        result['smtp_message'] = 'Invalid email syntax'
        return result
    
    result['is_valid_syntax'] = True
    
    try:
        domain = email.split('@')[1].lower()
    except IndexError:
        result['smtp_message'] = 'Invalid email format'
        return result
    
    has_mx, mx_records = check_mx_records(domain)
    result['has_mx_records'] = has_mx
    result['mx_records'] = mx_records
    
    if not has_mx:
        result['smtp_message'] = 'No MX records found for domain'
        result['overall_result'] = 'invalid'
        return result
    
    try:
        is_deliverable, smtp_message = smtp_handshake(email, mx_records, timeout=5)
        result['is_deliverable'] = is_deliverable
        result['smtp_message'] = smtp_message
    except Exception as e:
        result['is_deliverable'] = False
        result['smtp_message'] = f'SMTP verification skipped/failed: {str(e)}'
    
    result['overall_result'] = 'valid_verified' if result['is_deliverable'] else 'valid_catch_all'
    
    return result
