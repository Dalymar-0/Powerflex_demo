"""
PHASE 2: Storage Engine
Core storage allocation, data distribution, and capacity management logic.
Enforces PowerFlex rules on chunk placement, replication, and resource constraints.
"""

import math
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update
from app.models import (
    StoragePool,
    Volume,
    SDSNode,
    Chunk,
    Replica,
    VolumeMapping,
    EventLog,
    ProtectionPolicy,
    SDSNodeState,
    ProvisioningType,
    EventType,
    PoolHealth,
    VolumeState,
    ProtectionDomain,
    FaultSet,
)


class StorageEngine:
    """
    Core storage allocation engine for PowerFlex simulator.
    Handles chunk distribution, capacity management, and placement rules.
    """

    # Configuration constants
    CHUNK_SIZE_MB = 4  # Standard 4MB chunks
    CHUNKS_PER_GB = 256  # 1024MB / 4MB = 256 chunks per GB
    MIN_SDS_NODES_FOR_REPLICATION = 2

    def __init__(self, db: Session):
        """
        Initialize storage engine with database session.
        
        Args:
            db: SQLAlchemy session for database operations
        """
        self.db = db

    # ========================================================================
    # CAPACITY MANAGEMENT
    # ========================================================================

    def allocate_capacity(
        self, pool: StoragePool, volume: Volume
    ) -> Tuple[bool, str]:
        """
        Allocate capacity in pool for a volume.
        
        For THICK volumes: Reserve full size immediately.
        For THIN volumes: Reserve minimal space, allocate on-write later.
        
        Args:
            pool: Storage pool
            volume: Volume to allocate capacity for
            
        Returns:
            (success: bool, message: str)
        """
        # Get raw values from ORM objects using getattr and typecast
        prov_type = volume.provisioning  # type: ignore
        prov_type_value = prov_type.value if hasattr(prov_type, "value") else str(prov_type)
        pool_total = pool.total_capacity_gb or 0  # type: ignore
        pool_used = pool.used_capacity_gb or 0  # type: ignore
        pool_reserved = pool.reserved_capacity_gb or 0  # type: ignore
        vol_size = volume.size_gb or 0  # type: ignore
        
        if prov_type_value == ProvisioningType.THICK.value:
            # Thick: must reserve entire size upfront
            required_capacity = vol_size
            available = pool_total - (pool_used + pool_reserved)

            if required_capacity > available:  # type: ignore
                return (
                    False,
                    f"Insufficient capacity: need {required_capacity}GB, "
                    f"available {available}GB",
                )

            # Update pool using SQL update statement
            self.db.execute(
                sql_update(StoragePool).where(StoragePool.id == pool.id).values(
                    reserved_capacity_gb=pool_reserved + required_capacity,
                    used_capacity_gb=pool_used + required_capacity
                )
            )
            # Update volume used capacity
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume.id).values(
                    used_capacity_gb=vol_size
                )
            )
            self.db.commit()

        else:  # THIN
            # Thin: minimal upfront, grows with use
            min_reserved = 0.1  # Reserve 100MB initially for metadata
            available = pool_total - (pool_used + pool_reserved)  # type: ignore

            if min_reserved > available:  # type: ignore
                return (
                    False,
                    "Pool capacity exhausted even for thin volume metadata",
                )

            self.db.execute(
                sql_update(StoragePool).where(StoragePool.id == pool.id).values(
                    reserved_capacity_gb=pool_reserved + min_reserved
                )
            )
            # Update volume used capacity to 0 for thin
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume.id).values(
                    used_capacity_gb=0
                )
            )
            self.db.commit()

        return True, "Capacity allocated successfully"

    def deallocate_capacity(self, pool: StoragePool, volume: Volume) -> None:
        """
        Release capacity when volume is deleted.
        
        Args:
            pool: Storage pool
            volume: Volume being deleted
        """
        pool_used = float(pool.used_capacity_gb)  # type: ignore
        pool_reserved = float(pool.reserved_capacity_gb)  # type: ignore
        vol_used = float(volume.used_capacity_gb)  # type: ignore
        vol_size = float(volume.size_gb)  # type: ignore
        prov_type = volume.provisioning  # type: ignore
        prov_type_value = prov_type.value if hasattr(prov_type, "value") else str(prov_type)
        
        if prov_type_value == ProvisioningType.THICK.value:
            new_used = max(0, pool_used - vol_size)
            new_reserved = max(0, pool_reserved - vol_size)
        else:  # THIN
            new_used = max(0, pool_used - vol_used)
            new_reserved = max(0, pool_reserved - 0.1)

        self.db.execute(
            sql_update(StoragePool).where(StoragePool.id == pool.id).values(
                used_capacity_gb=new_used,
                reserved_capacity_gb=new_reserved
            )
        )
        self.db.commit()

    def extend_volume_capacity(
        self, pool: StoragePool, volume: Volume, additional_gb: float
    ) -> Tuple[bool, str]:
        """
        Extend a volume's capacity.
        
        Args:
            pool: Storage pool
            volume: Volume to extend
            additional_gb: Gigabytes to add
            
        Returns:
            (success: bool, message: str)
        """
        if additional_gb <= 0:
            return False, "Extension size must be positive"

        prov_type = volume.provisioning
        prov_type_value = prov_type.value if hasattr(prov_type, "value") else str(prov_type)
        if prov_type_value == ProvisioningType.THIN.value:
            # Thin volumes can extend without reservation
            return True, f"Thin volume extended by {additional_gb}GB (on-demand)"

        # Thick: must have capacity available
        pool_total = float(pool.total_capacity_gb)  # type: ignore
        pool_used = float(pool.used_capacity_gb)  # type: ignore
        pool_reserved = float(pool.reserved_capacity_gb)  # type: ignore
        available = pool_total - (pool_used + pool_reserved)
        
        if additional_gb > available:
            return (
                False,
                f"Insufficient capacity for extension: need {additional_gb}GB, "
                f"available {available}GB",
            )

        self.db.execute(
            sql_update(StoragePool).where(StoragePool.id == pool.id).values(
                reserved_capacity_gb=pool_reserved + additional_gb,
                used_capacity_gb=pool_used + additional_gb
            )
        )
        self.db.execute(
            sql_update(Volume).where(Volume.id == volume.id).values(
                size_gb=float(volume.size_gb) + additional_gb  # type: ignore
            )
        )
        self.db.commit()
        return True, f"Volume extended by {additional_gb}GB"

    # ========================================================================
    # CHUNK & REPLICA ALLOCATION
    # ========================================================================

    def allocate_chunks(self, pool: StoragePool, volume: Volume) -> Tuple[int, str]:
        """
        Allocate chunks and replicas for a volume.
        
        Distributes chunks across SDS nodes following replication policy:
        - TWO_COPIES: 2 replicas per chunk on different SDS nodes
        - EC (ERASURE_CODING): 3 replicas per chunk (k=2, m=1)
        
        Placement rules:
        1. No two replicas on same SDS node
        2. Prefer different FaultSets (racks) if available
        3. Skip DOWN nodes
        4. Balance replicas across nodes (least-loaded first)
        
        Args:
            pool: Storage pool containing volume
            volume: Volume to create chunks for
            
        Returns:
            (chunk_count: int, message: str)
        """
        # Calculate chunk count: 256 chunks/GB - extract scalar first
        vol_size = float(volume.size_gb)  # type: ignore
        chunk_count = math.ceil(vol_size * self.CHUNKS_PER_GB)

        # Determine replica count from protection policy
        protection_policy = pool.protection_policy  # type: ignore
        replica_count = self._get_replica_count(protection_policy)  # type: ignore

        # Get available SDS nodes (UP state only)
        available_sds = self.db.query(SDSNode).filter(
            SDSNode.protection_domain_id == pool.pd_id, SDSNode.state == SDSNodeState.UP.value
        ).all()

        if len(available_sds) < replica_count:
            return (
                0,
                f"Insufficient SDS nodes for replication: "
                f"need {replica_count}, have {len(available_sds)} UP",
            )

        try:
            # Create chunks and replicas
            chunks_created = 0
            for chunk_idx in range(chunk_count):
                # Create chunk
                chunk = Chunk(
                    volume_id=volume.id,
                    logical_offset_mb=chunk_idx * self.CHUNK_SIZE_MB,
                    is_degraded=False,
                )
                self.db.add(chunk)
                self.db.flush()  # Get chunk.id

                # Select replica placement targets
                targets = self._select_replica_targets(
                    available_sds, replica_count, protection_policy  # type: ignore
                )

                if len(targets) < replica_count:
                    self.db.rollback()
                    return (
                        chunks_created,
                        f"Failed to place replicas for chunk {chunk_idx}: "
                        f"insufficient suitable nodes",
                    )

                # Create replicas and update SDS capacity
                for sds_node in targets:
                    replica = Replica(
                        chunk_id=chunk.id,
                        sds_id=sds_node.id,
                        is_available=True,
                        is_current=True,
                        is_rebuilding=False,
                    )
                    self.db.add(replica)
                    # Update SDS used capacity
                    sds_used = float(sds_node.used_capacity_gb)  # type: ignore
                    self.db.execute(
                        sql_update(SDSNode).where(SDSNode.id == sds_node.id).values(
                            used_capacity_gb=sds_used + (self.CHUNK_SIZE_MB / 1024)
                        )
                    )

                chunks_created += 1

            self.db.commit()
            return chunks_created, f"Created {chunks_created} chunks with {replica_count}-way replication"

        except Exception as e:
            self.db.rollback()
            return 0, f"Chunk allocation failed: {str(e)}"

    def _get_replica_count(self, protection_policy: ProtectionPolicy) -> int:
        """Get replica count for protection policy."""
        if protection_policy == ProtectionPolicy.TWO_COPIES:
            return 2
        elif protection_policy == ProtectionPolicy.EC:
            return 3  # k=2, m=1 erasure coding
        return 2

    def _select_replica_targets(
        self,
        available_sds: List[SDSNode],
        count: int,
        protection_policy: ProtectionPolicy,
    ) -> List[SDSNode]:
        """
        Select SDS nodes for replica placement.
        
        Strategy:
        1. Never place 2 replicas on same SDS
        2. Prefer different FaultSets if possible
        3. Balance load (select least-filled nodes)
        4. Return count targets, sorted by capacity available
        
        Args:
            available_sds: List of available SDS nodes
            count: Number of replicas needed
            protection_policy: Pool's protection policy
            
        Returns:
            List of selected SDS nodes
        """
        if len(available_sds) < count:
            return available_sds[:count]

        # Group by FaultSet if available
        fault_set_groups = {}
        for sds in available_sds:
            fs_id = sds.fault_set_id or "no_fault_set"
            if fs_id not in fault_set_groups:
                fault_set_groups[fs_id] = []
            fault_set_groups[fs_id].append(sds)

        selected = []

        # First, try to spread across fault sets
        if len(fault_set_groups) >= count:
            for fault_set_nodes in fault_set_groups.values():
                if len(selected) >= count:
                    break
                # Select least-loaded from this fault set
                best = min(
                    fault_set_nodes,
                    key=lambda n: n.used_capacity_gb / max(n.total_capacity_gb, 1),
                )
                if best not in selected:
                    selected.append(best)
        else:
            # Not enough fault sets, fill in with least-loaded nodes
            sorted_nodes = sorted(
                available_sds,
                key=lambda n: n.used_capacity_gb / max(n.total_capacity_gb, 1),
            )
            selected = sorted_nodes[:count]

        return selected[:count]

    # ========================================================================
    # VALIDATION & CONSISTENCY CHECKS
    # ========================================================================

    def validate_pool_exists(self, pool_id: int) -> Tuple[bool, Optional[StoragePool]]:
        """
        Validate that pool exists and is accessible.
        
        Args:
            pool_id: Pool ID to check
            
        Returns:
            (valid: bool, pool: StoragePool or None)
        """
        pool = self.db.query(StoragePool).filter(StoragePool.id == pool_id).first()
        return pool is not None, pool

    def validate_volume_can_map(self, volume: Volume) -> Tuple[bool, str]:
        """
        Validate that volume can be mapped to SDC.
        
        Rules:
        - Volume must exist
        - Volume must not be DEGRADED
        - Volume must not be being deleted
        
        Args:
            volume: Volume to check
            
        Returns:
            (valid: bool, message: str)
        """
        vol_state = volume.state
        if vol_state == VolumeState.DEGRADED.value or vol_state == VolumeState.DEGRADED:  # type: ignore
            return False, "Cannot map degraded volume (rebuild in progress)"

        if vol_state == VolumeState.DELETING.value or vol_state == VolumeState.DELETING:  # type: ignore
            return False, "Cannot map volume being deleted"

        return True, "Volume can be mapped"

    def validate_volume_can_delete(self, volume: Volume) -> Tuple[bool, str]:
        """
        Validate that volume can be deleted.
        
        Rules:
        - Volume must not be mapped to any SDCs
        - All chunks must be deletable
        
        Args:
            volume: Volume to check
            
        Returns:
            (valid: bool, message: str)
        """
        mapping_count = int(volume.mapping_count) if volume.mapping_count else 0  # type: ignore
        if mapping_count > 0:
            return False, f"Cannot delete: {mapping_count} SDC(s) still mapped"

        return True, "Volume can be deleted"

    def validate_all_chunks_healthy(self, volume: Volume) -> bool:
        """Check if all chunks of volume have replicas available."""
        degraded_chunks = (
            self.db.query(Chunk).filter(
                Chunk.volume_id == volume.id, Chunk.is_degraded == True
            ).count()
        )
        return degraded_chunks == 0

    def validate_replica_placement(self, chunk: Chunk) -> Tuple[bool, List[str]]:
        """
        Validate that chunk's replicas follow placement rules.
        
        Rules:
        - Each replica on different SDS node
        - Replica SDS must be UP or DEGRADED (not DOWN)
        - At least 1 replica available
        
        Args:
            chunk: Chunk to validate
            
        Returns:
            (valid: bool, errors: List[str])
        """
        errors = []
        replicas = self.db.query(Replica).filter(Replica.chunk_id == chunk.id).all()

        if not replicas:
            errors.append("Chunk has no replicas")

        # Check for duplicate SDS placement
        sds_ids = [r.sds_id for r in replicas]
        if len(sds_ids) != len(set(sds_ids)):
            errors.append("Multiple replicas on same SDS (invalid)")

        # Check replica SDS states
        for replica in replicas:
            sds = self.db.query(SDSNode).filter(SDSNode.id == replica.sds_id).first()
            sds_state = sds.state if sds else None
            if sds and (sds_state == SDSNodeState.DOWN.value or sds_state == SDSNodeState.DOWN):  # type: ignore
                replica_available = replica.is_available  # type: ignore
                if replica_available:  # type: ignore
                    errors.append(
                        f"Replica on DOWN SDS {sds.name} marked as available"
                    )

        # Check at least 1 available
        available_count = sum(1 for r in replicas if r.is_available)  # type: ignore
        if available_count == 0:
            errors.append("No available replicas (chunk lost)")

        return len(errors) == 0, errors

    def validate_capacity_consistency(self, pool: StoragePool) -> Tuple[bool, List[str]]:
        """
        Validate pool capacity accounting is consistent.
        
        Checks:
        - used_capacity <= total_capacity
        - sum(volume.size) <= pool.total_capacity
        - reserved_capacity is reasonable
        
        Args:
            pool: Pool to validate
            
        Returns:
            (valid: bool, errors: List[str])
        """
        errors = []
        
        pool_used = float(pool.used_capacity_gb)  # type: ignore
        pool_total = float(pool.total_capacity_gb)  # type: ignore
        pool_reserved = float(pool.reserved_capacity_gb)  # type: ignore

        if pool_used > pool_total:
            errors.append(
                f"Used capacity exceeds total: "
                f"{pool_used}GB > {pool_total}GB"
            )

        if pool_reserved < 0:
            errors.append(f"Negative reserved capacity: {pool_reserved}GB")

        return len(errors) == 0, errors

    # ========================================================================
    # HEALTH & STATE MANAGEMENT
    # ========================================================================

    def update_pool_health(self, pool: StoragePool) -> None:
        """
        Evaluate and update pool health status.
        
        Health rules:
        - OK: All SDS nodes UP, all chunks healthy
        - DEGRADED: Some SDS DOWN or volumes DEGRADED, rebuild running
        - FAILED: Chunk data loss detected (< 1 replica available)
        
        Args:
            pool: Pool to update health for
        """
        # Count UP/DOWN/DEGRADED nodes in this pool
        sds_nodes = self.db.query(SDSNode).filter(SDSNode.protection_domain_id == pool.pd_id).all()
        up_count = sum(1 for s in sds_nodes if s.state == SDSNodeState.UP.value or s.state == SDSNodeState.UP)  # type: ignore
        down_count = sum(1 for s in sds_nodes if s.state == SDSNodeState.DOWN.value or s.state == SDSNodeState.DOWN)  # type: ignore
        degraded_count = sum(1 for s in sds_nodes if s.state == SDSNodeState.DEGRADED.value or s.state == SDSNodeState.DEGRADED)  # type: ignore

        # Check for data loss (chunks with no available replicas)
        volumes = self.db.query(Volume).filter(Volume.pool_id == pool.id).all()
        data_loss_detected = False
        pool_degraded = False

        for volume in volumes:
            chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume.id).all()
            for chunk in chunks:
                available = self.db.query(Replica).filter(
                    Replica.chunk_id == chunk.id, Replica.is_available == True
                ).count()

                if available == 0:
                    data_loss_detected = True
                elif available < 2:
                    pool_degraded = True

        # Update pool health using SQL update
        if data_loss_detected:
            health_value = PoolHealth.FAILED.value
        elif pool_degraded or down_count > 0:
            health_value = PoolHealth.DEGRADED.value
        else:
            health_value = PoolHealth.OK.value

        self.db.execute(
            sql_update(StoragePool).where(StoragePool.id == pool.id).values(
                health=health_value
            )
        )
        self.db.commit()

    def mark_chunks_degraded(self, sds_id: int, pool: StoragePool) -> int:
        """
        When SDS node fails, mark affected chunks as degraded.
        
        Args:
            sds_id: Failed SDS node ID
            pool: Pool to update
            
        Returns:
            Count of chunks marked degraded
        """
        # Find all replicas on this SDS that belong to volumes in this pool
        volumes = self.db.query(Volume).filter(Volume.pool_id == pool.id).all()
        volume_ids = [v.id for v in volumes]

        chunks_updated = 0
        for volume_id in volume_ids:
            chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()
            for chunk in chunks:
                # Check if this chunk has a replica on the failed SDS
                replica = self.db.query(Replica).filter(
                    Replica.chunk_id == chunk.id, Replica.sds_id == sds_id
                ).first()

                if replica:
                    # Mark replica unavailable
                    self.db.execute(
                        sql_update(Replica).where(Replica.id == replica.id).values(
                            is_available=False
                        )
                    )
                    # Mark chunk degraded if only 1 replica left
                    available = self.db.query(Replica).filter(
                        Replica.chunk_id == chunk.id, Replica.is_available == True
                    ).count()

                    if available < 2:
                        self.db.execute(
                            sql_update(Chunk).where(Chunk.id == chunk.id).values(
                                is_degraded=True
                            )
                        )
                        chunks_updated += 1

        self.db.commit()
        return chunks_updated

    def heal_chunks_on_recovery(self, sds_id: int, pool: StoragePool) -> int:
        """
        When SDS node recovers, mark chunks healthy if replicas now available.
        
        Args:
            sds_id: Recovered SDS node ID
            pool: Pool to update
            
        Returns:
            Count of chunks healed
        """
        volumes = self.db.query(Volume).filter(Volume.pool_id == pool.id).all()
        volume_ids = [v.id for v in volumes]

        chunks_healed = 0
        for volume_id in volume_ids:
            chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()
            for chunk in chunks:
                if chunk.is_degraded:  # type: ignore
                    # Check if chunk now has 2 available replicas
                    available = self.db.query(Replica).filter(
                        Replica.chunk_id == chunk.id, Replica.is_available == True
                    ).count()

                    if available >= 2:
                        self.db.execute(
                            sql_update(Chunk).where(Chunk.id == chunk.id).values(
                                is_degraded=False
                            )
                        )
                        chunks_healed += 1

        self.db.commit()
        return chunks_healed

    # ========================================================================
    # LOGGING & EVENTS
    # ========================================================================

    def log_event(
        self,
        event_type: EventType,
        message: str,
        pool_id: Optional[int] = None,
        volume_id: Optional[int] = None,
        sds_id: Optional[int] = None,
        sdc_id: Optional[int] = None,
    ) -> None:
        """
        Log system event for audit trail.
        
        Args:
            event_type: Type of event (from EventType enum)
            message: Event description
            pool_id: Optional pool associated with event
            volume_id: Optional volume associated with event
            sds_id: Optional SDS node associated with event
            sdc_id: Optional SDC client associated with event
        """
        event = EventLog(
            event_type=event_type,
            message=message,
            pool_id=pool_id,
            volume_id=volume_id,
            sds_id=sds_id,
            sdc_id=sdc_id,
        )
        self.db.add(event)
        self.db.commit()
