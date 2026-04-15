"""
Search Orchestration Module for Lead Discovery.
Combines DuckDuckGo (ddgs) and SearXNG for comprehensive domain discovery.
"""
import os
import json
import time
import logging
from typing import List, Set, Optional, Dict, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime, timedelta

from ddgs import DDGS

logger = logging.getLogger(__name__)

SEARCH_CACHE_HOURS = int(os.getenv("SEARCH_CACHE_HOURS", "24"))
SEARCH_DDGS_DELAY = int(os.getenv("SEARCH_DDGS_DELAY", "2"))
SEARCH_SEARXNG_DELAY = int(os.getenv("SEARCH_SEARXNG_DELAY", "1"))

DIRECTORY_DOMAINS = [
    'techbehemoths.com', 'clutch.co', 'goodfirms.co', 'g2.com',
    'capterra.com', 'themanifest.com', 'goodtal.com', 'lusha.com',
    'crunchbase.com', 'linkedin.com', 'yelp.com', 'yellowpages.com',
    'wikipedia.org', 'reddit.com', 'quora.com',
]


def _get_cache_file_path() -> str:
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, 'search_cache.json')


def _load_cache() -> Dict[str, Any]:
    cache_file = _get_cache_file_path()
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    cache_file = _get_cache_file_path()
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _get_cached_results(query: str) -> Optional[List[str]]:
    cache = _load_cache()
    if query in cache:
        cached_time = cache[query].get('timestamp', '')
        try:
            cached_dt = datetime.fromisoformat(cached_time)
            if datetime.now() - cached_dt < timedelta(hours=SEARCH_CACHE_HOURS):
                return cache[query].get('domains', [])
        except Exception:
            pass
    return None


def _save_cached_results(query: str, domains: List[str]) -> None:
    cache = _load_cache()
    cache[query] = {'domains': domains, 'timestamp': datetime.now().isoformat(), 'count': len(domains)}
    _save_cache(cache)


def generate_query_variations(base_query: str, region: str = "") -> List[str]:
    if region is None:
        region = ""
    elif not isinstance(region, str):
        region = str(region)
    
    variations = []
    region_suffix = f" in {region}" if region and region.lower() != "global" else ""
    variations.append(base_query + region_suffix)
    
    if region:
        region_lower = region.lower()
        tld_map = {'turkey': 'com.tr', 'nigeria': 'com.ng', 'usa': 'com', 'uk': 'co.uk'}
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
    if not domain or not isinstance(domain, str):
        return False
    domain = domain.lower().strip()
    if len(domain) < 4:
        return False
    for d in DIRECTORY_DOMAINS:
        if d in domain:
            return False
    excluded = ['google.', 'youtube.', 'facebook.', 'twitter.', 'instagram.', 'linkedin.', 'wikipedia.', 'reddit.', 'amazon.', 'microsoft.', 'github.']
    for pattern in excluded:
        if pattern in domain:
            return False
    return True


def _search_ddgs_single(query: str, num_results: int = 50, delay: int = 2) -> List[str]:
    domains: Set[str] = set()
    try:
        time.sleep(delay)
        with DDGS() as ddgs:
            results = ddgs.text(query.strip(), max_results=num_results, region="wt-wt")
            for result in results:
                url = result.get('href', '')
                domain = extract_domain(url)
                if domain and is_corporate_domain(domain):
                    domains.add(domain)
    except Exception as e:
        logger.warning(f"DDGS search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_ddgs(queries: List[str], num_results_per_query: int = 25, delay: int = 2) -> List[str]:
    all_domains: Set[str] = set()
    for query in queries:
        try:
            domains = _search_ddgs_single(query, num_results_per_query, delay)
            all_domains.update(domains)
        except Exception:
            pass
    return sorted(list(all_domains))


def search_with_searxng(query: str, num_results: int = 50) -> List[str]:
    import requests
    domains = []
    try:
        searxng_url = os.getenv("SEARXNG_URL", "http://localhost:8080")
        response = requests.get(f"{searxng_url}/search", params={"q": query, "format": "json"}, timeout=10)
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
    domains: Set[str] = set()
    try:
        time.sleep(delay)
        results = search_with_searxng(query, num_results)
        for domain in results:
            if is_corporate_domain(domain):
                domains.add(domain)
    except Exception as e:
        logger.warning(f"SearXNG search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_searxng(queries: List[str], num_results_per_query: int = 25, delay: int = 1) -> List[str]:
    all_domains: Set[str] = set()
    for query in queries:
        try:
            domains = _search_searxng_single(query, num_results_per_query, delay)
            all_domains.update(domains)
        except Exception:
            pass
    return sorted(list(all_domains))


def search_domains_dual(base_query: str, region: str = "", target_results: int = 100,
                        ddgs_results: int = 50, searxng_results: int = 50) -> Tuple[List[str], Dict[str, Any]]:
    start_time = time.time()
    cache_key = f"{base_query}_{region}"
    cached = _get_cached_results(cache_key)
    if cached:
        return cached, {'source': 'cache', 'count': len(cached)}
    
    queries = generate_query_variations(base_query, region)
    
    ddgs_domains = search_domains_ddgs(queries, ddgs_results, SEARCH_DDGS_DELAY)
    searxng_domains = search_domains_searxng(queries, searxng_results, SEARCH_SEARXNG_DELAY)
    
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
    }
    
    return final_domains, metadata


def search_domains(keyword: str, num_results: int = 100, region: str = "") -> List[str]:
    if region is None:
        region = ""
    elif not isinstance(region, str):
        region = str(region)
    results_per_source = min(30, num_results // 3)
    domains, metadata = search_domains_dual(
        base_query=keyword, region=region, target_results=num_results,
        ddgs_results=results_per_source, searxng_results=results_per_source
    )
    return domains
