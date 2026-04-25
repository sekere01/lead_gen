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
    start_time: Optional[float] = None
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
            start_time=s.start_time,
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
def get_logs(limit: int = 100):
    """Get recent pipeline logs from all services."""
    import os
    all_logs = []
    
    service_names = ['discovery', 'browsing', 'enrichment', 'verification']
    for svc in service_names:
        log_file = f"/tmp/{svc}.out"
        try:
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    lines = f.readlines()
                    for line in lines[-limit:]:
                        all_logs.append(f"[{svc}] {line.strip()}")
        except Exception:
            pass
    
    # Try legacy log path from env, if exists
    legacy_log = os.getenv("LEGACY_LOG_PATH", "")
    if legacy_log and os.path.exists(legacy_log):
        with open(legacy_log, "r") as f:
            for line in f.readlines()[-limit:]:
                all_logs.append(f"[legacy] {line.strip()}")
    except Exception:
        pass
    
    # Return last 'limit' entries (newest first by reversing)
    all_logs = list(reversed(all_logs))[-limit:]
    all_logs = list(reversed(all_logs))
    
    return {"logs": all_logs, "count": len(all_logs)}


@router.get("/{service_name}/logs")
def get_service_logs(service_name: str, limit: int = 200):
    """Get logs for a specific service."""
    log_file = f"/tmp/{service_name}.out"
    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
        logs = [line.strip() for line in lines[-limit:]]
        return {"logs": logs, "count": len(logs), "service": service_name}
    except FileNotFoundError:
        return {"logs": [f"No logs yet for {service_name}"], "count": 0, "service": service_name}


@router.post("/refresh")
def refresh_services():
    """Refresh service status cache."""
    process_manager.refresh_status()
    return {"success": True}