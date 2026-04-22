"""
Search Orchestration Module for Lead Discovery.
Combines DuckDuckGo (ddgs) and SearXNG for comprehensive domain discovery.
"""
import os
import time
import random
import logging
from typing import List, Set, Optional, Dict, Any, Tuple, Callable
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from ddgs import DDGS

from config import settings

DDGS_TIMEOUT = 10

logger = logging.getLogger(__name__)


class RateLimiter:
    """Exponential backoff rate limiter for search providers."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, max_retries: int = 5):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self._delays: Dict[str, float] = {}

    def wait(self, provider: str) -> None:
        """Wait if provider was recently rate limited."""
        if provider in self._delays:
            delay = self._delays[provider]
            if delay > 0:
                logger.warning(f"Rate limiting {provider}: waiting {delay:.1f}s")
                time.sleep(delay)

    def record_success(self, provider: str) -> None:
        """Record successful request - reduce delay."""
        self._delays[provider] = max(0, self._delays.get(provider, 0) - self.base_delay)

    def record_rate_limit(self, provider: str) -> None:
        """Record rate limit hit - increase delay with exponential backoff + jitter."""
        current_delay = self._delays.get(provider, self.base_delay)
        new_delay = min(current_delay * 2 + random.uniform(0, 1), self.max_delay)
        self._delays[provider] = new_delay
        logger.warning(f"Rate limit recorded for {provider}: new delay {new_delay:.1f}s")

    def execute_with_backoff(self, provider: str, func: Callable, *args, **kwargs) -> Any:
        """Execute function with exponential backoff on rate limits."""
        for attempt in range(self.max_retries):
            self.wait(provider)
            try:
                result = func(*args, **kwargs)
                self.record_success(provider)
                return result
            except Exception as e:
                error_str = str(e).lower()
                is_rate_limited = (
                    '429' in error_str or
                    'rate limit' in error_str or
                    'too many requests' in error_str or
                    'timeout' in error_str or
                    'temporary failure' in error_str
                )
                if is_rate_limited and attempt < self.max_retries - 1:
                    self.record_rate_limit(provider)
                    logger.warning(f"{provider} rate limited (attempt {attempt + 1}/{self.max_retries}): {e}")
                else:
                    raise
        raise Exception(f"Max retries exceeded for {provider}")


rate_limiter = RateLimiter(base_delay=1.0, max_delay=60.0, max_retries=5)

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
    
    # Base variations
    variations.append(base_query + region_suffix)
    
    if region:
        region_lower = region.lower()
        tld_map = {
            'turkey': 'com.tr', 'nigeria': 'com.ng', 'usa': 'com',
            'united states': 'com', 'uk': 'co.uk', 'united kingdom': 'co.uk',
        }
        tld = tld_map.get(region_lower, 'com')
        variations.append(f"{base_query} site:.{tld}")
        variations.append(f"{base_query} {region}")
    
    # Additional business-type variations
    variations.append(f"{base_query} company")
    variations.append(f"{base_query} LLC")
    variations.append(f"{base_query} Inc")
    variations.append(f"{base_query} corp")
    variations.append(f"{base_query} group")
    variations.append(f"{base_query} solutions")
    variations.append(f"{base_query} services")
    
    # More variations for additional coverage
    variations.append(f"{base_query} provider")
    variations.append(f"{base_query} vendor")
    variations.append(f"{base_query} consultant")
    variations.append(f"{base_query} firm")
    variations.append(f"{base_query} expert")
    variations.append(f"{base_query} specialist")
    variations.append(f"{base_query} team")
    variations.append(f"{base_query} agency")
    variations.append(f"{base_query} managed services")
    variations.append(f"{base_query} consulting")
    variations.append(f"{base_query} support")
    variations.append(f"{base_query} compliance")
    variations.append(f"{base_query} audit")
    
    seen = set()
    unique_variations = []
    for v in variations:
        if v not in seen:
            seen.add(v)
            unique_variations.append(v)

    return unique_variations[:20]


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
        results = rate_limiter.execute_with_backoff("ddgs", _ddgs_search_with_timeout, query, num_results, "wt-wt")
        for result in results:
            url = result.get('href', '')
            domain = extract_domain(url)
            if domain and is_corporate_domain(domain):
                domains.add(domain)
        logger.info(f"DDGS: Found {len(domains)} domains for '{query}'")
    except DDGSTimeout as e:
        logger.warning(f"DDGS timed out for '{query}': {e}")
        rate_limiter.record_rate_limit("ddgs")
    except Exception as e:
        logger.warning(f"DDGS search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_ddgs(queries: List[str], num_results_per_query: int = 100, delay: int = 2) -> List[str]:
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


def search_with_searxng(query: str) -> List[str]:
    """Search using SearXNG instance with pagination and deduplication."""
    import requests
    domains: Set[str] = set()  # Dedupe across all pages
    searxng_url = os.getenv("SEARXNG_URL", "http://localhost:8080")

    max_pages = 10
    page_delays = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]  # 0s first page, 1s thereafter

    for page_num in range(1, max_pages + 1):
        if page_num > 1:
            delay = page_delays[page_num - 1]
            time.sleep(delay)

        try:
            response = requests.get(
                f"{searxng_url}/search",
                params={"q": query, "format": "json", "pageno": page_num},
                timeout=10
            )
            if response.status_code == 429:
                rate_limiter.record_rate_limit("searxng")
                raise Exception("SearXNG rate limited (429)")
            if response.status_code != 200:
                break

            data = response.json()
            results = data.get('results', [])
            page_count = len(results)
            logger.info(f"SearXNG page {page_num}: {page_count} results")

            if not results:
                break

            for result in results:
                url = result.get('url', '')
                domain = extract_domain(url)
                if domain and is_corporate_domain(domain):
                    domains.add(domain)  # Dedupe in-memory

        except Exception as e:
            logger.warning(f"SearXNG page {page_num} failed: {str(e)}")
            break

    return sorted(domains)


def _search_searxng_single(query: str, delay: int = 1) -> List[str]:
    """Search SearXNG for a single query with rate limiting."""
    domains: Set[str] = set()
    try:
        logger.info(f"SearXNG: Searching for '{query}'")
        time.sleep(delay)
        results = rate_limiter.execute_with_backoff("searxng", search_with_searxng, query)
        # Already filtered in search_with_searxng via is_corporate_domain
        domains.update(results)
        logger.info(f"SearXNG: Found {len(domains)} domains for '{query}'")
    except Exception as e:
        logger.warning(f"SearXNG search failed for '{query}': {str(e)}")
    return sorted(list(domains))


def search_domains_searxng(queries: List[str], delay: int = 1) -> List[str]:
    """Search SearXNG for multiple queries."""
    all_domains: Set[str] = set()
    logger.info(f"SearXNG: Starting search for {len(queries)} queries")
    for i, query in enumerate(queries):
        try:
            if i > 0:
                time.sleep(2)  # Space out queries to avoid burst detection
            domains = _search_searxng_single(query, delay)
            all_domains.update(domains)
            logger.info(f"SearXNG: Progress {i+1}/{len(queries)} - {len(all_domains)} domains collected")
        except Exception as e:
            logger.warning(f"SearXNG: Failed for query '{query}': {str(e)}")
    result = sorted(list(all_domains))
    logger.info(f"SearXNG: Total domains found: {len(result)}")
    return result


def search_domains_dual(base_query: str, region: str = "", target_results: int = 100,
                        ddgs_results: int = 100, searxng_results: int = 100) -> Tuple[List[str], Dict[str, Any]]:
    """Main orchestrator: Run ddgs + SearXNG + new sources concurrently."""
    start_time = time.time()
    cache_key = f"{base_query}_{region}"
    cached = _get_cached_results(cache_key)
    if cached:
        return cached, {'source': 'cache', 'count': len(cached)}

    # Generate search queries, CommonCrawl keywords, AND TLDs in parallel
    from concurrent.futures import ThreadPoolExecutor as LLMExecutor

    try:
        from .llm_query_generator import generate_search_queries, generate_commoncrawl_keywords, generate_tld_list

        searxng_query_count = getattr(settings, 'GROQ_QUERY_COUNT', 50)
        cc_keyword_count = getattr(settings, 'COMMONCRAWL_KEYWORD_COUNT', 15)
        tld_count = getattr(settings, 'TLD_COUNT', 10)

        with LLMExecutor(max_workers=3) as executor:
            search_future = executor.submit(generate_search_queries, base_query, region, searxng_query_count)
            cc_future = executor.submit(generate_commoncrawl_keywords, base_query, region, cc_keyword_count)
            tld_future = executor.submit(generate_tld_list, region, base_query, tld_count)

            queries = search_future.result()
            cc_keywords = cc_future.result()
            tlds = tld_future.result()
    except Exception as e:
        logger.warning(f"LLM query generation failed: {e}, using static fallback")
        queries = generate_query_variations(base_query, region)
        cc_keywords = [base_query.lower().replace(' ', '-')]
        tlds = []

    logger.info(f"Generated {len(queries)} search queries, {len(cc_keywords)} CC keywords, {len(tlds)} TLDs")

    # Expand queries with TLD targeting
    def expand_queries_with_tld(base_queries: List[str], tlds: List[str], max_total: int) -> List[str]:
        """Expand queries with site: operator for TLD targeting."""
        if not tlds:
            return base_queries[:max_total]

        half = max_total // 2
        base = list(base_queries[:half])
        expanded = list(base)

        priority_tlds = tlds[:half]
        for query in base_queries[:half]:
            for tld in priority_tlds:
                expanded.append(f"{query} site:{tld}")

        return expanded[:max_total]

    # DDGS: use subset with TLD expansion (capped)
    ddgs_query_count = getattr(settings, 'DDGS_QUERY_COUNT', 15)
    ddgs_queries = expand_queries_with_tld(queries, tlds, ddgs_query_count)

    # SearXNG: full list with TLD expansion (capped)
    searxng_query_count = getattr(settings, 'GROQ_QUERY_COUNT', 50)
    searxng_queries = expand_queries_with_tld(queries, tlds, searxng_query_count)

    logger.info(f"Starting search: {len(ddgs_queries)} DDGS queries, {len(searxng_queries)} SearXNG queries, target: {target_results}")

    # Run DDGS and SearXNG in parallel for faster execution
    ddgs_domains: List[str] = []
    searxng_domains: List[str] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        ddgs_future = executor.submit(
            search_domains_ddgs, ddgs_queries, ddgs_results, settings.SEARCH_DDGS_DELAY
        )
        searxng_future = executor.submit(
            search_domains_searxng, searxng_queries, settings.SEARCH_SEARXNG_DELAY
        )

        try:
            ddgs_domains = ddgs_future.result(timeout=300)
            logger.info(f"DDGS search completed: {len(ddgs_domains)} domains")
        except FuturesTimeout:
            logger.warning(f"DDGS parallel execution timed out after 5 minutes")
        except Exception as e:
            logger.warning(f"DDGS parallel execution failed: {e}")

        try:
            searxng_domains = searxng_future.result(timeout=600)
            logger.info(f"SearXNG search completed: {len(searxng_domains)} domains")
        except FuturesTimeout:
            logger.warning(f"SearXNG parallel execution timed out after 10 minutes")
        except Exception as e:
            logger.warning(f"SearXNG parallel execution failed: {e}")

    # Combine all sources
    all_domains: Set[str] = set()
    all_domains.update(ddgs_domains)
    all_domains.update(searxng_domains)
    
    # Try CommonCrawl if enabled with LLM-generated keywords
    try:
        from .commoncrawl import discover_commoncrawl
        cc_results = rate_limiter.execute_with_backoff("commoncrawl", discover_commoncrawl, base_query, region=region, max_results=500, keywords=cc_keywords)
        cc_domains = [r.get('domain', '') for r in cc_results if r.get('domain')]
        cc_domains = [d for d in cc_domains if is_corporate_domain(d)]
        all_domains.update(cc_domains)
        logger.info(f"CommonCrawl search completed: {len(cc_domains)} domains")
    except Exception as e:
        logger.warning(f"CommonCrawl search failed: {e}")
        cc_domains = []
    
    final_domains = sorted(list(all_domains))

    if target_results > 0 and len(final_domains) > target_results:
        final_domains = final_domains[:target_results]

    elapsed_time = time.time() - start_time
    _save_cached_results(cache_key, final_domains)

    metadata = {
        'source': 'ddgs + searxng + commoncrawl',
        'ddgs_count': len(ddgs_domains),
        'searxng_count': len(searxng_domains),
        'commoncrawl_count': len(cc_domains),
        'total_count': len(final_domains),
        'elapsed_time': round(elapsed_time, 2),
        'queries_used': len(queries),
        'base_query': base_query,
        'region': region
    }

    logger.info(f"Multi-source search completed: {len(final_domains)} domains in {elapsed_time:.2f}s")
    return final_domains, metadata


def search_domains(keyword: str, num_results: int = 100, region: str = "") -> List[str]:
    """Convenience wrapper — main entry point for the pipeline."""
    if region is None:
        region = ""
    elif not isinstance(region, str):
        region = str(region)
    # If num_results=0 (no cap), use max per source. Otherwise cap at num_results.
    results_per_source = 200 if num_results == 0 else min(200, num_results)
    domains, metadata = search_domains_dual(
        base_query=keyword,
        region=region,
        target_results=num_results,
        ddgs_results=results_per_source,
        searxng_results=results_per_source
    )
    logger.info(f"Search results: {metadata}")
    return domains