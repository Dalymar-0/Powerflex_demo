"""
PHASE 3: Volume Operations
Complete CRUD lifecycle for volumes with state transitions and event logging.
Enforces volume access control and consistency.
"""

from typing import Tuple, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update
from app.models import (
    Volume,
    StoragePool,
    VolumeMapping,
    SDCClient,
    EventLog,
    ProvisioningType,
    VolumeState,
    AccessMode,
    EventType,
)
from app.services.storage_engine import StorageEngine


class VolumeManager:
    """
    Manages volume lifecycle: creation, mapping, extension, and deletion.
    """

    def __init__(self, db: Session):
        """
        Initialize volume manager.
        
        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self.engine = StorageEngine(db)

    # ========================================================================
    # VOLUME CREATION
    # ========================================================================

    def create_volume(
        self,
        pool_id: int,
        name: str,
        size_gb: float,
        provisioning: str,
    ) -> Tuple[bool, Optional[Volume], str]:
        """
        Create new volume in pool.
        
        Steps:
        1. Validate pool exists
        2. Validate volume name is unique
        3. Allocate capacity in pool
        4. Create volume record
        5. Allocate chunks and replicas
        6. Log event
        
        Args:
            pool_id: Pool to create volume in
            name: Volume name (must be unique)
            size_gb: Volume size in GB
            provisioning: "thin" or "thick"
            
        Returns:
            (success: bool, volume: Volume or None, message: str)
        """
        # Validate pool exists
        valid, pool = self.engine.validate_pool_exists(pool_id)
        if not valid:
            return False, None, f"Pool {pool_id} not found"

        # Validate volume name unique
        existing = self.db.query(Volume).filter(Volume.name == name).first()
        if existing:
            return False, None, f"Volume name '{name}' already exists"

        # Validate size
        if size_gb <= 0:
            return False, None, "Volume size must be positive"

        # Parse provisioning type
        try:
            prov_type = ProvisioningType[provisioning.upper()]
        except KeyError:
            return False, None, f"Invalid provisioning type: {provisioning}"

        try:
            # Create volume record
            volume = Volume(
                name=name,
                size_gb=size_gb,
                provisioning=prov_type,
                pool_id=pool_id,
                state=VolumeState.CREATING.value,
                mapping_count=0,
                used_capacity_gb=0,
            )
            self.db.add(volume)
            self.db.flush()  # Get volume.id

            # Allocate capacity
            success, capacity_msg = self.engine.allocate_capacity(pool, volume)
            if not success:
                self.db.rollback()
                return False, None, capacity_msg

            # Allocate chunks and replicas
            chunk_count, chunk_msg = self.engine.allocate_chunks(pool, volume)
            if chunk_count == 0:
                self.db.rollback()
                return False, None, f"Failed to allocate chunks: {chunk_msg}"

            # Mark volume available using SQL update
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume.id).values(
                    state=VolumeState.AVAILABLE.value
                )
            )

            # Get protection policy value for logging
            pool_policy = pool.protection_policy if pool else "UNKNOWN"  # type: ignore
            
            # Log event
            self.engine.log_event(
                EventType.VOLUME_CREATE,
                f"Created volume '{name}' ({size_gb}GB, {provisioning}): "
                f"{chunk_count} chunks, {pool_policy} policy",
                pool_id=pool.id,  # type: ignore
                volume_id=volume.id,  # type: ignore
            )

            self.db.commit()
            return True, volume, f"Volume created: {chunk_count} chunks allocated"

        except Exception as e:
            self.db.rollback()
            return False, None, f"Volume creation failed: {str(e)}"

    # ========================================================================
    # VOLUME MAPPING (ACCESS CONTROL)
    # ========================================================================

    def map_volume(
        self,
        volume_id: int,
        sdc_id: int,
        access_mode: str = "readWrite",
    ) -> Tuple[bool, str]:
        """
        Map volume to SDC client (grant access).
        
        Steps:
        1. Validate volume exists and can be mapped
        2. Validate SDC exists
        3. Check if already mapped
        4. Create VolumeMapping record
        5. Update volume state if first mapping
        6. Log event
        
        Args:
            volume_id: Volume to map
            sdc_id: SDC client to map to
            access_mode: "readWrite" or "readOnly"
            
        Returns:
            (success: bool, message: str)
        """
        # Validate volume exists
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, f"Volume {volume_id} not found"

        # Validate volume can be mapped
        valid, msg = self.engine.validate_volume_can_map(volume)
        if not valid:
            return False, msg

        # Validate SDC exists
        sdc = self.db.query(SDCClient).filter(SDCClient.id == sdc_id).first()
        if not sdc:
            return False, f"SDC {sdc_id} not found"

        # Parse access mode (accept enum name and enum value forms)
        mode = None
        access_mode_normalized = access_mode.replace("-", "_").replace(" ", "")
        for candidate in AccessMode:
            if (
                candidate.value.lower() == access_mode.lower()
                or candidate.name.lower() == access_mode_normalized.lower()
            ):
                mode = candidate
                break
        if mode is None:
            return False, f"Invalid access mode: {access_mode}"

        try:
            # Check if already mapped
            existing = (
                self.db.query(VolumeMapping)
                .filter(
                    VolumeMapping.volume_id == volume_id,
                    VolumeMapping.sdc_id == sdc_id,
                )
                .first()
            )
            if existing:
                return False, f"Volume already mapped to SDC {sdc.name}"

            # Create mapping
            mapping = VolumeMapping(
                volume_id=volume_id,
                sdc_id=sdc_id,
                access_mode=mode.value,
            )
            self.db.add(mapping)

            # Update volume state using SQL update
            current_mapping_count = int(volume.mapping_count) if volume.mapping_count else 0  # type: ignore
            new_mapping_count = current_mapping_count + 1
            vol_state = VolumeState.IN_USE.value if new_mapping_count == 1 else volume.state
            
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume_id).values(
                    mapping_count=new_mapping_count,
                    state=vol_state
                )
            )

            # Validate and update pool health
            pool = self.db.query(StoragePool).filter(
                StoragePool.id == volume.pool_id
            ).first()
            self.engine.update_pool_health(pool)

            # Log event
            self.engine.log_event(
                EventType.VOLUME_MAP,
                f"Mapped volume '{volume.name}' to SDC '{sdc.name}' ({mode.value})",
                pool_id=volume.pool_id,  # type: ignore
                volume_id=volume_id,
                sdc_id=sdc_id,
            )

            self.db.commit()
            return True, f"Volume mapped to {sdc.name}"

        except Exception as e:
            self.db.rollback()
            return False, f"Volume mapping failed: {str(e)}"

    def unmap_volume(self, volume_id: int, sdc_id: int) -> Tuple[bool, str]:
        """
        Unmap volume from SDC client (revoke access).
        
        Steps:
        1. Validate mapping exists
        2. Delete VolumeMapping record
        3. Decrement mapping count
        4. Update volume state if no mappings left
        5. Log event
        
        Args:
            volume_id: Volume to unmap
            sdc_id: SDC to unmap from
            
        Returns:
            (success: bool, message: str)
        """
        # Validate volume exists
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, f"Volume {volume_id} not found"

        # Validate SDC exists
        sdc = self.db.query(SDCClient).filter(SDCClient.id == sdc_id).first()
        if not sdc:
            return False, f"SDC {sdc_id} not found"

        try:
            # Find and delete mapping
            mapping = (
                self.db.query(VolumeMapping)
                .filter(
                    VolumeMapping.volume_id == volume_id,
                    VolumeMapping.sdc_id == sdc_id,
                )
                .first()
            )

            if not mapping:
                return False, f"Volume not mapped to SDC {sdc.name}"

            self.db.delete(mapping)

            # Update volume state using SQL update
            current_mapping_count = int(volume.mapping_count) if volume.mapping_count else 0  # type: ignore
            new_mapping_count = max(0, current_mapping_count - 1)
            vol_state = VolumeState.AVAILABLE.value if new_mapping_count == 0 else volume.state
            
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume_id).values(
                    mapping_count=new_mapping_count,
                    state=vol_state
                )
            )

            # Log event
            self.engine.log_event(
                EventType.VOLUME_UNMAP,
                f"Unmapped volume '{volume.name}' from SDC '{sdc.name}'",
                pool_id=volume.pool_id,  # type: ignore
                volume_id=volume_id,
                sdc_id=sdc_id,
            )

            self.db.commit()
            return True, f"Volume unmapped from {sdc.name}"

        except Exception as e:
            self.db.rollback()
            return False, f"Volume unmapping failed: {str(e)}"

    # ========================================================================
    # VOLUME EXTENSION
    # ========================================================================

    def extend_volume(self, volume_id: int, additional_gb: float) -> Tuple[bool, str]:
        """
        Extend volume size.
        
        Steps:
        1. Validate volume exists
        2. Validate size is positive
        3. Extend capacity in pool
        4. Allocate additional chunks
        5. Log event
        
        Args:
            volume_id: Volume to extend
            additional_gb: Size to add
            
        Returns:
            (success: bool, message: str)
        """
        # Validate volume exists
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, f"Volume {volume_id} not found"

        # Validate size
        if additional_gb <= 0:
            return False, "Extension size must be positive"

        try:
            # Get pool
            pool = self.db.query(StoragePool).filter(
                StoragePool.id == volume.pool_id
            ).first()

            # Extend capacity
            success, msg = self.engine.extend_volume_capacity(pool, volume, additional_gb)
            if not success:
                return False, msg

            # Allocate additional chunks
            chunk_count, chunk_msg = self.engine.allocate_chunks(pool, volume)

            # Log event
            self.engine.log_event(
                EventType.VOLUME_EXTEND,
                f"Extended volume '{volume.name}' by {additional_gb}GB "
                f"({chunk_count} additional chunks)",
                pool_id=pool.id,  # type: ignore
                volume_id=volume_id,
            )

            self.db.commit()
            return True, f"Volume extended by {additional_gb}GB"

        except Exception as e:
            self.db.rollback()
            return False, f"Volume extension failed: {str(e)}"

    # ========================================================================
    # VOLUME DELETION
    # ========================================================================

    def delete_volume(self, volume_id: int) -> Tuple[bool, str]:
        """
        Delete volume and free capacity.
        
        Steps:
        1. Validate volume exists
        2. Validate volume can be deleted (not mapped)
        3. Set state to DELETING
        4. Delete all chunks and replicas
        5. Deallocate capacity from pool
        6. Delete volume record
        7. Log event
        
        Args:
            volume_id: Volume to delete
            
        Returns:
            (success: bool, message: str)
        """
        # Validate volume exists
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, f"Volume {volume_id} not found"

        # Validate volume can be deleted
        valid, msg = self.engine.validate_volume_can_delete(volume)
        if not valid:
            return False, msg

        try:
            # Update state using SQL update
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume_id).values(
                    state=VolumeState.DELETING.value
                )
            )

            # Get pool for capacity deallocation
            pool = self.db.query(StoragePool).filter(
                StoragePool.id == volume.pool_id
            ).first()

            # Delete chunks and replicas (cascade)
            from app.models import Chunk, Replica
            chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()
            for chunk in chunks:
                self.db.query(Replica).filter(Replica.chunk_id == chunk.id).delete()
                self.db.delete(chunk)

            # Deallocate capacity
            self.engine.deallocate_capacity(pool, volume)

            # Delete volume
            pool_id = volume.pool_id
            vol_size = float(volume.size_gb)  # type: ignore
            vol_prov = volume.provisioning
            self.db.delete(volume)

            # Log event
            self.engine.log_event(
                EventType.VOLUME_DELETE,
                f"Deleted volume ({vol_size}GB, {vol_prov})",
                pool_id=pool_id,  # type: ignore
                volume_id=volume_id,
            )

            # Update pool health
            self.engine.update_pool_health(pool)

            self.db.commit()
            return True, "Volume deleted successfully"

        except Exception as e:
            self.db.rollback()
            return False, f"Volume deletion failed: {str(e)}"

    # ========================================================================
    # VOLUME QUERIES & INSIGHTS
    # ========================================================================

    def get_volume_details(self, volume_id: int) -> Optional[dict]:
        """
        Get detailed information about a volume.
        
        Args:
            volume_id: Volume to get details for
            
        Returns:
            Dict with volume details or None
        """
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return None

        # Get associated pool and chunks
        pool = self.db.query(StoragePool).filter(
            StoragePool.id == volume.pool_id
        ).first()

        from app.models import Chunk
        chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()

        # Count degraded chunks
        degraded_count = sum(1 for c in chunks if c.is_degraded)  # type: ignore

        # Extract scalar values
        vol_prov = volume.provisioning
        vol_state = volume.state
        
        return {
            "id": volume.id,
            "name": volume.name,
            "size_gb": float(volume.size_gb),  # type: ignore
            "used_capacity_gb": float(volume.used_capacity_gb),  # type: ignore
            "provisioning": vol_prov,
            "state": vol_state,
            "pool_id": pool.id if pool else None,
            "pool_name": pool.name if pool else None,
            "mapping_count": int(volume.mapping_count) if volume.mapping_count else 0,  # type: ignore
            "chunk_count": len(chunks),
            "degraded_chunks": degraded_count,
            "healthy": degraded_count == 0,
            "current_iops": float(volume.current_iops) if volume.current_iops else 0,  # type: ignore
            "current_bandwidth_mbps": float(volume.current_bandwidth_mbps) if volume.current_bandwidth_mbps else 0,  # type: ignore
            "read_iops": float(volume.read_iops) if volume.read_iops else 0,  # type: ignore
            "write_iops": float(volume.write_iops) if volume.write_iops else 0,  # type: ignore
            "average_read_latency_ms": float(volume.average_read_latency_ms) if volume.average_read_latency_ms else 0,  # type: ignore
            "average_write_latency_ms": float(volume.average_write_latency_ms) if volume.average_write_latency_ms else 0,  # type: ignore
            "created_at": volume.created_at.isoformat() if volume.created_at else None,  # type: ignore
        }

    def list_volumes(self, pool_id: Optional[int] = None) -> List[dict]:  # type: ignore
        """
        List all volumes, optionally filtered by pool.
        
        Args:
            pool_id: Optional pool filter
            
        Returns:
            List of volume dicts
        """
        query = self.db.query(Volume)
        if pool_id:
            query = query.filter(Volume.pool_id == pool_id)

        volumes = query.all()
        result = []
        for v in volumes:
            details = self.get_volume_details(int(v.id))  # type: ignore
            if details:
                result.append(details)
        return result

    def list_volume_mappings(self, volume_id: int) -> List[dict]:
        """
        List all SDCs with access to a volume.
        
        Args:
            volume_id: Volume to get mappings for
            
        Returns:
            List of mapping dicts
        """
        mappings = (
            self.db.query(VolumeMapping)
            .filter(VolumeMapping.volume_id == volume_id)
            .all()
        )

        result = []
        for mapping in mappings:
            sdc = self.db.query(SDCClient).filter(
                SDCClient.id == mapping.sdc_id
            ).first()
            access_mode = mapping.access_mode
            result.append({
                "sdc_id": mapping.sdc_id,
                "sdc_name": sdc.name if sdc else None,
                "access_mode": access_mode,
                "mapped_at": mapping.mapped_at.isoformat() if mapping.mapped_at else None,  # type: ignore
            })

        return result
