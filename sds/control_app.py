"""
SDS Control Plane API (Phase 5)

HTTP/JSON API for MDM→SDS control commands.
Listens on SDS_CONTROL_PORT (9100+n).

MDM uses this API to:
- Assign chunks to this SDS node
- Issue replication commands (rebuild)
- Verify token status
- Update configuration
"""

from fastapi import APIRouter, Depends, HTTPException, FastAPI
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime
from pathlib import Path
import logging

from sds.database import get_db
from sds.models import LocalReplica, LocalDevice, SDSMetadata

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="SDS Control Plane", version="1.0.0")
router = APIRouter(prefix="/control", tags=["control"])


class AssignChunkRequest(BaseModel):
    """Request to assign a chunk to this SDS node"""
    chunk_id: int
    volume_id: int
    size_bytes: int
    device_name: Optional[str] = None  # Target device, or auto-select


class AssignChunkResponse(BaseModel):
    """Response after chunk assignment"""
    chunk_id: int
    local_file_path: str
    status: str


class ReplicateChunkRequest(BaseModel):
    """Request to replicate a chunk from another SDS"""
    chunk_id: int
    volume_id: int
    source_sds_address: str  # "10.0.1.10:9700"
    source_sds_id: int
    rebuild_token: str  # Special token issued by MDM for rebuild operations


class ReplicateChunkResponse(BaseModel):
    """Response after chunk replication"""
    chunk_id: int
    success: bool
    bytes_copied: int
    error_message: Optional[str] = None


class ChunkStatusResponse(BaseModel):
    """Chunk status on this SDS"""
    chunk_id: int
    volume_id: int
    status: str  # ACTIVE, DEGRADED, REBUILDING, MISSING
    size_bytes: int
    generation: int
    checksum: Optional[str] = None
    last_write_at: Optional[datetime] = None


@router.post("/assign", response_model=AssignChunkResponse)
def assign_chunk(request: AssignChunkRequest, db: Session = Depends(get_db)):
    """
    Assign a chunk to this SDS node.
    MDM calls this when creating a new volume or during rebalancing.
    """
    logger.info(f"Assign chunk request: chunk_id={request.chunk_id}, volume_id={request.volume_id}, size={request.size_bytes}")
    
    # Check if chunk already exists
    existing = db.query(LocalReplica).filter(
        LocalReplica.chunk_id == request.chunk_id
    ).first()
    
    if existing:
        return AssignChunkResponse(
            chunk_id=int(existing.chunk_id),  # type: ignore[arg-type]
            local_file_path=existing.local_file_path,  # type: ignore[arg-type]
            status="ALREADY_EXISTS"
        )
    
    # Get SDS metadata for storage root
    metadata = db.query(SDSMetadata).filter(SDSMetadata.id == 1).first()
    if not metadata:
        raise HTTPException(status_code=500, detail="SDS metadata not initialized")
    
    # Select device (auto-select if not specified)
    if request.device_name:
        device = db.query(LocalDevice).filter(
            LocalDevice.device_name == request.device_name,
            LocalDevice.status == "ONLINE"
        ).first()
        if not device:
            raise HTTPException(status_code=404, detail=f"Device {request.device_name} not found or offline")
    else:
        # Auto-select device with most free space
        device = db.query(LocalDevice).filter(
            LocalDevice.status == "ONLINE"
        ).order_by((LocalDevice.total_capacity_gb - LocalDevice.used_capacity_gb).desc()).first()
        
        if not device:
            raise HTTPException(status_code=503, detail="No online devices available")
    
    # Create local file path
    storage_root = Path(f"./vm_storage/sds_{metadata.sds_id}")
    storage_root.mkdir(parents=True, exist_ok=True)
    
    local_file_path = str(storage_root / f"vol_{request.volume_id}_chunk_{request.chunk_id}.img")
    
    # Create sparse file
    chunk_file = Path(local_file_path)
    with open(chunk_file, "wb") as f:
        f.truncate(request.size_bytes)
    
    # Create replica record
    replica = LocalReplica(
        chunk_id=request.chunk_id,
        volume_id=request.volume_id,
        local_file_path=local_file_path,
        size_bytes=request.size_bytes,
        status="ACTIVE",
        generation=0
    )
    
    db.add(replica)
    
    # Update device usage
    device.used_capacity_gb += request.size_bytes / (1024**3)
    
    db.commit()
    db.refresh(replica)
    
    logger.info(f"Chunk assigned: chunk_id={request.chunk_id}, path={local_file_path}")
    
    return AssignChunkResponse(
        chunk_id=replica.chunk_id,
        local_file_path=replica.local_file_path,
        status="ASSIGNED"
    )


