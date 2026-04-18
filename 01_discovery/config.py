"""
Configuration for Discovery Service.
Loads environment variables from .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL")  # REQUIRED - no default

    # Discovery settings
    DISCOVERY_POLL_INTERVAL: int = int(os.getenv("DISCOVERY_POLL_INTERVAL", "300"))
    MAX_JOB_RETRIES: int = int(os.getenv("MAX_JOB_RETRIES", "3"))
    SEARCH_CACHE_HOURS: int = int(os.getenv("SEARCH_CACHE_HOURS", "24"))
    SEARCH_DDGS_DELAY: int = int(os.getenv("SEARCH_DDGS_DELAY", "2"))
    SEARCH_SEARXNG_DELAY: int = int(os.getenv("SEARCH_SEARXNG_DELAY", "1"))


settings = Settings()
