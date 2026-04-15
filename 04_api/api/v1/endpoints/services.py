"""
Service Control Endpoints
Start, stop, restart, and check status of pipeline services.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

from database import get_db
from services.process_manager import process_manager

router = APIRouter(prefix="/services", tags=["Services"])


class ServiceResponse(BaseModel):
    name: str
    status: str
    uptime: Optional[int] = None
    pid: Optional[int] = None


class HealthResponse(BaseModel):
    health: str
    services_running: int
    services_total: int
    services: List[ServiceResponse]


class ServiceActionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


@router.get("/status", response_model=List[ServiceResponse])
def get_services_status():
    """Get status of all pipeline services."""
    services = process_manager.get_all_services_status()
    return [
        ServiceResponse(
            name=s.name,
            status=s.status,
            uptime=s.uptime,
            pid=s.pid
        )
        for s in services
    ]


@router.get("/health", response_model=HealthResponse)
def get_health():
    """Get overall pipeline health."""
    health = process_manager.get_health_status()
    return HealthResponse(**health)


@router.post("/{service_name}/start", response_model=ServiceActionResponse)
def start_service(service_name: str):
    """Start a pipeline service."""
    return process_manager.start_service(service_name)


@router.post("/{service_name}/stop", response_model=ServiceActionResponse)
def stop_service(service_name: str):
    """Stop a pipeline service."""
    return process_manager.stop_service(service_name)


@router.post("/{service_name}/restart", response_model=ServiceActionResponse)
def restart_service(service_name: str):
    """Restart a pipeline service."""
    return process_manager.restart_service(service_name)


@router.get("/logs")
def get_logs(limit: int = 50):
    """Get recent pipeline logs."""
    log_file = "/home/fisazkido/lead_gen2/pipeline.log"
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
        logs = [line.strip() for line in lines[-limit:]]
        return {"logs": logs, "count": len(logs)}
    except FileNotFoundError:
        return {"logs": [], "count": 0}


@router.post("/refresh")
def refresh_services():
    """Refresh service status cache."""
    process_manager.refresh_status()
    return {"success": True}