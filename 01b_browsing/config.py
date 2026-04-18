"""
Configuration for Browsing Service.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")  # REQUIRED - no default
    
    # Polling
    BROWSING_POLL_INTERVAL: int = int(os.getenv("BROWSING_POLL_INTERVAL", "10"))
    
    # Timeouts
    BROWSING_TIMEOUT_HTTP: int = int(os.getenv("BROWSING_TIMEOUT_HTTP", "10"))
    BROWSING_TIMEOUT_PLAYWRIGHT: int = int(os.getenv("BROWSING_TIMEOUT_PLAYWRIGHT", "30"))
    BROWSING_TIMEOUT_DOMAIN: int = int(os.getenv("BROWSING_TIMEOUT_DOMAIN", "45"))
    
    # Concurrency
    BROWSING_CONCURRENCY_HTTP: int = int(os.getenv("BROWSING_CONCURRENCY_HTTP", "20"))
    BROWSING_CONCURRENCY_PLAYWRIGHT: int = int(os.getenv("BROWSING_CONCURRENCY_PLAYWRIGHT", "5"))
    
    # Retry/Watchdog
    BROWSING_WATCHDOG_MINUTES: int = int(os.getenv("BROWSING_WATCHDOG_MINUTES", "15"))
    BROWSING_MAX_RETRIES: int = int(os.getenv("BROWSING_MAX_RETRIES", "3"))
    
    # Scoring
    SCORE_MAX: int = int(os.getenv("SCORE_MAX", "10"))
    SCORE_THRESHOLD_WEAK: int = int(os.getenv("SCORE_THRESHOLD_WEAK", "2"))
    SCORE_THRESHOLD_GOOD: int = int(os.getenv("SCORE_THRESHOLD_GOOD", "5"))
    SCORE_THRESHOLD_STRONG: int = int(os.getenv("SCORE_THRESHOLD_STRONG", "8"))
    
    HEARTBEAT_INTERVAL: int = 10


settings = Settings()