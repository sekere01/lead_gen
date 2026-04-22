"""
LLM Query Generator for Discovery Service.
Generates diverse search queries using Groq API.
Falls back to static queries if LLM fails.
"""
import json
import logging
from typing import List, Optional

from groq import Groq
from groq import RateLimitError, APIError

from config import settings
from .search_orchestration import generate_query_variations

logger = logging.getLogger(__name__)


def generate_search_queries(industry: str, location: str, count: int = 25) -> List[str]:
    """
    Generate diverse search queries for company discovery using Groq.
    Falls back to static queries if Groq call fails.

    Args:
        industry: The industry/keyword to search for (e.g., "cybersecurity")
        location: The location/region (e.g., "Nigeria", "USA", or "")
        count: Number of queries to generate (default 25)

    Returns:
        List of search query strings
    """
    api_key = getattr(settings, 'GROQ_API_KEY', None)

    if not api_key:
        logger.warning("GROQ_API_KEY not configured, using static fallback")
        return generate_query_variations(industry, location)[:count]

    try:
        client = Groq(api_key=api_key)
        model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')

        prompt = f"""You are a B2B lead generation expert helping an entrepreneur find business deals.
Generate {count} search engine queries to discover companies in {industry} {f"in {location}" if location else ""}
that are likely to need new vendors, partners, or services.

Include these query types:
- Direct company searches ("retail companies Lagos")
- Sales target signals ("retail stores expanding Nigeria")
- Marketing agencies and consultancies ("marketing agency Lagos")
- Decision maker signals ("sales director retail company Nigeria")
- Business directory style ("list of retail businesses Lagos")
- Association/membership ("Nigeria retail association members")
- B2B vendor/supplier opportunities ("retail supplier vendor Nigeria")
- Job posting signals ("retail company hiring sales manager Lagos")
- Regional city variations (use major cities in {location})
- Industry synonyms ("FMCG distributor", "consumer goods company", "wholesale dealer")
- Contact/outreach targeted ("contact us retail company Nigeria")
- Growth signals ("fastest growing retail companies Nigeria 2024")
- Deal-ready signals ("retail company looking for suppliers Nigeria")
- SME and startup focused ("small retail business Lagos", "startup consumer goods Nigeria")
- Trade and commerce ("import export retail Nigeria", "trade company Lagos")

Return ONLY a JSON array of strings. No explanation, no markdown, no preamble.
Example: ["query one", "query two", "query three"]"""

        logger.info(f"Generating {count} LLM queries for '{industry}' in '{location}'")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=1000
        )

        raw = response.choices[0].message.content.strip()
        logger.debug(f"Groq raw response: {raw[:200]}...")

        queries = json.loads(raw)
        result = queries[:count]

        logger.info(f"LLM generated {len(result)} queries successfully")
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Groq returned invalid JSON: {e}, raw: {raw[:500]}, using static fallback")
        return generate_query_variations(industry, location)[:count]

    except RateLimitError as e:
        logger.warning(f"Groq rate limited: {e}, using static fallback")
        return generate_query_variations(industry, location)[:count]

    except APIError as e:
        logger.warning(f"Groq API error: {e}, using static fallback")
        return generate_query_variations(industry, location)[:count]

    except Exception as e:
        logger.warning(f"Groq query generation failed: {e}, using static fallback")
        return generate_query_variations(industry, location)[:count]


def get_static_queries(industry: str, location: str) -> List[str]:
    """
    Fallback static query generator.
    Returns the existing generate_query_variations result.
    """
    return generate_query_variations(industry, location)


# Static TLD list organized by region
STATIC_TLDS = {
    "africa": [".ng", ".ke", ".gh", ".za", ".tz", ".ug", ".et", ".zw", ".zm", ".bw"],
    "middle_east": [".ae", ".sa", ".eg", ".qa", ".kw", ".om"],
    "europe": [".co.uk", ".de", ".fr", ".nl", ".es", ".it", ".pl"],
    "asia": [".in", ".sg", ".my", ".th", ".ph", ".vn", ".id"],
    "americas": [".com.br", ".com.mx", ".ca", ".com", ".org"],
    "oceania": [".com.au", ".co.nz"],
    "generic": [".com", ".co", ".biz", ".inc", ".ltd", ".group"]
}


