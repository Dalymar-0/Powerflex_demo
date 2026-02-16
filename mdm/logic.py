"""
PHASE 6: Logic Layer Adapter
Integrates new service classes (PHASES 2-5) with existing API layer.
Provides backwards-compatible functions for API endpoints.
"""

from sqlalchemy.orm import Session
from sqlalchemy import select
from mdm.models import (
    SDSNode,
    StoragePool,
    Volume,
    SDSNodeState,
    ProvisioningType,
)
from mdm.services.storage_engine import StorageEngine
from mdm.services.volume_manager import VolumeManager
from mdm.services.rebuild_engine import RebuildEngine
from typing import List, Optional

# ============================================================================
# SERVICE INTEGRATION LAYER
# ============================================================================

def get_storage_engine(session: Session) -> StorageEngine:
    """Get storage engine instance."""
    return StorageEngine(session)


def get_volume_manager(session: Session) -> VolumeManager:
    """Get volume manager instance."""
    return VolumeManager(session)


def get_rebuild_engine(session: Session) -> RebuildEngine:
    """Get rebuild engine instance."""
    return RebuildEngine(session)


# ============================================================================
# CAPACITY & PLACEMENT LOGIC (delegated to StorageEngine)
# ============================================================================

def get_available_sds(pool: StoragePool, session: Session) -> List[SDSNode]:
    """Get list of available (UP) SDS nodes in pool's PD."""
    return session.scalars(select(SDSNode).where(
        SDSNode.protection_domain_id == pool.pd_id, SDSNode.state == SDSNodeState.UP
    )).all()


def allocate_chunks(volume: Volume, session: Session):
    """
    Allocate chunks and replicas for a volume.
    Delegates to StorageEngine.
    """
    pool = session.get(StoragePool, volume.pool_id)
    if not pool:
        raise Exception("Pool does not exist")

    engine = get_storage_engine(session)
    chunk_count, msg = engine.allocate_chunks(pool, volume)
    if chunk_count == 0:
        raise Exception(f"Chunk allocation failed: {msg}")


# ============================================================================
# VOLUME CREATION LOGIC (delegated to VolumeManager)
# ============================================================================

def create_volume(
    name: str, size_gb: float, provisioning: ProvisioningType, pool_id: int, session: Session
) -> Volume:
    """
    Create a new volume with capacity allocation and chunk placement.
    Delegates to VolumeManager.
    """
    mgr = get_volume_manager(session)
    prov_str = provisioning.value if isinstance(provisioning, ProvisioningType) else provisioning
    success, volume, msg = mgr.create_volume(pool_id, name, size_gb, prov_str)
    if not success:
        raise Exception(f"Volume creation failed: {msg}")
    return volume


# ============================================================================
# VOLUME MAPPING LOGIC (delegated to VolumeManager)
# ============================================================================

def map_volume(volume_id: int, sdc_id: int, access_mode: str, session: Session):
    """Map volume to SDC (grant access)."""
    mgr = get_volume_manager(session)
    success, msg = mgr.map_volume(volume_id, sdc_id, access_mode)
    if not success:
        raise Exception(f"Volume mapping failed: {msg}")


def unmap_volume(volume_id: int, sdc_id: int, session: Session):
    """Unmap volume from SDC (revoke access)."""
    mgr = get_volume_manager(session)
    success, msg = mgr.unmap_volume(volume_id, sdc_id)
    if not success:
        raise Exception(f"Volume unmapping failed: {msg}")


# ============================================================================
# VOLUME EXTENSION (delegated to VolumeManager)
# ============================================================================

def extend_volume(volume_id: int, new_size_gb: float, session: Session):
    """Extend an existing volume's capacity."""
    volume = session.get(Volume, volume_id)
    if not volume:
        raise Exception("Volume not found")

    if new_size_gb <= volume.size_gb:
        raise Exception("New size must be greater than current size")

    mgr = get_volume_manager(session)
    additional_gb = new_size_gb - volume.size_gb
    success, msg = mgr.extend_volume(volume_id, additional_gb)
    if not success:
        raise Exception(f"Volume extension failed: {msg}")


# ============================================================================
# VOLUME DELETION (delegated to VolumeManager)
# ============================================================================

def delete_volume(volume_id: int, session: Session):
    """Delete a volume and free its capacity."""
    mgr = get_volume_manager(session)
    success, msg = mgr.delete_volume(volume_id)
    if not success:
        raise Exception(f"Volume deletion failed: {msg}")


# ============================================================================
# NODE FAILURE HANDLING (delegated to RebuildEngine)
# ============================================================================

def fail_sds_node(sds_id: int, session: Session) -> str:
    """Simulate SDS node failure and trigger rebuild."""
    engine = get_rebuild_engine(session)
    success, msg = engine.fail_sds_node(sds_id)
    if not success:
        raise Exception(f"SDS failure handling failed: {msg}")
    return msg


def recover_sds_node(sds_id: int, session: Session) -> str:
    """Recover a failed SDS node."""
    engine = get_rebuild_engine(session)
    success, msg = engine.recover_sds_node(sds_id)
    if not success:
        raise Exception(f"SDS recovery failed: {msg}")
    return msg


# ============================================================================
# REBUILD OPERATIONS (delegated to RebuildEngine)
# ============================================================================

def start_rebuild(pool_id: int, session: Session) -> str:
    """Start rebuild operation for a pool."""
    engine = get_rebuild_engine(session)
    success, msg = engine.start_rebuild(pool_id)
    if not success:
        raise Exception(f"Rebuild start failed: {msg}")
    return msg


def get_rebuild_status(pool_id: int, session: Session) -> Optional[dict]:
    """Get current rebuild status for a pool."""
    engine = get_rebuild_engine(session)
    return engine.get_rebuild_status(pool_id)


# ============================================================================
# METRICS ACCESSORS (direct model-backed values)
# ============================================================================

def get_volume_metrics(volume_id: int, session: Session) -> dict:
    """Get current metrics for a volume."""
    volume = session.get(Volume, volume_id)
    if not volume:
        return {"error": "Volume not found"}
    return {
        "size_gb": volume.size_gb,
        "used_capacity_gb": volume.used_capacity_gb,
        "state": volume.state,
    }


def get_pool_metrics(pool_id: int, session: Session) -> dict:
    """Get aggregated metrics for a pool."""
    pool = session.get(StoragePool, pool_id)
    if not pool:
        return {"error": "Pool not found"}
    return {
        "total_capacity_gb": pool.total_capacity_gb,
        "used_capacity_gb": pool.used_capacity_gb,
        "free_capacity_gb": pool.total_capacity_gb - pool.used_capacity_gb,
        "health": pool.health,
    }


def get_sds_metrics(sds_id: int, session: Session) -> dict:
    """Get metrics for an SDS node."""
    sds = session.get(SDSNode, sds_id)
    if not sds:
        return {"error": "SDS not found"}
    return {
        "total_capacity_gb": sds.total_capacity_gb,
        "used_capacity_gb": sds.used_capacity_gb,
        "state": sds.state,
        "devices": sds.devices,
    }


def get_sdc_metrics(sdc_id: int, session: Session) -> dict:
    """Get metrics for an SDC client."""
    from mdm.models import SDCClient

    sdc = session.get(SDCClient, sdc_id)
    if not sdc:
        return {"error": "SDC not found"}
    return {
        "sdc_id": sdc.id,
        "name": sdc.name,
        "current_iops": sdc.current_iops,
        "current_bandwidth_mbps": sdc.current_bandwidth_mbps,
        "average_latency_ms": sdc.average_latency_ms,
    }