@router.post("/replicate", response_model=ReplicateChunkResponse)
def replicate_chunk(request: ReplicateChunkRequest, db: Session = Depends(get_db)):
    """
    Replicate a chunk from another SDS node (rebuild operation).
    MDM issues this command during failure recovery.
    
    Note: Full implementation requires TCP client to source SDS.
    For Phase 5, we create the placeholder and return success.
    """
    logger.info(f"Replicate chunk request: chunk_id={request.chunk_id}, source={request.source_sds_address}")
    
    # Check if chunk already exists
    existing = db.query(LocalReplica).filter(
        LocalReplica.chunk_id == request.chunk_id
    ).first()
    
    if existing:
        return ReplicateChunkResponse(
            chunk_id=existing.chunk_id,
            success=True,
            bytes_copied=existing.size_bytes,
            error_message="Chunk already exists (no replication needed)"
        )
    
    # TODO Phase 5: Implement actual replication:
    # 1. Connect to source SDS data port
    # 2. Request full chunk read with rebuild_token
    # 3. Write received data to local storage
    # 4. Verify checksum
    # 5. Mark as ACTIVE
    
    # For now, return placeholder
    logger.warning(f"Chunk replication not yet implemented (Phase 5 TODO)")
    
    return ReplicateChunkResponse(
        chunk_id=request.chunk_id,
        success=False,
        bytes_copied=0,
        error_message="Replication not yet implemented (Phase 5)"
    )


@router.get("/chunk/{chunk_id}/status", response_model=ChunkStatusResponse)
def get_chunk_status(chunk_id: int, db: Session = Depends(get_db)):
    """
    Get chunk status on this SDS node.
    MDM uses this to verify chunk health.
    """
    replica = db.query(LocalReplica).filter(
        LocalReplica.chunk_id == chunk_id
    ).first()
    
    if not replica:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found on this SDS")
    
    return ChunkStatusResponse(
        chunk_id=replica.chunk_id,
        volume_id=replica.volume_id,
        status=replica.status,
        size_bytes=replica.size_bytes,
        generation=replica.generation,
        checksum=replica.checksum,
        last_write_at=replica.last_write_at
    )


@router.post("/device/add")
def add_device(device_name: str, device_path: str, capacity_gb: float, db: Session = Depends(get_db)):
    """
    Add a new device to this SDS node.
    Called during SDS initialization or when adding disks.
    """
    existing = db.query(LocalDevice).filter(
        LocalDevice.device_name == device_name
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail=f"Device {device_name} already exists")
    
    device = LocalDevice(
        device_name=device_name,
        device_path=device_path,
        total_capacity_gb=capacity_gb,
        used_capacity_gb=0.0,
        status="ONLINE"
    )
    
    db.add(device)
    db.commit()
    db.refresh(device)
    
    logger.info(f"Device added: {device_name}, capacity={capacity_gb}GB")
    
    return {
        "id": device.id,
        "device_name": device.device_name,
        "status": device.status
    }


# Mount router
app.include_router(router)


@app.get("/")
def root():
    """Control plane root endpoint"""
    return {"service": "sds_control", "status": "running"}
