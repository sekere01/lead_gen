"""
Search Orchestration Module for Lead Discovery.
Combines DuckDuckGo (ddgs) and SearXNG for comprehensive domain discovery.
"""
import os
import time
import logging
from typing import List, Set, Optional, Dict, Any, Tuple
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from ddgs import DDGS

from config import settings

DDGS_TIMEOUT = 10

logger = logging.getLogger(__name__)

# In-memory TTL cache — no file I/O per search call
_memory_cache: Dict[str, tuple[List[str], float]] = {}


class SearchOrchestrationError(Exception):
    """Custom exception for search orchestration errors."""
    pass


DIRECTORY_DOMAINS = [
    'techbehemoths.com', 'clutch.co', 'goodfirms.co', 'g2.com',
    'capterra.com', 'themanifest.com', 'goodtal.com', 'lusha.com',
    'crunchbase.com', 'linkedin.com', 'yelp.com', 'yellowpages.com',
    'wikipedia.org', 'reddit.com', 'quora.com', 'cybersecurityintelligence.com',
    'blog.layer3.ng', 'qualysec.com', 'snapnetsolutions.com'
]


def _get_cached_results(query: str) -> Optional[List[str]]:
    """Get cached search results if not expired (in-memory TTL cache)."""
    cache_hours = getattr(settings, 'SEARCH_CACHE_HOURS', 1)
    entry = _memory_cache.get(query)
    if entry:
        domains, timestamp = entry
        if time.time() - timestamp < cache_hours * 3600:
            logger.info(f"Using cached results for query: '{query}'")
            return domains
    return None


def _save_cached_results(query: str, domains: List[str]) -> None:
    """Save search results to in-memory cache."""
    _memory_cache[query] = (domains, time.time())


def generate_query_variations(base_query: str, region: str = "") -> List[str]:
    """Generate multiple query variations for wider search coverage."""
    if region is None:
        region = ""
    elif not isinstance(region, str):
        region = str(region)

    variations = []
    region_suffix = f" in {region}" if region and region.lower() != "global" else ""
    variations.append(base_query + region_suffix)

    if region:
        region_lower = region.lower()
        tld_map = {
            'turkey': 'com.tr', 'nigeria': 'com.ng', 'usa': 'com',
            'united states': 'com', 'uk': 'co.uk', 'united kingdom': 'co.uk',
        }
        tld = tld_map.get(region_lower, 'com')
        variations.append(f"{base_query} site:.{tld}")
    else:
        variations.append(f"{base_query} company")

    seen = set()
    unique_variations = []
    for v in variations:
        if v not in seen:
            seen.add(v)
            unique_variations.append(v)

    return unique_variations[:3]


def extract_domain(url: str) -> Optional[str]:
    """Extract root domain from a URL."""
    try:
        if not url or not isinstance(url, str):
            return None
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


def is_corporate_domain(domain: str) -> bool:
    """Filter out non-corporate and directory domains."""
    if not domain or not isinstance(domain, str):
        return False
    domain = domain.lower().strip()
    if len(domain) < 4:
        return False
    for d in DIRECTORY_DOMAINS:
        if d in domain:
            return False
    excluded = [
        'google.', 'youtube.', 'facebook.', 'twitter.', 'instagram.',
        'linkedin.', 'wikipedia.', 'reddit.', 'quora.', 'pinterest.',
        'tiktok.', 'amazon.', 'apple.', 'microsoft.', 'github.',
        'stackoverflow.', 'medium.', 'substack.', 'wordpress.com',
        'blogspot.', 'wix.com', 'cisa.gov', 'weforum.org'
    ]
    for pattern in excluded:
        if pattern in domain:
            return False
    suspicious = ['ads.', 'doubleclick.', 'analytics.', 'pixel.', 'wp-admin', 'login', 'signin', 'account']
    for pattern in suspicious:
        if pattern in domain:
            return False
    return True


class DDGSTimeout(Exception):
    """DDGS call timed out."""
    pass


def _ddgs_search_thread(query: str, max_results: int, region: str, result_container: dict) -> None:
    """Run DDGS search in thread, store results in container."""
    try:
        with DDGS() as ddgs:
            result_container['results'] = ddgs.text(query.strip(), max_results=max_results, region=region)
    except Exception as e:
        result_container['error'] = str(e)


def _ddgs_search_with_timeout(query: str, max_results: int, region: str) -> List[Dict[str, Any]]:
    """Run DDGS search with timeout using thread."""
    result_container = {'results': [], 'error': None}

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_ddgs_search_thread, query, max_results, region, result_container)
        try:
            future.result(timeout=DDGS_TIMEOUT)
        except FuturesTimeout:
            raise DDGSTimeout(f"DDGS timed out after {DDGS_TIMEOUT}s")

    if result_container.get('error'):
        raise Exception(result_container['error'])

    return result_container.get('results', [])