def _get_static_tlds(location: str, count: int = 10) -> List[str]:
    """Get static TLDs based on location."""
    if not location:
        location = "global"

    location_lower = location.lower()

    # Map location to region
    region_map = {
        "nigeria": "africa",
        "kenya": "africa",
        "ghana": "africa",
        "south africa": "africa",
        "tanzania": "africa",
        "uganda": "africa",
        "ethiopia": "africa",
        "uae": "middle_east",
        "dubai": "middle_east",
        "saudi": "middle_east",
        "egypt": "middle_east",
        "uk": "europe",
        "germany": "europe",
        "france": "europe",
        "netherlands": "europe",
        "india": "asia",
        "singapore": "asia",
        "malaysia": "asia",
        "china": "asia",
        "japan": "asia",
        "thailand": "asia",
        "usa": "americas",
        "united states": "americas",
        "canada": "americas",
        "brazil": "americas",
        "mexico": "americas",
        "australia": "oceania",
        "new zealand": "oceania",
    }

    region = region_map.get(location_lower, "generic")

    tlds = []

    # Priority: region → neighboring regions → generic
    if region in STATIC_TLDS:
        tlds.extend(STATIC_TLDS[region])

    # Add neighboring regions for major countries
    if region == "africa":
        tlds.extend(STATIC_TLDS.get("middle_east", [])[:3])
        tlds.extend(STATIC_TLDS.get("generic", [])[:3])
    elif region == "americas":
        tlds.extend(STATIC_TLDS.get("generic", [])[:5])
    else:
        tlds.extend(STATIC_TLDS.get("generic", [])[:5])

    # Dedupe while preserving order
    seen = set()
    unique_tlds = []
    for tld in tlds:
        if tld not in seen:
            seen.add(tld)
            unique_tlds.append(tld)

    return unique_tlds[:count]


def generate_tld_list(location: str, industry: str = "", count: int = 10) -> List[str]:
    """
    Generate relevant TLDs for search targeting.
    Falls back to static TLDs if Groq call fails.

    Args:
        location: The location/region (e.g., "Nigeria", "Kenya")
        industry: The industry (e.g., "logistics")
        count: Number of TLDs to generate (default 10)

    Returns:
        List of TLD strings including the dot (e.g., [".com", ".ng", ".co.ke"])
    """
    api_key = getattr(settings, 'GROQ_API_KEY', None)

    if not api_key:
        logger.warning("GROQ_API_KEY not configured, using static TLD fallback")
        return _get_static_tlds(location, count)

    try:
        client = Groq(api_key=api_key)
        model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')

        prompt = f"""Generate {count} TLDs for {industry if industry else 'business'} in {location}. 

Return ONLY a JSON array of TLDs with dots. Example: [".com", ".ng", ".co.ke"]
No explanations. No comments."""

        logger.info(f"Generating {count} TLDs for '{location}' in '{industry}'")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=300
        )

        raw = response.choices[0].message.content.strip()
        logger.debug(f"Groq TLD raw response: {raw}")

        # Find JSON array bounds
        start = raw.find('[')
        end = raw.rfind(']') + 1
        if start >= 0 and end > 0:
            raw = raw[start:end]

        tlds = json.loads(raw)
        result = [tld.strip() if tld.startswith('.') else f'.{tld.strip()}'
                for tld in tlds if tld.strip()]

        logger.info(f"LLM generated {len(result)} TLDs successfully")
        return result[:count]

    except json.JSONDecodeError as e:
        logger.warning(f"Groq returned invalid TLD JSON: {e}, using static fallback")
        return _get_static_tlds(location, count)

    except Exception as e:
        logger.warning(f"Groq TLD generation failed: {e}, using static fallback")
        return _get_static_tlds(location, count)


