"""
SDC Management API - Phase 6

FastAPI management plane for SDC (port 8004).
Provides health status, telemetry, and operational metrics for MGMT monitoring.

Endpoints:
- GET /health: Health check with operational status
- GET /status: Detailed SDC status (IO stats, mappings, connections)
- GET /metrics: Performance metrics (throughput, latency, error rates)
- GET /mappings: Active volume mappings with IO statistics
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mgmt"])


# Will be injected by service.py
_db_session_factory = None
_nbd_server = None  # Reference to NBD server for connection stats

def set_db_session_factory(factory):
    """Set database session factory (called by service.py)"""
    global _db_session_factory
    _db_session_factory = factory


def set_nbd_server(nbd_server):
    """Set NBD server reference for stats (called by service.py)"""
    global _nbd_server
    _nbd_server = nbd_server


def get_db():
    """Dependency for database sessions"""
    db = _db_session_factory()
    try:
        yield db
    finally:
        db.close()


class HealthResponse(BaseModel):
    """Health check response"""
    status: str  # 'healthy', 'degraded', 'unhealthy'
    component: str
    timestamp: datetime
    nbd_server_running: bool
    active_connections: int
    mapped_volumes: int


class StatusResponse(BaseModel):
    """Detailed SDC status"""
    sdc_id: Optional[int]
    nbd_server_port: int
    control_port: int
    mgmt_port: int
    mapped_volumes: int
    active_connections: int
    total_reads: int
    total_writes: int
    total_bytes_read: int
    total_bytes_written: int
    uptime_seconds: float


class MappingStat(BaseModel):
    """Volume mapping statistics"""
    volume_id: int
    volume_name: str
    size_bytes: int
    access_mode: str
    mapped_at: datetime
    last_io_at: Optional[datetime]
    io_count: int


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for MGMT monitoring.
    Returns operational status of SDC components.
    """
    from sdc.models import VolumeMappingCache
    
    # Check NBD server
    nbd_running = _nbd_server is not None and _nbd_server.running if _nbd_server else False
    active_conns = len(_nbd_server.active_connections) if _nbd_server and nbd_running else 0
    
    # Count mapped volumes
    mapped_count = db.query(VolumeMappingCache).count()
    
    # Determine health status
    if nbd_running and mapped_count > 0:
        status = "healthy"
    elif nbd_running:
        status = "healthy"  # Running but no volumes mapped yet
    else:
        status = "unhealthy"
    
    return HealthResponse(
        status=status,
        component="SDC",
        timestamp=datetime.utcnow(),
        nbd_server_running=nbd_running,
        active_connections=active_conns,
        mapped_volumes=mapped_count
    )


@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    """
    Get detailed SDC status with IO statistics.
    """
    from sdc.models import VolumeMappingCache, DeviceRegistry
    
    # Aggregate device stats
    devices = db.query(DeviceRegistry).all()
    
    total_reads = sum(d.total_reads for d in devices)  # type: ignore[attr-defined]
    total_writes = sum(d.total_writes for d in devices)  # type: ignore[attr-defined]
    total_bytes_read = sum(d.total_bytes_read for d in devices)  # type: ignore[attr-defined]
    total_bytes_written = sum(d.total_bytes_written for d in devices)  # type: ignore[attr-defined]
    
    mapped_count = db.query(VolumeMappingCache).count()
    active_conns = len(_nbd_server.active_connections) if _nbd_server and _nbd_server.running else 0
    
    # TODO: Track actual uptime from service start time
    uptime_seconds = 0.0
    
    return StatusResponse(
        sdc_id=None,  # TODO: Get from service.py
        nbd_server_port=8005,
        control_port=8003,
        mgmt_port=8004,
        mapped_volumes=mapped_count,
        active_connections=active_conns,
        total_reads=total_reads,
        total_writes=total_writes,
        total_bytes_read=total_bytes_read,
        total_bytes_written=total_bytes_written,
        uptime_seconds=uptime_seconds
    )


@router.get("/metrics")
def get_metrics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get performance metrics for MGMT dashboards.
    """
    from sdc.models import VolumeMappingCache, DeviceRegistry, PendingIO
    
    # IO statistics
    devices = db.query(DeviceRegistry).all()
    
    total_reads = sum(d.total_reads for d in devices)  # type: ignore[attr-defined]
    total_writes = sum(d.total_writes for d in devices)  # type: ignore[attr-defined]
    total_bytes_read = sum(d.total_bytes_read for d in devices)  # type: ignore[attr-defined]
    total_bytes_written = sum(d.total_bytes_written for d in devices)  # type: ignore[attr-defined]
    
    # Pending IOs (for monitoring IO queue depth)
    pending_io_count = db.query(PendingIO).filter(
        PendingIO.status.in_(["PENDING", "IN_PROGRESS"])  # type: ignore[attr-defined]
    ).count()
    
    # Connection stats
    active_conns = len(_nbd_server.active_connections) if _nbd_server and _nbd_server.running else 0
    
    return {
        "io_operations": {
            "total_reads": total_reads,
            "total_writes": total_writes,
            "pending_ios": pending_io_count
        },
        "throughput": {
            "total_bytes_read": total_bytes_read,
            "total_bytes_written": total_bytes_written,
            "avg_read_size": total_bytes_read / total_reads if total_reads > 0 else 0,
            "avg_write_size": total_bytes_written / total_writes if total_writes > 0 else 0
        },
        "connections": {
            "active": active_conns,
            "nbd_server_running": _nbd_server.running if _nbd_server else False
        },
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/mappings", response_model=List[MappingStat])
def get_mappings(db: Session = Depends(get_db)):
    """
    Get all mapped volumes with IO statistics.
    """
    from sdc.models import VolumeMappingCache
    
    mappings = db.query(VolumeMappingCache).all()
    
    result = []
    for mapping in mappings:
        result.append(MappingStat(
            volume_id=mapping.volume_id,  # type: ignore[attr-defined]
            volume_name=mapping.volume_name,  # type: ignore[attr-defined]
            size_bytes=mapping.size_bytes,  # type: ignore[attr-defined]
            access_mode=mapping.access_mode,  # type: ignore[attr-defined]
            mapped_at=mapping.mapped_at,  # type: ignore[attr-defined]
            last_io_at=mapping.last_io_at,  # type: ignore[attr-defined]
            io_count=mapping.io_count  # type: ignore[attr-defined]
        ))
    
    return result
