"""
Dashboard Endpoints
Provides aggregated metrics and pipeline status for the dashboard.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db, Company, Contact, DiscoveryJob
from services.process_manager import process_manager

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class MetricWrite(BaseModel):
    service: str
    metric: str
    value: float


def _format_uptime(seconds: Optional[int]) -> str:
    """Format uptime in seconds to human readable string."""
    if not seconds:
        return '--'
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f'{h}h {m}m'
    return f'{m}m'


class CompanyCountByStatus(BaseModel):
    status: str
    count: int


class ContactCountByVerification(BaseModel):
    verification_status: Optional[str] = "unknown"
    count: int


class JobQueueItem(BaseModel):
    id: int
    keyword: str
    region: str
    status: str
    created_at: Optional[str] = None
    last_run: Optional[str] = None


class PipelineMetrics(BaseModel):
    companies_total: int
    companies_by_status: List[CompanyCountByStatus]
    contacts_total: int
    contacts_by_verification: List[ContactCountByVerification]
    verified_count: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int


class DashboardStats(BaseModel):
    metrics: PipelineMetrics
    job_queue: List[JobQueueItem]
    services: dict
    pipeline: dict


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """Get dashboard statistics."""
    # Company counts by status
    company_status_counts = db.query(
        Company.status,
        func.count(Company.id).label('count')
    ).group_by(Company.status).all()
    
    companies_by_status = [
        CompanyCountByStatus(status=status, count=count)
        for status, count in company_status_counts
    ]
    
    companies_total = sum(c.count for c in companies_by_status)
    
    # Contact counts by verification status
    contact_verification_counts = db.query(
        func.coalesce(Contact.verification_status, 'unknown').label('verification_status'),
        func.count(Contact.id).label('count')
    ).group_by(func.coalesce(Contact.verification_status, 'unknown')).all()
    
    contacts_by_verification = [
        ContactCountByVerification(verification_status=status, count=count)
        for status, count in contact_verification_counts
    ]
    
    contacts_total = sum(c.count for c in contacts_by_verification)
    verified_count = db.query(Contact).filter(Contact.is_verified == True).count()
    
    # Job counts
    pending_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').count()
    processing_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'processing').count()
    completed_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'completed').count()
    failed_jobs = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'failed').count()
    
    # Job queue (pending + processing)
    queue_jobs = db.query(DiscoveryJob).filter(
        DiscoveryJob.status.in_(['pending', 'processing'])
    ).order_by(DiscoveryJob.created_at.desc()).limit(20).all()
    
    job_queue = [
        JobQueueItem(
            id=job.id,
            keyword=job.keyword,
            region=job.region,
            status=job.status,
            created_at=job.created_at.isoformat() if job.created_at else None,
            last_run=job.last_run.isoformat() if job.last_run else None
        )
        for job in queue_jobs
    ]
    
# Service status
    services_status = process_manager.get_health_status()

    # Queue depths per pipeline stage
    discovery_queue = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'pending').count()
    browsing_queue = db.query(Company).filter(
        Company.status == 'discovered'
    ).count()
    enrichment_queue = db.query(Company).filter(Company.status == 'browsed').count()
    verification_queue = db.query(Contact).filter(Contact.verification_status == 'pending').count()

    # Processed counts per stage
    discovery_processed = db.query(DiscoveryJob).filter(DiscoveryJob.status == 'completed').count()
    browsing_processed = db.query(Company).filter(Company.status == 'browsed').count()
    enrichment_processed = db.query(Company).filter(Company.status == 'enriched').count()
    verification_processed = db.query(Contact).filter(Contact.is_verified == True).count()

    # Build service status lookup
    services_lookup = {s['name']: s for s in services_status.get('services', [])}

    # Build pipeline object matching frontend expectations
    pipeline = {
        'discovery': {
            'status': services_lookup.get('discovery', {}).get('status', 'stopped'),
            'queue': discovery_queue,
            'uptime': _format_uptime(services_lookup.get('discovery', {}).get('uptime')),
            'processed': discovery_processed,
        },
        'browsing': {
            'status': services_lookup.get('browsing', {}).get('status', 'stopped'),
            'queue': browsing_queue,
            'uptime': _format_uptime(services_lookup.get('browsing', {}).get('uptime')),
            'processed': browsing_processed,
        },
        'enrichment': {
            'status': services_lookup.get('enrichment', {}).get('status', 'stopped'),
            'queue': enrichment_queue,
            'uptime': _format_uptime(services_lookup.get('enrichment', {}).get('uptime')),
            'processed': enrichment_processed,
        },
        'verification': {
            'status': services_lookup.get('verification', {}).get('status', 'stopped'),
            'queue': verification_queue,
            'uptime': _format_uptime(services_lookup.get('verification', {}).get('uptime')),
            'processed': verification_processed,
        },
        'sources': {
            'ddgs': {'status': 'active'},
            'searxng': {'status': 'active'},
            'commoncrawl': {'status': 'active'},
            'theharvester': {'status': 'active'},
        }
    }

    metrics = PipelineMetrics(
        companies_total=companies_total,
        companies_by_status=companies_by_status,
        contacts_total=contacts_total,
        contacts_by_verification=contacts_by_verification,
        verified_count=verified_count,
        pending_jobs=pending_jobs + processing_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs
    )
    
    return DashboardStats(
        metrics=metrics,
        job_queue=job_queue,
        services=services_status,
        pipeline=pipeline
    )


@router.get("/metrics")
def get_dashboard_metrics(service: str = "discovery", window: str = "5m", db: Session = Depends(get_db)):
    """
    Get time-series metrics for a service.
    Returns metrics from the ServiceMetrics table filtered by service and time window.
    """
    from datetime import datetime, timezone, timedelta
    from shared_models import ServiceMetrics
    
    # Parse time window - use local timezone-aware datetime
    window_seconds = {"5m": 300, "1h": 3600, "24h": 86400}.get(window, 300)
    now = datetime.now()
    cutoff = now - timedelta(seconds=window_seconds)
    
    # Ensure cutoff is timezone-aware for SQLAlchemy comparison
    # Database timestamps are in local timezone (EDT/EST)
    if cutoff.tzinfo is None:
        from datetime import timezone
        local_tz = datetime.now().astimezone().tzinfo
        cutoff = cutoff.replace(tzinfo=local_tz)
    
    try:
        # Handle 'all' service - return data from ALL services
        if service == 'all':
            services_to_query = ['discovery', 'browsing', 'enrichment', 'verification']
        else:
            services_to_query = [service]
        
        # Query metrics with proper window filtering
        metrics = db.query(ServiceMetrics).filter(
            ServiceMetrics.service.in_(services_to_query),
            ServiceMetrics.recorded_at >= cutoff
        ).order_by(ServiceMetrics.recorded_at.asc()).limit(100).all()
        
        if not metrics:
            return {"data": []}
        
        # Group by timestamp and pivot metrics
        data_by_time = {}
        for m in metrics:
            # Handle both timezone-aware and naive timestamps
            ts = m.recorded_at.isoformat() if m.recorded_at.tzinfo else m.recorded_at.replace(tzinfo=timezone.utc).isoformat()
            if ts not in data_by_time:
                data_by_time[ts] = {"timestamp": ts}
            # For "all" view, prefix metric with service name to avoid conflicts
            if service == 'all':
                data_by_time[ts][f"{m.service}_{m.metric}"] = m.value
            else:
                data_by_time[ts][m.metric] = m.value
        
        data = list(data_by_time.values())
        
        # Sort by timestamp (oldest first, ascending) and limit
        data.sort(key=lambda x: x.get("timestamp", ""), reverse=False)
        data = data[:50]  # Limit to 50 data points for chart
        
        # Add formatted label to each data point
        import re
        for d in data:
            ts_str = d.get("timestamp", "")
            if ts_str:
                try:
                    # Extract just YYYY-MM-DDTHH:MM:SS from timestamp
                    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})', ts_str)
                    if match:
                        ts = datetime.fromisoformat(match.group(1))
                        hour = ts.hour % 12
                        hour = hour if hour else 12
                        ampm = 'AM' if ts.hour < 12 else 'PM'
                        if window == "24h":
                            d["label"] = f"{ts.strftime('%m/%d')} {hour:02d} {ampm}"
                        else:
                            d["label"] = f"{hour:02d}:{ts.minute:02d} {ampm}"
                except Exception as e:
                    pass
        
        return {"data": data}
    
    except Exception as e:
        # Graceful degradation - return empty on error
        return {"data": []}


@router.post("/metrics")
def write_metric(payload: MetricWrite, db: Session = Depends(get_db)):
    """Write a single metric to ServiceMetrics table."""
    from fastapi import HTTPException
    from shared_models import ServiceMetrics
    from datetime import datetime, timezone

    try:
        recorded_at = datetime.now(timezone.utc)
        record = ServiceMetrics(
            service=payload.service,
            metric=payload.metric,
            value=payload.value,
            recorded_at=recorded_at,
        )
        db.add(record)
        db.commit()
        return {
            "status": "ok",
            "recorded": {
                "service": payload.service,
                "metric": payload.metric,
                "value": payload.value,
                "recorded_at": recorded_at.isoformat(),
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/job/{job_id}/companies")
def get_job_companies(job_id: int, limit: int = 10, db: Session = Depends(get_db)):
    """Get top companies for a job (by discovery score)."""
    job = db.query(DiscoveryJob).filter(DiscoveryJob.id == job_id).first()
    if not job:
        return {'error': 'Job not found'}
    
    # Find companies that match this job's keyword pattern
    # For now, just get recent companies sorted by score
    companies = db.query(Company).order_by(
        Company.discovery_score.desc()
    ).limit(limit).all()
    
    return {
        'job_id': job_id,
        'keyword': job.keyword,
        'companies': [
            {
                'id': c.id,
                'domain': c.domain,
                'discovery_score': c.discovery_score,
                'status': c.status,
                'tier': 'strong' if c.discovery_score >= 8 else 'good' if c.discovery_score >= 5 else 'weak'
            }
            for c in companies
        ]
    }

# WebSocket real-time updates
from fastapi import WebSocket, WebSocketDisconnect
from typing import List
import json

class ConnectionManager:
    """Manage WebSocket connections for real-time dashboard updates."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()


@router.websocket("/ws")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    print(f"WebSocket connection request received")  # Debug log
    await manager.connect(websocket)
    try:
        # Send initial dashboard data
        db = next(get_db())
        initial_data = get_dashboard_stats(db)
        # Convert Pydantic model to dict for JSON serialization
        if hasattr(initial_data, 'model_dump'):
            initial_dict = initial_data.model_dump()
        else:
            initial_dict = dict(initial_data)
        await websocket.send_text(json.dumps({
            "type": "initial",
            "data": initial_dict
        }))
        
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            # Echo back for ping/pong
            await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


def broadcast_update(update_type: str, data: dict):
    """Broadcast an update to all connected WebSocket clients."""
    import asyncio
    message = {"type": update_type, "data": data}
    asyncio.create_task(manager.broadcast(message))
