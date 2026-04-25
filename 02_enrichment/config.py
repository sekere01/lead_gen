"""
Configuration for Enrichment Service.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")  # REQUIRED - no default
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "5"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "10"))
    ENRICHER_POLL_INTERVAL: int = int(os.getenv("ENRICHER_POLL_INTERVAL", "60"))
    MAX_CONCURRENT_CONTAINERS: int = int(os.getenv("MAX_CONCURRENT_CONTAINERS", "5"))
    ENRICHMENT_TIMEOUT_DOCKER: int = int(os.getenv("ENRICHMENT_TIMEOUT_DOCKER", "120"))
    
    # theHarvester API config
    HARVESTER_API_URL: str = os.getenv("HARVESTER_API_URL", "http://localhost:5000")
    HARVESTER_SOURCES: str = os.getenv("HARVESTER_SOURCES", "duckduckgo,bing")
    HARVESTER_LIMIT: int = int(os.getenv("HARVESTER_LIMIT", "500"))
    
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "/tmp/leadgen_harvester")
    
    # Enrichment reliability config
    ENRICHMENT_TIMEOUT_DOMAIN: int = int(os.getenv("ENRICHMENT_TIMEOUT_DOMAIN", "60"))
    ENRICHMENT_MAX_RETRIES: int = int(os.getenv("ENRICHMENT_MAX_RETRIES", "3"))
    ENRICHMENT_MAX_RETRIES_PHASE2: int = int(os.getenv("ENRICHMENT_MAX_RETRIES_PHASE2", "2"))
    ENRICHMENT_WATCHDOG_MINUTES: int = int(os.getenv("ENRICHMENT_WATCHDOG_MINUTES", "15"))
    TARGET_EMAILS_PER_DOMAIN: int = int(os.getenv("TARGET_EMAILS_PER_DOMAIN", "10"))
    HEARTBEAT_INTERVAL: int = 10
    CRAWLER_HTTP_TIMEOUT: int = 15


settings = Settings()
