"""
SDC Control API - Phase 6

FastAPI control plane for SDC (port 8003).
Handles volume mapping notifications from MDM and chunk location updates.

Endpoints:
- POST /control/volume_mapped: MDM notifies SDC of new volume mapping
- POST /control/volume_unmapped: MDM notifies SDC of volume unmapping
- POST /control/plan_update: MDM sends updated IO plan (chunk locations)
- GET /control/mappings: List all active volume mappings (for debugging)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/control", tags=["control"])


# Will be injected by service.py
_db_session_factory = None

def set_db_session_factory(factory):
    """Set database session factory (called by service.py)"""
    global _db_session_factory
    _db_session_factory = factory


def get_db():
    """Dependency for database sessions"""
    if _db_session_factory is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    db = _db_session_factory()
    try:
        yield db
    finally:
        db.close()


class VolumeMappedRequest(BaseModel):
    """MDM notification of volume mapping"""
    volume_id: int
    volume_name: str
    size_bytes: int
    access_mode: str  # 'readOnly', 'readWrite'


class VolumeUnmappedRequest(BaseModel):
    """MDM notification of volume unmapping"""
    volume_id: int


class PlanUpdateRequest(BaseModel):
    """MDM sends updated chunk locations"""
    volume_id: int
    chunk_id: int
    sds_address: str
    sds_data_port: int
    generation: int


class MappingInfo(BaseModel):
    """Volume mapping information"""
    volume_id: int
    volume_name: str
    size_bytes: int
    access_mode: str
    mapped_at: datetime
    io_count: int


@router.post("/volume_mapped")
def volume_mapped(request: VolumeMappedRequest, db: Session = Depends(get_db)):
    """
    Handle volume mapping notification from MDM.
    Cache volume info locally for NBD server validation.
    """
    from sdc.models import VolumeMappingCache
    
    # Check if already exists
    existing = db.query(VolumeMappingCache).filter(
        VolumeMappingCache.volume_id == request.volume_id
    ).first()
    
    if existing:
        # Update existing mapping
        existing.volume_name = request.volume_name  # type: ignore[assignment]
        existing.size_bytes = request.size_bytes  # type: ignore[assignment]
        existing.access_mode = request.access_mode  # type: ignore[assignment]
        db.commit()
        
        logger.info(f"Updated volume mapping: {request.volume_id} ({request.volume_name})")
        return {"status": "updated", "volume_id": request.volume_id}
    
    else:
        # Create new mapping
        mapping = VolumeMappingCache(
            volume_id=request.volume_id,
            volume_name=request.volume_name,
            size_bytes=request.size_bytes,
            access_mode=request.access_mode,
            mapped_at=datetime.utcnow(),
            io_count=0
        )
        
        db.add(mapping)
        db.commit()
        
        logger.info(f"Cached volume mapping: {request.volume_id} ({request.volume_name})")
        return {"status": "mapped", "volume_id": request.volume_id}


@router.post("/volume_unmapped")
def volume_unmapped(request: VolumeUnmappedRequest, db: Session = Depends(get_db)):
    """
    Handle volume unmapping notification from MDM.
    Remove from local cache.
    """
    from sdc.models import VolumeMappingCache, ChunkLocation
    
    # Remove mapping
    deleted_mappings = db.query(VolumeMappingCache).filter(
        VolumeMappingCache.volume_id == request.volume_id
    ).delete()
    
    # Clear chunk location cache for this volume
    deleted_chunks = db.query(ChunkLocation).filter(
        ChunkLocation.volume_id == request.volume_id
    ).delete()
    
    db.commit()
    
    if deleted_mappings > 0:
        logger.info(f"Removed volume mapping: {request.volume_id} (cleared {deleted_chunks} chunk cache entries)")
        return {"status": "unmapped", "volume_id": request.volume_id}
    else:
        logger.warning(f"Volume {request.volume_id} not found in cache")
        return {"status": "not_found", "volume_id": request.volume_id}


@router.post("/plan_update")
def plan_update(request: PlanUpdateRequest, db: Session = Depends(get_db)):
    """
    Handle chunk location update from MDM.
    Update local cache with new SDS location.
    """
    from sdc.models import ChunkLocation
    
    # Check if chunk location already cached
    existing = db.query(ChunkLocation).filter(
        ChunkLocation.volume_id == request.volume_id,
        ChunkLocation.chunk_id == request.chunk_id
    ).first()
    
    if existing:
        # Update existing entry
        existing.sds_address = request.sds_address  # type: ignore[assignment]
        existing.sds_data_port = request.sds_data_port  # type: ignore[assignment]
        existing.generation = request.generation  # type: ignore[assignment]
        existing.last_used_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()
        
        logger.debug(f"Updated chunk location: vol={request.volume_id} chunk={request.chunk_id} → {request.sds_address}:{request.sds_data_port}")
        return {"status": "updated"}
    
    else:
        # Create new entry
        location = ChunkLocation(
            volume_id=request.volume_id,
            chunk_id=request.chunk_id,
            sds_address=request.sds_address,
            sds_data_port=request.sds_data_port,
            generation=request.generation,
            cached_at=datetime.utcnow(),
            last_used_at=datetime.utcnow()
        )
        
        db.add(location)
        db.commit()
        
        logger.debug(f"Cached chunk location: vol={request.volume_id} chunk={request.chunk_id} → {request.sds_address}:{request.sds_data_port}")
        return {"status": "cached"}


@router.get("/mappings", response_model=List[MappingInfo])
def list_mappings(db: Session = Depends(get_db)):
    """List all active volume mappings (for debugging)"""
    from sdc.models import VolumeMappingCache
    
    mappings = db.query(VolumeMappingCache).all()
    
    result = []
    for mapping in mappings:
        result.append(MappingInfo(
            volume_id=mapping.volume_id,  # type: ignore[attr-defined]
            volume_name=mapping.volume_name,  # type: ignore[attr-defined]
            size_bytes=mapping.size_bytes,  # type: ignore[attr-defined]
            access_mode=mapping.access_mode,  # type: ignore[attr-defined]
            mapped_at=mapping.mapped_at,  # type: ignore[attr-defined]
            io_count=mapping.io_count  # type: ignore[attr-defined]
        ))
    
    return result
