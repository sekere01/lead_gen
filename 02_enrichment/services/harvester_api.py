"""
theHarvester REST API client.
Calls theHarvester container running at http://localhost:5000
"""
import logging
import os
from typing import List, Tuple, Optional
import httpx

from config import settings

logger = logging.getLogger(__name__)

HARVESTER_API_URL = os.getenv("HARVESTER_API_URL", "http://localhost:5000")
HARVESTER_SOURCES = os.getenv("HARVESTER_SOURCES", "duckduckgo,bing").split(",")
HARVESTER_LIMIT = int(os.getenv("HARVESTER_LIMIT", "500"))


def harvest_emails(domain: str, sources: Optional[List[str]] = None, limit: int = None) -> Tuple[List[str], List[str]]:
    """
    Harvest emails and hosts via theHarvester REST API.
    
    Args:
        domain: Domain to search (e.g., 'example.com')
        sources: List of sources to use (default: from config HARVESTER_SOURCES)
        limit: Max results per source (default: from config HARVESTER_LIMIT)
    
    Returns:
        Tuple of (emails: List[str], hosts: List[str])
    """
    if sources is None:
        sources = HARVESTER_SOURCES
    
    if limit is None:
        limit = HARVESTER_LIMIT
    
    emails = []
    hosts = []
    
    source_str = ",".join(sources)
    
    try:
        url = f"{HARVESTER_API_URL}/query"
        params = {
            "domain": domain,
            "source": source_str,
            "limit": limit
        }
        
        logger.info(f"Calling theHarvester API for {domain} with sources: {source_str}")
        
        response = httpx.get(url, params=params, timeout=60.0)
        response.raise_for_status()
        
        data = response.json()
        
        raw_emails = data.get("emails", [])
        unique_emails = list(set(e.lower() for e in raw_emails if e and "@" in e))
        emails = unique_emails
        
        raw_hosts = data.get("hosts", [])
        hosts = [h.split(":")[0] for h in raw_hosts if h]
        
        logger.info(f"Harvester API: found {len(emails)} emails, {len(hosts)} hosts for {domain}")
        
    except httpx.TimeoutException:
        logger.warning(f"Harvester API timeout for {domain}")
    except httpx.HTTPError as e:
        logger.warning(f"Harvester API error for {domain}: {e}")
    except Exception as e:
        logger.warning(f"Harvester error for {domain}: {e}")
    
    return emails, hosts