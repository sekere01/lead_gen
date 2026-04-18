"""
Configuration for Verification Service.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL")  # REQUIRED - no default
    VERIFIER_POLL_INTERVAL: int = int(os.getenv("VERIFIER_POLL_INTERVAL", "30"))
    SMTP_TIMEOUT: int = int(os.getenv("SMTP_TIMEOUT", "5"))


settings = Settings()
