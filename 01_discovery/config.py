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
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "4"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "3"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "10"))

    # Discovery settings
    DISCOVERY_POLL_INTERVAL: int = int(os.getenv("DISCOVERY_POLL_INTERVAL", "300"))
    MAX_JOB_RETRIES: int = int(os.getenv("MAX_JOB_RETRIES", "3"))
    SEARCH_CACHE_HOURS: int = int(os.getenv("SEARCH_CACHE_HOURS", "24"))
    SEARCH_DDGS_DELAY: int = int(os.getenv("SEARCH_DDGS_DELAY", "2"))
    SEARCH_SEARXNG_DELAY: int = int(os.getenv("SEARCH_SEARXNG_DELAY", "1"))

    # Groq LLM settings
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_QUERY_COUNT: int = int(os.getenv("GROQ_QUERY_COUNT", "50"))
    DDGS_QUERY_COUNT: int = int(os.getenv("DDGS_QUERY_COUNT", "15"))
    COMMONCRAWL_KEYWORD_COUNT: int = int(os.getenv("COMMONCRAWL_KEYWORD_COUNT", "15"))
    TLD_COUNT: int = int(os.getenv("TLD_COUNT", "10"))


settings = Settings()
