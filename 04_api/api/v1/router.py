"""
Router for API v1.
"""
from fastapi import APIRouter

from api.v1.endpoints import jobs, search, verification, companies, contacts, dashboard, services

router = APIRouter(prefix="/api/v1")

router.include_router(jobs.router)
router.include_router(search.router)
router.include_router(verification.router)
router.include_router(companies.router)
router.include_router(contacts.router)
router.include_router(dashboard.router)
router.include_router(services.router)
