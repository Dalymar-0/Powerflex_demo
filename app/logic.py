"""
PHASE 6: Logic Layer Adapter
Integrates new service classes (PHASES 2-5) with existing API layer.
Provides backwards-compatible functions for API endpoints.
"""

from sqlalchemy.orm import Session
from app.models import (
    SDSNode,
    StoragePool,
    Volume,
    Chunk,
    Replica,
    SDCClient,
    VolumeMapping,
    ProtectionDomain,
    PoolHealth,
    SDSNodeState,
    VolumeState,
    ProvisioningType,
    ProtectionPolicy,
)
from app.database import SessionLocal
from app.services.storage_engine import StorageEngine
from app.services.volume_manager import VolumeManager
from app.services.rebuild_engine import RebuildEngine
from app.services.io_simulator import IOSimulator
from typing import List, Optional
import random

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


def get_io_simulator(session: Session) -> IOSimulator:
    """Get IO simulator instance."""
    return IOSimulator(session)


# ============================================================================
# CAPACITY & PLACEMENT LOGIC (delegated to StorageEngine)
# ============================================================================

def get_available_sds(pool: StoragePool, session: Session) -> List[SDSNode]:
    """Get list of available (UP) SDS nodes in pool's PD."""
    return session.query(SDSNode).filter(
        SDSNode.protection_domain_id == pool.pd_id, SDSNode.state == SDSNodeState.UP
    ).all()


def allocate_chunks(volume: Volume, session: Session):
    """
    Allocate chunks and replicas for a volume.
    Delegates to StorageEngine.
    """
    pool = session.query(StoragePool).get(volume.pool_id)
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
    volume = session.query(Volume).get(volume_id)
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
# METRICS & IO OPERATIONS (delegated to IOSimulator)
# ============================================================================

def get_volume_metrics(volume_id: int, session: Session) -> dict:
    """Get current metrics for a volume."""
    sim = get_io_simulator(session)
    return sim.aggregate_volume_metrics(volume_id)


def get_pool_metrics(pool_id: int, session: Session) -> dict:
    """Get aggregated metrics for a pool."""
    sim = get_io_simulator(session)
    return sim.aggregate_pool_metrics(pool_id)


def get_sds_metrics(sds_id: int, session: Session) -> dict:
    """Get metrics for an SDS node."""
    sim = get_io_simulator(session)
    return sim.aggregate_sds_metrics(sds_id)


def get_sdc_metrics(sdc_id: int, session: Session) -> dict:
    """Get metrics for an SDC client."""
    sim = get_io_simulator(session)
    return sim.aggregate_sdc_metrics(sdc_id)

    for chunk in chunks:
        replicas = session.query(Replica).filter_by(chunk_id=chunk.id).all()
        for replica in replicas:
            sds = session.query(SDSNode).get(replica.sds_id)
            sds.used_capacity_gb -= CHUNK_SIZE_GB
            session.delete(replica)
        session.delete(chunk)
    session.delete(volume)
    session.commit()
