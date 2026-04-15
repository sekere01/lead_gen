"""Regional scoring module."""
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default fallback TLD scores (used if config file missing)
DEFAULT_TLD_SCORES = {
    '.cn': 3, '.in': 3, '.br': 3, '.mx': 3, '.ru': 3,
    '.de': 3, '.fr': 3, '.nl': 3, '.tr': 3, '.ng': 3,
    '.co.uk': 3, '.za': 3, '.au': 3, '.jp': 3, '.kr': 3,
    '.id': 3, '.pk': 3, '.bd': 3, '.es': 3, '.it': 3, '.ca': 3,
    '.com': 1, '.org': 1, '.net': 1, '.io': 1, '.co': 1,
}

# Default fallback city keywords (used if config file missing)
DEFAULT_CITY_KEYWORDS = {
    'china': ['beijing', 'shanghai', 'shenzhen', 'guangzhou', 'hangzhou'],
    'nigeria': ['lagos', 'abuja', 'ibadan', 'kano', 'enugu'],
    'india': ['mumbai', 'delhi', 'bangalore', 'hyderabad', 'chennai'],
    'germany': ['berlin', 'munich', 'hamburg', 'frankfurt'],
    'brazil': ['sao paulo', 'rio'],
    'turkey': ['istanbul', 'ankara', 'izmir'],
    'uk': ['london', 'manchester', 'birmingham'],
    'france': ['paris', 'marseille', 'lyon'],
    'usa': ['new york', 'los angeles', 'chicago', 'houston'],
    'australia': ['sydney', 'melbourne', 'brisbane'],
    'japan': ['tokyo', 'osaka', 'kyoto'],
}

# Module-level config (loaded at startup)
tld_scores: Dict[str, int] = {}
city_keywords: Dict[str, List[str]] = {}

# Config file modification tracking
_last_tld_mtime = 0
_last_city_mtime = 0


def _get_config_dir() -> Path:
    """Get the config directory path."""
    config_dir = Path(__file__).parent.parent / 'config'
    return config_dir


def _load_tld_scores() -> Dict[str, int]:
    """Load TLD scores from config file with fallback to defaults."""
    config_file = _get_config_dir() / 'tld_scores.yaml'
    
    if not config_file.exists():
        logger.warning(f"TLD config not found: {config_file}, using defaults")
        return DEFAULT_TLD_SCORES.copy()
    
    try:
        import yaml
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)
        
        if data and 'tlds' in data:
            logger.info(f"Loaded {len(data['tlds'])} TLDs from config")
            return data['tlds']
        else:
            logger.warning(f"Invalid TLD config format, using defaults")
            return DEFAULT_TLD_SCORES.copy()
    except Exception as e:
        logger.error(f"Error loading TLD config: {e}, using defaults")
        return DEFAULT_TLD_SCORES.copy()


def _load_city_keywords() -> Dict[str, List[str]]:
    """Load city keywords from config file with fallback to defaults."""
    config_file = _get_config_dir() / 'city_keywords.yaml'
    
    if not config_file.exists():
        logger.warning(f"City keywords config not found: {config_file}, using defaults")
        return DEFAULT_CITY_KEYWORDS.copy()
    
    try:
        import yaml
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)
        
        if data and 'regions' in data:
            logger.info(f"Loaded {len(data['regions'])} regions with city keywords from config")
            return data['regions']
        else:
            logger.warning(f"Invalid city keywords config format, using defaults")
            return DEFAULT_CITY_KEYWORDS.copy()
    except Exception as e:
        logger.error(f"Error loading city keywords config: {e}, using defaults")
        return DEFAULT_CITY_KEYWORDS.copy()


def load_config() -> tuple:
    """Load config from files. Returns (tld_scores, city_keywords)."""
    global tld_scores, city_keywords
    
    tld_scores = _load_tld_scores()
    city_keywords = _load_city_keywords()
    
    return tld_scores, city_keywords


def maybe_reload_config() -> bool:
    """
    Check if config files have changed and reload if needed.
    Returns True if config was reloaded, False otherwise.
    """
    global _last_tld_mtime, _last_city_mtime, tld_scores, city_keywords
    
    config_dir = _get_config_dir()
    tld_file = config_dir / 'tld_scores.yaml'
    city_file = config_dir / 'city_keywords.yaml'
    
    reloaded = False
    
    # Check TLD config
    if tld_file.exists():
        tld_mtime = tld_file.stat().st_mtime
        if tld_mtime > _last_tld_mtime:
            tld_scores = _load_tld_scores()
            _last_tld_mtime = tld_mtime
            reloaded = True
    
    # Check city keywords config
    if city_file.exists():
        city_mtime = city_file.stat().st_mtime
        if city_mtime > _last_city_mtime:
            city_keywords = _load_city_keywords()
            _last_city_mtime = city_mtime
            reloaded = True
    
    if reloaded:
        logger.info(f"Config reloaded: {len(tld_scores)} TLDs, {len(city_keywords)} regions")
    
    return reloaded


def get_config_summary() -> str:
    """Get a summary string of loaded config."""
    return f"{len(tld_scores)} TLDs, {len(city_keywords)} regions with city keywords"


def get_global_region_score(domain: str, region: str = "") -> int:
    """
    Calculate regional score for a domain.
    
    Args:
        domain: Domain to score
        region: Target region (e.g., "Nigeria", "Turkey", "Global")
    
    Returns:
        Score: TLD match (+3) + City/Keyword match (+2) + Global baseline (+1)
    """
    if not domain:
        return 0
    
    domain = domain.lower()
    score = 0
    
    # Check TLD match
    for tld, tld_score in tld_scores.items():
        if domain.endswith(tld):
            score += tld_score
            break
    
    # Check city/keyword in domain
    domain_parts = domain.replace('-', ' ').replace('.', ' ')
    
    # Check against all city keywords
    for region_name, cities in city_keywords.items():
        for city in cities:
            if city in domain_parts:
                score += 2
                break
        if score > 0 and score % 2 == 0:
            # Already added city score, break out
            break
    
    # Global mode: give +1 for generic TLDs
    if region and region.lower() == 'global':
        if '.com' in domain or '.org' in domain or '.net' in domain:
            score += 1
    
    return score


# Load config at module import time
load_config()