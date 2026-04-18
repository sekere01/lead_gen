"""CommonCrawl discovery module."""
import json
import logging
import requests
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
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
    
    try:
        response = requests.get(
            "https://index.commoncrawl.org/collinfo.json",
            timeout=10
        )
        if response.status_code == 200:
            indexes = response.json()
            if indexes and len(indexes) > 0:
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


def discover_commoncrawl(keyword: str, region: str = "", max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Discover domains via CommonCrawl CDX API.
    
    Args:
        keyword: Search keyword
        region: Target region (e.g., 'nigeria', 'china', or 'global')
        max_results: Maximum results to return
    
    Returns:
        List of domain dictionaries
    """
    results = []
    seen_domains = set()
    
    config = _load_config()
    
    # Skip if disabled in config
    if not config.get('enabled', False):
        logger.info("CommonCrawl disabled in config - skipping")
        return results
    
    max_results = config.get('max_results', max_results)
    fallback_max = config.get('fallback_max_results', 200)
    min_before_fallback = config.get('min_results_before_fallback', 50)
    
    # Use fast timeout - fail quick if API is slow
    timeout = 3
    
    # Get TLD(s) for region
    tlds = _get_tld_for_region(region, config)
    
# Get latest index
  try:
      index = _get_latest_index()
  except ValueError:
      logger.warning("CommonCrawl index fetch failed — skipping CommonCrawl discovery")
      return results
  base_url = f"https://index.commoncrawl.org/{index}"

  try:
        for tld in tlds:
            if len(results) >= max_results:
                break
            
            # Quick health check first
            if not results and tld != tlds[0]:
                logger.info("CommonCrawl skipping - no results from first query")
                break
            
            # Primary query: TLD bulk pull
            params = {
                'url': f'*.{tld}/',
                'output': 'json',
                'filter': 'statuscode:200',
                'limit': max_results,
                'matchType': 'domain',
            }
            
            logger.info(f"CommonCrawl primary query: *.{tld}/")
            
            try:
                response = requests.get(base_url, params=params, timeout=timeout)
                
                if response.status_code == 200:
                    lines = response.text.strip().split('\n')
                    
                    for line in lines:
                        if len(results) >= max_results:
                            break
                        
                        try:
                            data = json.loads(line)
                            url = data.get('url', '')
                            domain = _extract_domain(url)
                            
                            if domain and domain not in seen_domains:
                                seen_domains.add(domain)
                                results.append({
                                    'domain': domain,
                                    'source': 'commoncrawl',
                                    'score': 2  # Higher score for TLD-based results
                                })
                        except json.JSONDecodeError:
                            continue
                        
            except Exception as e:
                logger.warning(f"CommonCrawl primary query failed for .{tld}: {e}")
            
            # Fallback: keyword in URL path (if primary returned too few results)
            if len(results) < min_before_fallback and keyword:
                keyword_lower = keyword.lower().replace(' ', '')
                
                fallback_params = {
                    'url': f'*.{tld}/%{keyword_lower}%',
                    'output': 'json',
                    'filter': 'statuscode:200',
                    'limit': fallback_max,
                }
                
                logger.info(f"CommonCrawl fallback query: *.{tld}/%{keyword_lower}%")
                
                try:
                    response = requests.get(base_url, params=fallback_params, timeout=timeout)
                    
                    if response.status_code == 200:
                        lines = response.text.strip().split('\n')
                        
                        for line in lines:
                            if len(results) >= max_results * 1.5:
                                break
                            
                            try:
                                data = json.loads(line)
                                url = data.get('url', '')
                                domain = _extract_domain(url)
                                
                                if domain and domain not in seen_domains:
                                    seen_domains.add(domain)
                                    results.append({
                                        'domain': domain,
                                        'source': 'commoncrawl_fallback',
                                        'score': 1  # Lower score for fallback results
                                    })
                            except json.JSONDecodeError:
                                continue
                                
                except Exception as e:
                    logger.warning(f"CommonCrawl fallback query failed: {e}")
        
        logger.info(f"CommonCrawl found {len(results)} domains for '{keyword}' (region: {region})")
    
    except Exception as e:
        logger.warning(f"CommonCrawl failed for '{keyword}': {str(e)}")
    
    return results[:max_results]