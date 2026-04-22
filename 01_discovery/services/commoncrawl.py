"""CommonCrawl discovery module."""
import json
import logging
import requests
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
import os

logger = logging.getLogger(__name__)

# Cache for latest index
_latest_index = None
_index_cache_age = 0

# Config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'commoncrawl.yaml')


def _load_config() -> dict:
    """Load CommonCrawl config."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _get_latest_index() -> str:
    """Fetch the latest CommonCrawl index dynamically."""
    global _latest_index, _index_cache_age

    headers = {'User-Agent': 'LeadGenDiscovery/1.0 (contact@example.com)'}

    try:
        response = requests.get(
            "https://index.commoncrawl.org/collinfo.json",
            headers=headers,
            timeout=10
        )
        if response.status_code != 200:
            raise ValueError(f"Non-200 response: {response.status_code}")
        indexes = response.json()
        if not indexes or len(indexes) == 0:
            raise ValueError("No indexes returned")
        _latest_index = indexes[0]['id']
        logger.info(f"Using latest CommonCrawl index: {_latest_index}")
        return _latest_index
    except Exception as e:
        logger.warning(f"Failed to fetch latest index: {e}")
        raise ValueError("Could not fetch CommonCrawl index — set enabled: false in config to skip")


def _get_tld_for_region(region: str, config: dict) -> List[str]:
    """Get TLD(s) for a region."""
    region_lower = region.lower().strip() if region else "global"
    
    region_tld_map = config.get('region_tld_map', {})
    fallback_tlds = config.get('fallback_tlds', ['com', 'net', 'org'])
    
    if region_lower == 'global' or not region:
        return fallback_tlds
    
    tld = region_tld_map.get(region_lower, 'com')
    
    # Handle comma-separated TLDs (e.g., "com,net,org")
    if ',' in tld:
        tld_list = tld.split(',')
        return [t.strip() for t in tld_list]
    return [tld]


def _extract_domain(url: str) -> Optional[str]:
    """Extract clean domain from URL."""
    try:
        if not url:
            return None
        
        # Handle URLs without protocol
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]
        
        return domain.lower() if domain else None
    
    except Exception:
        return None


def discover_commoncrawl(keyword: str, region: str = "", max_results: int = 50,
                           keywords: List[str] = None) -> List[Dict[str, Any]]:
    """
    Discover domains via CommonCrawl CDX API.
    Uses parallel TLD queries for faster execution.

    Args:
        keyword: Industry keyword (for fallback if keywords not provided)
        region: Target region for TLD selection
        max_results: Maximum results to return
        keywords: Optional list of URL path keywords (single words, no spaces)
                  If not provided, uses keyword parameter as fallback
    """
    results = []
    seen_domains = set()

    config = _load_config()

    if not config.get('enabled', False):
        logger.info("CommonCrawl disabled in config - skipping")
        return results

    max_results = config.get('max_results', max_results)
    fallback_max = config.get('fallback_max_results', 200)
    min_before_fallback = config.get('min_results_before_fallback', 30)
    timeout = config.get('timeout', 15)
    retry_count = config.get('retry_count', 3)

    tlds = _get_tld_for_region(region, config)

    try:
        index = _get_latest_index()
    except ValueError:
        logger.warning("CommonCrawl index fetch failed — skipping CommonCrawl discovery (service may be down)")
        return results

    base_url = f"https://index.commoncrawl.org/{index}"

    # Build keyword list for pattern matching
    # Use provided keywords, or fall back to keyword-based patterns
    if keywords:
        keyword_patterns = keywords
    elif keyword:
        keyword_patterns = [keyword.lower().replace(' ', '-')]
    else:
        keyword_patterns = []

    # Check if main API is reachable with a quick probe
    _headers = {'User-Agent': 'LeadGenDiscovery/1.0 (contact@example.com)'}
    try:
        probe_response = requests.get(base_url, params={'url': '*.com/', 'output': 'json', 'limit': 1}, headers=_headers, timeout=5)
        if probe_response.status_code != 200:
            logger.warning(f"CommonCrawl API unhealthy ({probe_response.status_code}) — skipping")
            return results
    except Exception as e:
        logger.warning(f"CommonCrawl API unreachable: {e} — skipping")
        return results

    def query_tld(tld: str) -> List[Dict[str, Any]]:
        """Query a single TLD with multiple keyword patterns."""
        tld_results = []

        headers = {
            'User-Agent': 'LeadGenDiscovery/1.0 (contact@example.com)'
        }

        # Build patterns from keywords
        if keyword_patterns:
            patterns = [f"*.{tld}/%{kw}%" for kw in keyword_patterns]
        else:
            patterns = [f"*.{tld}/"]

        for pattern in patterns:
            if len(tld_results) >= max_results:
                break

            for attempt in range(retry_count):
                try:
                    # Extract keyword from pattern for logging
                    pattern_kw = pattern.split('/%')[-1].rstrip('%') if '%' in pattern else ''

                    params = {
                        'url': pattern,
                        'output': 'json',
                        'filter': 'statuscode:200',
                        'limit': max_results,
                    }
                    logger.info(f"CommonCrawl query: {pattern}")

                    response = requests.get(base_url, params=params, headers=headers, timeout=timeout)

                    if response.status_code == 200:
                        lines = response.text.strip().split('\n')

                        for line in lines:
                            if len(tld_results) >= max_results:
                                break

                            try:
                                data = json.loads(line)
                                url = data.get('url', '')
                                domain = _extract_domain(url)

                                if domain and domain not in seen_domains:
                                    seen_domains.add(domain)
                                    tld_results.append({
                                        'domain': domain,
                                        'source': 'commoncrawl',
                                        'score': 2 if pattern_kw else 1
                                    })
                            except json.JSONDecodeError:
                                continue

                    break  # Success for this pattern

                except Exception as e:
                    if attempt < retry_count - 1:
                        wait_time = (attempt + 1) * 3
                        logger.warning(f"CommonCrawl retry {attempt + 1}/{retry_count} for {pattern}: {e}")
                        time.sleep(wait_time)
                    else:
                        logger.warning(f"CommonCrawl query failed for {pattern} after {retry_count} attempts")

        return tld_results

    # Run TLD queries in parallel using ThreadPoolExecutor pattern
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(tlds)))) as executor:
        futures = {executor.submit(query_tld, tld): tld for tld in tlds}

        for future in as_completed(futures):
            if len(results) >= max_results:
                break
            tld_results = future.result()
            results.extend(tld_results)

    logger.info(f"CommonCrawl found {len(results)} domains for '{keyword}' (region: {region})")

    return results[:max_results]