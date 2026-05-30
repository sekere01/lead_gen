"""
Sorter Service — MX-based email classification and provider resolution.
Sky Email Sorter integration module.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import dns.resolver
from utils.email_utils import classify_provider

logger = logging.getLogger(__name__)


def extract_mx_domain(mx_exchange: str) -> str:
    """Extract the base domain from an MX exchange hostname.
    e.g. 'aspmx.l.google.com' -> 'google.com'
    """
    if not mx_exchange:
        return ''
    parts = mx_exchange.lower().rstrip('.').split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:])
    return mx_exchange


def resolve_mx(domain: str) -> Optional[str]:
    """Resolve the primary MX record for a domain.
    Returns the exchange hostname or None.
    """
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_list = []
        for record in records:
            mx_list.append((record.preference, str(record.exchange).rstrip('.')))
        mx_list.sort(key=lambda x: x[0])
        if mx_list:
            return mx_list[0][1]
    except Exception:
        pass
    return None


def bulk_resolve_mx(domains: List[str], max_workers: int = 10) -> dict:
    """Resolve MX for multiple domains in parallel.
    Returns dict of {domain: mx_exchange_or_none}.
    """
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(resolve_mx, d): d for d in domains}
        for future in as_completed(futures):
            domain = futures[future]
            try:
                results[domain] = future.result()
            except Exception:
                results[domain] = None
    return results


def update_contact_provider(db, contact_id: int, mx_domain: str, provider: str) -> None:
    """Update a contact's mx_domain and provider fields."""
    from shared_models import Contact
    db.query(Contact).filter(Contact.id == contact_id).update(
        {'mx_domain': mx_domain, 'provider': provider}
    )
