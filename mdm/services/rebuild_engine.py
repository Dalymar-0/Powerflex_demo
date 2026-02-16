"""
PHASE 5: Failure & Rebuild Orchestration
SDS node failure detection, rebuild job management, and recovery coordination.
Implements rate-limiting, progress tracking, and stall detection.
"""

import time
from typing import Tuple, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update
from mdm.models import (
    StoragePool,
    SDSNode,
    RebuildJob,
    Replica,
    Chunk,
    EventLog,
    SDSNodeState,
    RebuildState,
    PoolHealth,
    VolumeState,
    EventType,
)
from mdm.services.storage_engine import StorageEngine


class RebuildEngine:
    """
    Manages SDS node failures, rebuild orchestration, and recovery.
    Handles rebuild rate limiting, progress tracking, and stall detection.
    """

    # Configuration constants
    REBUILD_CHUNK_SIZE_MB = 4  # Must match storage engine
    DEFAULT_REBUILD_RATE_MBPS = 100  # MB/s rate limit
    STALL_DETECTION_TIMEOUT_SEC = 60  # Stall if no progress for 60s
    PROGRESS_POLL_INTERVAL_SEC = 1  # Check progress every 1s

    def __init__(self, db: Session):
        """
        Initialize rebuild engine.
        
        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self.engine = StorageEngine(db)

    # ========================================================================
    # NODE FAILURE HANDLING
    # ========================================================================

    def fail_sds_node(self, sds_id: int) -> Tuple[bool, str]:
        """
        Simulate SDS node failure.
        
        Steps:
        1. Validate SDS exists
        2. Set state to DOWN
        3. Mark affected chunks as degraded
        4. Update affected pool health to DEGRADED
        5. Trigger auto-rebuild start
        6. Log event
        
        Args:
            sds_id: SDS node to fail
            
        Returns:
            (success: bool, message: str)
        """
        # Validate SDS exists
        sds = self.db.query(SDSNode).filter(SDSNode.id == sds_id).first()
        if not sds:
            return False, f"SDS {sds_id} not found"

        if sds.state == SDSNodeState.DOWN:  # type: ignore
            return False, "SDS already DOWN"

        try:
            # Update SDS state using SQL update
            self.db.execute(
                sql_update(SDSNode).where(SDSNode.id == sds_id).values(
                    state=SDSNodeState.DOWN.value,
                    state_last_change=datetime.utcnow()
                )
            )

            # Find all pools with volumes on this SDS
            from mdm.models import Volume
            
            affected_pools = set()
            replicas = (
                self.db.query(Replica)
                .filter(Replica.sds_id == sds_id)
                .all()
            )

            for replica in replicas:
                chunk = self.db.query(Chunk).filter(
                    Chunk.id == replica.chunk_id
                ).first()
                if chunk:
                    volume = self.db.query(Volume).filter(
                        Volume.id == chunk.volume_id
                    ).first()
                    if volume:
                        affected_pools.add(volume.pool_id)

            # Mark chunks degraded for each affected pool
            degraded_count = 0
            for pool_id in affected_pools:
                pool = self.db.query(StoragePool).filter(
                    StoragePool.id == pool_id
                ).first()
                if pool:
                    count = self.engine.mark_chunks_degraded(sds_id, pool)
                    degraded_count += count
                    
                    # Set pool state to DEGRADED using SQL update
                    self.db.execute(
                        sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                            health=PoolHealth.DEGRADED.value,
                            rebuild_state=RebuildState.IDLE.value
                        )
                    )
                    
                    # Log event
                    self.engine.log_event(
                        EventType.SDS_STATE_CHANGE,
                        f"SDS node '{sds.name}' failed - {count} chunks marked degraded",
                        pool_id=pool_id,
                        sds_id=sds_id,
                    )

                    # Auto-start rebuild
                    rebuild_success, rebuild_msg = self.start_rebuild(pool_id)
                    if not rebuild_success:
                        # Rebuild start failed, log the error
                        self.engine.log_event(
                            EventType.REBUILD_FAILED,
                            f"Failed to start auto-rebuild: {rebuild_msg}",
                            pool_id=pool_id,
                            sds_id=sds_id,
                        )

            self.db.commit()
            return (
                True,
                f"SDS '{sds.name}' marked DOWN - {degraded_count} chunks degraded, "
                f"rebuild triggered for {len(affected_pools)} pool(s)",
            )

        except Exception as e:
            self.db.rollback()
            return False, f"SDS failure handling failed: {str(e)}"

    def recover_sds_node(self, sds_id: int) -> Tuple[bool, str]:
        """
        Recover a failed SDS node.
        
        Steps:
        1. Validate SDS exists and is DOWN
        2. Set state to UP
        3. Check if chunks can be healed (all replicas present)
        4. Heal degraded chunks where possible
        5. Update affected pool health
        6. Log event
        
        Args:
            sds_id: SDS node to recover
            
        Returns:
            (success: bool, message: str)
        """
        # Validate SDS exists
        sds = self.db.query(SDSNode).filter(SDSNode.id == sds_id).first()
        if not sds:
            return False, f"SDS {sds_id} not found"

        if sds.state != SDSNodeState.DOWN:  # type: ignore
            return False, f"SDS not DOWN (current state: {sds.state.value})"

        try:
            # Update SDS state using SQL update
            self.db.execute(
                sql_update(SDSNode).where(SDSNode.id == sds_id).values(
                    state=SDSNodeState.UP.value,
                    state_last_change=datetime.utcnow()
                )
            )

            # Find affected pools
            from mdm.models import Volume
            
            affected_pools = set()
            replicas = (
                self.db.query(Replica)
                .filter(Replica.sds_id == sds_id)
                .all()
            )

            for replica in replicas:
                # Mark replicas on recovered node as available using SQL update
                self.db.execute(
                    sql_update(Replica).where(Replica.id == replica.id).values(
                        is_available=True
                    )
                )
                chunk = self.db.query(Chunk).filter(
                    Chunk.id == replica.chunk_id
                ).first()
                if chunk:
                    volume = self.db.query(Volume).filter(
                        Volume.id == chunk.volume_id
                    ).first()
                    if volume:
                        affected_pools.add(volume.pool_id)

            # Heal chunks for each affected pool
            healed_count = 0
            for pool_id in affected_pools:
                pool = self.db.query(StoragePool).filter(
                    StoragePool.id == pool_id
                ).first()
                if pool:
                    count = self.engine.heal_chunks_on_recovery(sds_id, pool)
                    healed_count += count
                    
                    # Update pool health
                    self.engine.update_pool_health(pool)
                    
                    # Log event
                    self.engine.log_event(
                        EventType.SDS_STATE_CHANGE,
                        f"SDS node '{sds.name}' recovered - {count} chunks healed",
                        pool_id=pool_id,
                        sds_id=sds_id,
                    )

            self.db.commit()
            return (
                True,
                f"SDS '{sds.name}' recovered - {healed_count} chunks healed",
            )

        except Exception as e:
            self.db.rollback()
            return False, f"SDS recovery failed: {str(e)}"

    # ========================================================================
    # REBUILD JOB ORCHESTRATION
    # ========================================================================

    def start_rebuild(self, pool_id: int) -> Tuple[bool, str]:
        """
        Start rebuild operation for pool.
        
        Steps:
        1. Validate pool exists
        2. Find all degraded chunks
        3. Create rebuild job
        4. Calculate total bytes to rebuild
        5. Create new replicas on healthy SDS for degraded chunks
        6. Set pool state to IN_PROGRESS
        7. Log event
        
        Args:
            pool_id: Pool to rebuild
            
        Returns:
            (success: bool, message: str)
        """
        # Validate pool exists
        pool = self.db.query(StoragePool).filter(StoragePool.id == pool_id).first()
        if not pool:
            return False, f"Pool {pool_id} not found"

        # Check if rebuild already in progress
        active_job = (
            self.db.query(RebuildJob)
            .filter(
                RebuildJob.pool_id == pool_id,
                RebuildJob.state == RebuildState.IN_PROGRESS,
            )
            .first()
        )
        if active_job:
            return False, "Rebuild already in progress"

        try:
            # Find degraded chunks
            from mdm.models import Volume
            
            volumes = self.db.query(Volume).filter(Volume.pool_id == pool_id).all()
            degraded_chunks = []

            for volume in volumes:
                chunks = (
                    self.db.query(Chunk)
                    .filter(Chunk.volume_id == volume.id, Chunk.is_degraded == True)
                    .all()
                )
                degraded_chunks.extend(chunks)

            if not degraded_chunks:
                return False, "No degraded chunks to rebuild"

            # Calculate total bytes
            total_bytes = len(degraded_chunks) * self.REBUILD_CHUNK_SIZE_MB

            # Create rebuild job
            job = RebuildJob(
                pool_id=pool_id,
                state=RebuildState.IN_PROGRESS,
                progress_percent=0,
                total_bytes_to_rebuild=total_bytes,
                bytes_rebuilt=0,
                estimated_time_remaining_seconds=0,
                current_rebuild_rate_mbps=pool.rebuild_rate_limit_mbps,
            )
            self.db.add(job)
            self.db.flush()

            # Create new replicas for degraded chunks
            chunks_queued = 0
            for chunk in degraded_chunks:
                # Find a healthy SDS with capacity to rebuild this chunk
                target_sds = self._find_rebuild_target(pool, chunk)
                if not target_sds:
                    # Can't find target for this chunk - mark as loss
                    continue

                # Create new replica with rebuilding flag
                new_replica = Replica(
                    chunk_id=chunk.id,
                    sds_id=target_sds.id,
                    is_available=False,  # Not available until rebuild complete
                    is_current=False,
                    is_rebuilding=True,
                )
                self.db.add(new_replica)
                chunks_queued += 1

            # Update pool state using SQL update
            self.db.execute(
                sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                    rebuild_state=RebuildState.IN_PROGRESS.value,
                    rebuild_progress_percent=0
                )
            )

            # Log event
            self.engine.log_event(
                EventType.REBUILD_START,
                f"Rebuild started: {chunks_queued}/{len(degraded_chunks)} chunks queued, "
                f"total {total_bytes}MB to rebuild at {pool.rebuild_rate_limit_mbps}MB/s",
                pool_id=pool_id,
            )

            self.db.commit()
            return True, f"Rebuild started: {chunks_queued} chunks queued"

        except Exception as e:
            self.db.rollback()
            return False, f"Rebuild start failed: {str(e)}"

    def _find_rebuild_target(self, pool: StoragePool, chunk: Chunk) -> Optional[SDSNode]:
        """
        Find a healthy SDS node to rebuild chunk replica on.
        
        Selection criteria:
        1. SDS must be UP (not DOWN or DEGRADED during rebuild)
        2. SDS must have available capacity
        3. SDS must not already have a replica of this chunk
        4. Prefer SDS in different FaultSet from existing replicas
        
        Args:
            pool: Pool being rebuilt
            chunk: Chunk to find rebuild target for
            
        Returns:
            Selected SDS node or None if no suitable target found
        """
        # Get existing replicas for this chunk
        existing_replicas = (
            self.db.query(Replica)
            .filter(Replica.chunk_id == chunk.id, Replica.is_rebuilding == False)
            .all()
        )
        existing_sds_ids = {r.sds_id for r in existing_replicas}
        existing_fault_sets = set()
        for replica in existing_replicas:
            sds = self.db.query(SDSNode).filter(SDSNode.id == replica.sds_id).first()
            if sds and sds.fault_set_id:  # type: ignore
                existing_fault_sets.add(sds.fault_set_id)

        # Find available SDS nodes
        available_sds = (
            self.db.query(SDSNode)
            .filter(
                SDSNode.protection_domain_id == pool.pd_id,
                SDSNode.state == SDSNodeState.UP,
                SDSNode.id.notin_(existing_sds_ids),  # Not already have this chunk
            )
            .all()
        )

        # Sort by: 1) different FaultSet, 2) most available capacity
        def score_sds(sds):
            fault_set_bonus = 1000 if (sds.fault_set_id not in existing_fault_sets) else 0
            capacity_bonus = sds.total_capacity_gb - sds.used_capacity_gb
            return fault_set_bonus + capacity_bonus

        available_sds.sort(key=score_sds, reverse=True)

        return available_sds[0] if available_sds else None

    # ========================================================================
    # REBUILD PROGRESS & RATE LIMITING
    # ========================================================================

    def update_rebuild_progress(self, pool_id: int) -> Tuple[bool, str]:
        """
        Update rebuild job progress using rate limiting.
        
        Steps:
        1. Get active rebuild job
        2. Calculate bytes to rebuild this tick (respecting rate limit)
        3. Find rebuilding replicas and mark as complete
        4. Update progress_percent and estimated_time_remaining
        5. Check for stalls
        6. If 100%: complete rebuild, heal chunks, set pool OK
        
        Args:
            pool_id: Pool rebuild to update
            
        Returns:
            (success: bool, message: str)
        """
        # Get active rebuild job
        job = (
            self.db.query(RebuildJob)
            .filter(
                RebuildJob.pool_id == pool_id,
                RebuildJob.state == RebuildState.IN_PROGRESS,
            )
            .first()
        )

        if not job:
            return False, "No active rebuild for pool"

        pool = self.db.query(StoragePool).filter(StoragePool.id == pool_id).first()
        if not pool:
            return False, "Pool not found"

        try:
            # Get rebuilding replicas
            rebuilding = (
                self.db.query(Replica)
                .filter(Replica.is_rebuilding == True)
                .all()
            )

            if not rebuilding:
                # All replicas rebuilt
                self.db.execute(
                    sql_update(RebuildJob).where(RebuildJob.pool_id == pool_id).values(
                        state=RebuildState.COMPLETED.value,
                        completed_at=datetime.utcnow(),
                        progress_percent=100
                    )
                )

                # Mark chunks as non-degraded
                from mdm.models import Volume
                volumes = (
                    self.db.query(Volume)
                    .filter(Volume.pool_id == pool_id)
                    .all()
                )
                healed_count = 0
                for volume in volumes:
                    chunks = (
                        self.db.query(Chunk)
                        .filter(Chunk.volume_id == volume.id)
                        .all()
                    )
                    for chunk in chunks:
                        if chunk.is_degraded:  # type: ignore
                            # Check if now has 2 available replicas
                            available = (
                                self.db.query(Replica)
                                .filter(
                                    Replica.chunk_id == chunk.id,
                                    Replica.is_available == True,
                                )
                                .count()
                            )
                            if available >= 2:
                                self.db.execute(
                                    sql_update(Chunk).where(Chunk.id == chunk.id).values(
                                        is_degraded=False
                                    )
                                )
                                healed_count += 1

                # Update pool state
                self.db.execute(
                    sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                        rebuild_state=RebuildState.COMPLETED.value,
                        rebuild_progress_percent=100
                    )
                )
                self.engine.update_pool_health(pool)

                # Log completion
                self.engine.log_event(
                    EventType.REBUILD_COMPLETE,
                    f"Rebuild completed: {healed_count} chunks healed, pool healthy",
                    pool_id=pool_id,
                )

                self.db.commit()
                return True, "Rebuild completed"

            # Calculate rebuild rate this tick
            # Assume tick is 1 second, rebuild_rate is MB/s
            rebuild_rate = float(pool.rebuild_rate_limit_mbps)  # type: ignore
            bytes_per_tick = rebuild_rate * 1024 * 1024  # MB to bytes
            chunk_size_bytes = self.REBUILD_CHUNK_SIZE_MB * 1024 * 1024

            # Complete the first N replicas up to our rate budget
            replicas_to_complete = int(bytes_per_tick / chunk_size_bytes)
            replicas_completed = 0
            bytes_completed = 0

            for replica in rebuilding[:replicas_to_complete]:
                self.db.execute(
                    sql_update(Replica).where(Replica.id == replica.id).values(
                        is_rebuilding=False,
                        is_available=True
                    )
                )
                bytes_completed += chunk_size_bytes
                replicas_completed += 1

            # Update job progress using safe conversions
            job_bytes_rebuilt = float(job.bytes_rebuilt)  # type: ignore
            job_total_bytes = float(job.total_bytes_to_rebuild)  # type: ignore
            job_rate = float(job.current_rebuild_rate_mbps)  # type: ignore
            
            new_bytes_rebuilt = job_bytes_rebuilt + bytes_completed
            new_progress = (new_bytes_rebuilt / job_total_bytes * 100) if job_total_bytes > 0 else 0

            self.db.execute(
                sql_update(RebuildJob).where(RebuildJob.pool_id == pool_id).values(
                    bytes_rebuilt=int(new_bytes_rebuilt),
                    progress_percent=int(new_progress)
                )
            )

            # Estimate time remaining
            estimated_seconds = 0
            if job_rate > 0:
                bytes_remaining = job_total_bytes - new_bytes_rebuilt
                estimated_seconds = int(bytes_remaining / (job_rate * 1024 * 1024))
                self.db.execute(
                    sql_update(RebuildJob).where(RebuildJob.pool_id == pool_id).values(
                        estimated_time_remaining_seconds=estimated_seconds
                    )
                )

            # Check for stalls
            started_at = job.started_at  # type: ignore
            time_since_start = (datetime.utcnow() - started_at).total_seconds()
            if time_since_start > self.STALL_DETECTION_TIMEOUT_SEC:
                if new_bytes_rebuilt == 0:
                    self.db.execute(
                        sql_update(RebuildJob).where(RebuildJob.pool_id == pool_id).values(
                            state=RebuildState.STALLED.value
                        )
                    )
                    self.db.execute(
                        sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                            rebuild_state=RebuildState.STALLED.value
                        )
                    )
                    self.engine.log_event(
                        EventType.REBUILD_FAILED,
                        "Rebuild stalled: no progress detected",
                        pool_id=pool_id,
                    )

            # Update pool progress
            self.db.execute(
                sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                    rebuild_progress_percent=int(new_progress)
                )
            )

            self.db.commit()
            
            # Format response using calculated values (not from job object)
            bytes_rebuilt_gb = new_bytes_rebuilt / (1024**3)
            total_bytes_gb = job_total_bytes / (1024**3)
            
            return (
                True,
                f"Rebuild progress: {new_progress:.1f}% "
                f"({bytes_rebuilt_gb:.2f}GB / "
                f"{total_bytes_gb:.2f}GB) - "
                f"ETA: {estimated_seconds if job_rate > 0 else 0}s",
            )

        except Exception as e:
            self.db.rollback()
            return False, f"Progress update failed: {str(e)}"

    # ========================================================================
    # REBUILD QUERIES
    # ========================================================================

    def get_rebuild_status(self, pool_id: int) -> Optional[dict]:
        """
        Get current rebuild status for pool.
        
        Args:
            pool_id: Pool to check
            
        Returns:
            Dict with rebuild status or None
        """
        job = (
            self.db.query(RebuildJob)
            .filter(RebuildJob.pool_id == pool_id)
            .order_by(RebuildJob.started_at.desc())
            .first()
        )

        if not job:
            return None

        return {
            "job_id": job.id,
            "pool_id": job.pool_id,
            "state": job.state.value,  # type: ignore
            "progress_percent": job.progress_percent,
            "bytes_rebuilt": job.bytes_rebuilt,
            "total_bytes": job.total_bytes_to_rebuild,
            "current_rate_mbps": job.current_rebuild_rate_mbps,
            "estimated_time_remaining_seconds": job.estimated_time_remaining_seconds,
            "started_at": job.started_at.isoformat() if job.started_at is not None else None,  # type: ignore
            "completed_at": job.completed_at.isoformat() if job.completed_at is not None else None,  # type: ignore
        }
