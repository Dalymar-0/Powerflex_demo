"""
SDS Management Plane API (Phase 5)

HTTP/JSON API for MGMT→SDS monitoring.
Listens on SDS_MGMT_PORT (9200+n).

MGMT uses this API to:
- Query health status
- Get IO statistics
- List devices and replicas
- Retrieve error logs
"""

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
import logging

from sds.database import get_db
from sds.models import LocalReplica, LocalDevice, SDSMetadata, ConsumedToken, AckQueue

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="SDS Management Plane", version="1.0.0")
router = APIRouter(prefix="/mgmt", tags=["management"])


class HealthResponse(BaseModel):
    """SDS health status"""
    sds_id: int
    component_id: str
    status: str  # HEALTHY, DEGRADED, CRITICAL
    online_devices: int
    total_devices: int
    total_replicas: int
    active_replicas: int
    uptime_seconds: float
    last_heartbeat_sent: Optional[datetime] = None


class StatsResponse(BaseModel):
    """SDS IO statistics"""
    total_io_operations: int
    total_bytes_read: int
    total_bytes_written: int
    total_errors: int
    tokens_consumed: int
    pending_acks: int


class DeviceInfo(BaseModel):
    """Device information"""
    device_name: str
    device_path: str
    total_capacity_gb: float
    used_capacity_gb: float
    free_capacity_gb: float
    status: str
    error_count: int


class ReplicaInfo(BaseModel):
    """Replica information"""
    chunk_id: int
    volume_id: int
    size_bytes: int
    status: str
    generation: int
    last_write_at: Optional[datetime] = None


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)):
    """
    Get SDS health status.
    MGMT calls this periodically to monitor cluster health.
    """
    metadata = db.query(SDSMetadata).filter(SDSMetadata.id == 1).first()
    
    if not metadata:
        return HealthResponse(
            sds_id=0,
            component_id="unknown",
            status="CRITICAL",
            online_devices=0,
            total_devices=0,
            total_replicas=0,
            active_replicas=0,
            uptime_seconds=0.0
        )
    
    # Count devices
    total_devices = db.query(LocalDevice).count()
    online_devices = db.query(LocalDevice).filter(LocalDevice.status == "ONLINE").count()
    
    # Count replicas
    total_replicas = db.query(LocalReplica).count()
    active_replicas = db.query(LocalReplica).filter(LocalReplica.status == "ACTIVE").count()
    
    # Determine health status
    if online_devices == 0:
        status = "CRITICAL"
    elif online_devices < total_devices * 0.8:
        status = "DEGRADED"
    else:
        status = "HEALTHY"
    
    # Calculate uptime
    if metadata.initialized_at:
        uptime = (datetime.utcnow() - metadata.initialized_at).total_seconds()
    else:
        uptime = 0.0
    
    return HealthResponse(
        sds_id=metadata.sds_id or 0,
        component_id=metadata.component_id or "unknown",
        status=status,
        online_devices=online_devices,
        total_devices=total_devices,
        total_replicas=total_replicas,
        active_replicas=active_replicas,
        uptime_seconds=uptime,
        last_heartbeat_sent=metadata.last_heartbeat_sent_at
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    """
    Get IO statistics for this SDS node.
    Used by MGMT dashboard for performance monitoring.
    """
    metadata = db.query(SDSMetadata).filter(SDSMetadata.id == 1).first()
    
    if not metadata:
        return StatsResponse(
            total_io_operations=0,
            total_bytes_read=0,
            total_bytes_written=0,
            total_errors=0,
            tokens_consumed=0,
            pending_acks=0
        )
    
    # Count consumed tokens
    tokens_consumed = db.query(ConsumedToken).count()
    
    # Count pending ACKs
    pending_acks = db.query(AckQueue).filter(AckQueue.ack_status == "PENDING").count()
    
    return StatsResponse(
        total_io_operations=metadata.total_io_operations or 0,
        total_bytes_read=metadata.total_bytes_read or 0,
        total_bytes_written=metadata.total_bytes_written or 0,
        total_errors=metadata.total_errors or 0,
        tokens_consumed=tokens_consumed,
        pending_acks=pending_acks
    )


@router.get("/devices", response_model=List[DeviceInfo])
def list_devices(db: Session = Depends(get_db)):
    """
    List all devices attached to this SDS node.
    Used by MGMT for capacity planning and device health monitoring.
    """
    devices = db.query(LocalDevice).all()
    
    result = []
    for dev in devices:
        result.append(DeviceInfo(
            device_name=dev.device_name,
            device_path=dev.device_path,
            total_capacity_gb=dev.total_capacity_gb,
            used_capacity_gb=dev.used_capacity_gb,
            free_capacity_gb=dev.total_capacity_gb - dev.used_capacity_gb,
            status=dev.status,
            error_count=dev.error_count or 0
        ))
    
    return result


@router.get("/replicas", response_model=List[ReplicaInfo])
def list_replicas(db: Session = Depends(get_db)):
    """
    List all replicas stored on this SDS node.
    Used by MGMT for data placement visibility.
    """
    replicas = db.query(LocalReplica).all()
    
    result = []
    for rep in replicas:
        result.append(ReplicaInfo(
            chunk_id=rep.chunk_id,
            volume_id=rep.volume_id,
            size_bytes=rep.size_bytes,
            status=rep.status,
            generation=rep.generation,
            last_write_at=rep.last_write_at
        ))
    
    return result


@router.post("/shutdown")
def initiate_shutdown(db: Session = Depends(get_db)):
    """
    Initiate graceful shutdown of SDS service.
    MGMT can use this for maintenance operations.
    
    Note: Actual shutdown logic handled by service launcher.
    """
    logger.warning("Shutdown requested via management API")
    
    # TODO: Signal service launcher to stop
    # For now, just log
    
    return {"status": "shutdown_initiated", "message": "SDS will shut down gracefully"}


# Mount router
app.include_router(router)


@app.get("/")
def root():
    """Management plane root endpoint"""
    return {"service": "sds_mgmt", "status": "running"}
