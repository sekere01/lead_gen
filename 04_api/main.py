"""
Lead Generation Engine - REST API
FastAPI application for managing discovery jobs, companies, contacts, and verification.
Entry: python main.py
"""
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import logging.handlers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.v1.router import router as api_router
from database import init_db
from config import settings
from pathlib import Path

app = FastAPI(
    title="Lead Generation Engine API",
    description="REST API for managing lead discovery, enrichment, and verification",
    version="1.0.0"
)

BASE_DIR = Path(__file__).parent

LOG_DIR = os.getenv("LOG_DIR", "/home/fisazkido/lead_gen2/logs")
os.makedirs(LOG_DIR, exist_ok=True)

file_handler = logging.handlers.TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "api.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8"
)
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)s | api | %(message)s'
))

logging.getLogger("uvicorn.error").addHandler(file_handler)
logging.getLogger("uvicorn.access").addHandler(file_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "lead-gen-api"}


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Lead Generation Engine API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Dashboard UI."""
    template_path = BASE_DIR / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text())
    return HTMLResponse(content="<h1>Dashboard not found</h1>")


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 50)
    print("Starting Lead Generation API...")
    print("=" * 50)
    
    init_db()
    
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