# Fallback static keywords per industry
STATIC_KEYWORDS = {
    "logistics": ["freight", "haulage", "cargo", "courier", "warehousing", "shipping", "3pl", "transport"],
    "retail": ["store", "shop", "retail", "merchandise", "wholesale", "dealer", "e-commerce"],
    "cybersecurity": ["security", "infosec", "penetration-testing", "siem", "firewall", "encryption"],
    "healthcare": ["hospital", "clinic", "pharmacy", "medical", "health", "wellness"],
    "finance": ["banking", "investment", "insurance", "fintech", "accounting"],
    "default": ["services", "solutions", "consulting", "trading", "enterprise", "agency"]
}


def generate_commoncrawl_keywords(industry: str, location: str = "", count: int = 15) -> List[str]:
    """
    Generate URL path keywords for CommonCrawl pattern matching.
    Falls back to static keywords if Groq call fails.

    Args:
        industry: The industry to generate keywords for (e.g., "logistics")
        location: Ignored (CommonCrawl keywords don't use location)
        count: Number of keywords to generate (default 15)

    Returns:
        List of URL path keywords (single words or hyphenated, no spaces)
    """
    api_key = getattr(settings, 'GROQ_API_KEY', None)

    if not api_key:
        logger.warning("GROQ_API_KEY not configured, using static fallback")
        return _get_static_keywords(industry, count)

    try:
        client = Groq(api_key=api_key)
        model = getattr(settings, 'GROQ_MODEL', 'llama-3.1-8b-instant')

        prompt = f"""You are a B2B lead generation expert. Generate {count} URL path keywords to find {industry} company websites via web crawl pattern matching.

Rules:
- Single words or hyphenated terms only (no spaces, no phrases)
- These will be matched against URL paths like: */*keyword*
- Focus on industry jargon, business terms, and synonyms
- Do NOT include location names
- Do NOT include generic terms like "company" or "business"
- Do NOT include "contact", "about", "home", "services" — these are too generic

Examples for logistics: ["freight", "haulage", "cargo", "3pl", "warehousing", "shipping"]
Examples for retail: ["store", "shop", "merchandise", "wholesale", "e-commerce"]

Return ONLY a JSON array of strings. No explanation, no markdown, no preamble.
Example: ["freight", "haulage", "cargo"]"""

        logger.info(f"Generating {count} CommonCrawl keywords for '{industry}'")

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )

        raw = response.choices[0].message.content.strip()
        logger.debug(f"Groq CC raw response: {raw[:200]}...")

        keywords = json.loads(raw)
        result = [kw.strip().replace(' ', '-') for kw in keywords if kw.strip()]

        logger.info(f"LLM generated {len(result)} CommonCrawl keywords successfully")
        return result[:count]

    except json.JSONDecodeError as e:
        logger.warning(f"Groq returned invalid CC JSON: {e}, using static fallback")
        return _get_static_keywords(industry, count)

    except RateLimitError as e:
        logger.warning(f"Groq rate limited: {e}, using static fallback")
        return _get_static_keywords(industry, count)

    except APIError as e:
        logger.warning(f"Groq API error: {e}, using static fallback")
        return _get_static_keywords(industry, count)

    except Exception as e:
        logger.warning(f"Groq CC keyword generation failed: {e}, using static fallback")
        return _get_static_keywords(industry, count)


def _get_static_keywords(industry: str, count: int = 15) -> List[str]:
    """Get static fallback keywords for an industry."""
    industry_lower = industry.lower().strip() if industry else "default"

    # Exact match first
    if industry_lower in STATIC_KEYWORDS:
        keywords = STATIC_KEYWORDS[industry_lower]
    else:
        # Try partial match
        for key in STATIC_KEYWORDS:
            if key in industry_lower or industry_lower in key:
                keywords = STATIC_KEYWORDS[key]
                break
        else:
            keywords = STATIC_KEYWORDS["default"]

    return keywords[:count]