def _search_ddgs_single(query: str, num_results: int = 50, delay: int = 2) -> List[str]:
    """Search DuckDuckGo for a single query with timeout and rate limiting."""
    domains: Set[str] = set()
    try:
        logger.info(f"DDGS: Searching for '{query}'")
        time.sleep(delay)
        results = _ddgs_search_with_timeout(query, num_results, "wt-wt")
        for result in results:
            url = result.get('href', '')
            domain = extract_domain(url)
            if domain and is_corporate_domain(domain):
                domains.add(domain)
        logger.info(f"DDGS: Found {len(domains)} domains for '{query}'")
    except DDGSTimeout as e:
        logger.warning(f"DDGS timed out for '{query}': {e}")
    except Exception as e:
        logger.warning(f"DDGS search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_ddgs(queries: List[str], num_results_per_query: int = 25, delay: int = 2) -> List[str]:
    """Search DuckDuckGo for multiple queries."""
    all_domains: Set[str] = set()
    logger.info(f"DDGS: Starting search for {len(queries)} queries")
    for i, query in enumerate(queries):
        try:
            domains = _search_ddgs_single(query, num_results_per_query, delay)
            all_domains.update(domains)
            logger.info(f"DDGS: Progress {i+1}/{len(queries)} - {len(all_domains)} domains collected")
        except Exception as e:
            logger.warning(f"DDGS: Failed for query '{query}': {str(e)}")
    result = sorted(list(all_domains))
    logger.info(f"DDGS: Total domains found: {len(result)}")
    return result


def search_with_searxng(query: str, num_results: int = 50) -> List[str]:
    """Search using SearXNG instance."""
    import requests
    domains = []
    try:
        searxng_url = os.getenv("SEARXNG_URL", "http://localhost:8080")
        response = requests.get(
            f"{searxng_url}/search",
            params={"q": query, "format": "json", "engines": "duckduckgo,google"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            for result in data.get('results', [])[:num_results]:
                url = result.get('url', '')
                domain = extract_domain(url)
                if domain:
                    domains.append(domain)
    except Exception as e:
        logger.warning(f"SearXNG search failed: {str(e)}")
    return domains


def _search_searxng_single(query: str, num_results: int = 50, delay: int = 1) -> List[str]:
    """Search SearXNG for a single query."""
    domains: Set[str] = set()
    try:
        logger.info(f"SearXNG: Searching for '{query}'")
        time.sleep(delay)
        results = search_with_searxng(query, num_results)
        for domain in results:
            if is_corporate_domain(domain):
                domains.add(domain)
        logger.info(f"SearXNG: Found {len(domains)} domains for '{query}'")
    except Exception as e:
        logger.warning(f"SearXNG search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_searxng(queries: List[str], num_results_per_query: int = 25, delay: int = 1) -> List[str]:
    """Search SearXNG for multiple queries."""
    all_domains: Set[str] = set()
    logger.info(f"SearXNG: Starting search for {len(queries)} queries")
    for i, query in enumerate(queries):
        try:
            domains = _search_searxng_single(query, num_results_per_query, delay)
            all_domains.update(domains)
            logger.info(f"SearXNG: Progress {i+1}/{len(queries)} - {len(all_domains)} domains collected")
        except Exception as e:
            logger.warning(f"SearXNG: Failed for query '{query}': {str(e)}")
    result = sorted(list(all_domains))
    logger.info(f"SearXNG: Total domains found: {len(result)}")
    return result


def search_domains_dual(base_query: str, region: str = "", target_results: int = 100,
                        ddgs_results: int = 50, searxng_results: int = 50) -> Tuple[List[str], Dict[str, Any]]:
    """Main orchestrator: Run ddgs + SearXNG concurrently."""
    start_time = time.time()
    cache_key = f"{base_query}_{region}"
    cached = _get_cached_results(cache_key)
    if cached:
        return cached, {'source': 'cache', 'count': len(cached)}

    queries = generate_query_variations(base_query, region)
    logger.info(f"Starting dual search: {len(queries)} variations, target: {target_results}")

    ddgs_domains = search_domains_ddgs(queries, ddgs_results, settings.SEARCH_DDGS_DELAY)
    logger.info(f"DDGS search completed: {len(ddgs_domains)} domains")

    searxng_domains = search_domains_searxng(queries, searxng_results, settings.SEARCH_SEARXNG_DELAY)
    logger.info(f"SearXNG search completed: {len(searxng_domains)} domains")

    all_domains: Set[str] = set()
    all_domains.update(ddgs_domains)
    all_domains.update(searxng_domains)
    final_domains = sorted(list(all_domains))

    if len(final_domains) > target_results:
        final_domains = final_domains[:target_results]

    elapsed_time = time.time() - start_time
    _save_cached_results(cache_key, final_domains)

    metadata = {
        'source': 'ddgs + searxng',
        'ddgs_count': len(ddgs_domains),
        'searxng_count': len(searxng_domains),
        'total_count': len(final_domains),
        'elapsed_time': round(elapsed_time, 2),
        'queries_used': len(queries),
        'base_query': base_query,
        'region': region
    }

    logger.info(f"Dual search completed: {len(final_domains)} domains in {elapsed_time:.2f}s")
    return final_domains, metadata


def search_domains(keyword: str, num_results: int = 100, region: str = "") -> List[str]:
    """Convenience wrapper — main entry point for the pipeline."""
    if region is None:
        region = ""
    elif not isinstance(region, str):
        region = str(region)
    results_per_source = min(30, num_results // 3)
    domains, metadata = search_domains_dual(
        base_query=keyword,
        region=region,
        target_results=num_results,
        ddgs_results=results_per_source,
        searxng_results=results_per_source
    )
    logger.info(f"Search results: {metadata}")
    return domains