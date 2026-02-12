"""
PHASE 4: IO Simulation
Simulates realistic workloads and tracks metrics (IOPS, bandwidth, latency).
"""

import random
import math
from typing import Optional, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update
from app.models import (
    Volume,
    Chunk,
    Replica,
    SDCClient,
    SDSNode,
    VolumeMapping,
    StoragePool,
    EventLog,
    EventType,
)


class IOSimulator:
    """
    Simulates IO patterns and metrics generation for volumes.
    Supports read/write workloads with latency simulation.
    """

    # Configuration constants
    DEFAULT_IO_SIZE_KB = 64  # Assume 64KB average IO
    MIN_LATENCY_MS = 5
    MAX_LATENCY_MS = 50
    METRICS_AGGREGATION_WINDOW_SEC = 5
    IOPS_SAMPLE_SIZE = 10  # Moving average over N samples

    def __init__(self, db: Session):
        """
        Initialize IO simulator.
        
        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self.iops_history = {}  # volume_id -> list of samples
        self.latency_history = {}  # volume_id -> list of latencies
        self.bandwidth_history = {}  # volume_id -> list of bandwidth samples

    # ========================================================================
    # IO OPERATION SIMULATION
    # ========================================================================

    def simulate_volume_write(self, volume_id: int) -> Tuple[bool, float]:
        """
        Simulate a write operation to volume.
        
        Steps:
        1. Select random chunk in volume
        2. Update volume used_capacity
        3. Record write to all replicas (2 copies)
        4. Simulate latency (max of all replicas)
        5. Return latency
        
        Args:
            volume_id: Volume to write to
            
        Returns:
            (success: bool, latency_ms: float)
        """
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, 0.0

        # Select random chunk
        chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()
        if not chunks:
            return False, 0.0

        chunk = random.choice(chunks)

        # Get replicas for this chunk
        replicas = self.db.query(Replica).filter(Replica.chunk_id == chunk.id).all()
        if not replicas:
            return False, 0.0

        # Calculate write latency = max latency of all replicas
        max_latency = 0.0
        for replica in replicas:
            if replica.is_available:  # type: ignore
                sds = self.db.query(SDSNode).filter(
                    SDSNode.id == replica.sds_id
                ).first()
                if sds:
                    # Latency depends on SDS load
                    base_latency = random.uniform(
                        self.MIN_LATENCY_MS, self.MAX_LATENCY_MS
                    )
                    # Add load factor
                    sds_used = float(sds.used_capacity_gb)  # type: ignore
                    sds_total = float(sds.total_capacity_gb)  # type: ignore
                    load_factor = 1.0 + (sds_used / sds_total)
                    latency = base_latency * load_factor
                    max_latency = max(max_latency, latency)

        # Update volume used capacity for thin volumes
        from app.models import ProvisioningType
        
        provisioning = volume.provisioning  # type: ignore
        size_gb = float(volume.size_gb)  # type: ignore
        
        if provisioning == ProvisioningType.THIN:  # type: ignore
            io_size_gb = self.DEFAULT_IO_SIZE_KB / (1024 * 1024)
            curr_used = float(volume.used_capacity_gb)  # type: ignore
            new_used = min(curr_used + io_size_gb, size_gb)
            
            self.db.execute(
                sql_update(Volume).where(Volume.id == volume_id).values(
                    used_capacity_gb=new_used
                )
            )

        # Update write IOPS counter
        curr_write_iops = int(volume.write_iops)  # type: ignore
        
        # Track average write latency
        if hasattr(self, '_write_latencies'):
            self._write_latencies.append(max_latency)
            avg_write_latency = sum(self._write_latencies[-10:]) / len(
                self._write_latencies[-10:]
            )
        else:
            self._write_latencies = [max_latency]
            avg_write_latency = max_latency

        self.db.execute(
            sql_update(Volume).where(Volume.id == volume_id).values(
                write_iops=curr_write_iops + 1,
                average_write_latency_ms=avg_write_latency
            )
        )

        return True, max_latency

    def simulate_volume_read(self, volume_id: int) -> Tuple[bool, float]:
        """
        Simulate a read operation from volume.
        
        Steps:
        1. Select random chunk in volume
        2. Select best available replica (lowest latency)
        3. Simulate latency for that replica
        4. Return latency
        
        Args:
            volume_id: Volume to read from
            
        Returns:
            (success: bool, latency_ms: float)
        """
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return False, 0.0

        # Select random chunk
        chunks = self.db.query(Chunk).filter(Chunk.volume_id == volume_id).all()
        if not chunks:
            return False, 0.0

        chunk = random.choice(chunks)

        # Get best available replica
        chunk_id = int(chunk.id)  # type: ignore
        best_replica = self._select_best_replica(chunk_id)
        if not best_replica:
            return False, 0.0  # No available replicas

        # Calculate read latency
        sds = self.db.query(SDSNode).filter(
            SDSNode.id == best_replica.sds_id
        ).first()
        if not sds:
            return False, 0.0

        # Latency depends on SDS load
        base_latency = random.uniform(self.MIN_LATENCY_MS, self.MAX_LATENCY_MS)
        sds_used = float(sds.used_capacity_gb)  # type: ignore
        sds_total = float(sds.total_capacity_gb)  # type: ignore
        load_factor = 1.0 + (sds_used / sds_total)
        latency = base_latency * load_factor

        # Update read IOPS counter
        curr_read_iops = int(volume.read_iops)  # type: ignore

        # Track average read latency
        if hasattr(self, '_read_latencies'):
            self._read_latencies.append(latency)
            avg_read_latency = sum(self._read_latencies[-10:]) / len(
                self._read_latencies[-10:]
            )
        else:
            self._read_latencies = [latency]
            avg_read_latency = latency

        self.db.execute(
            sql_update(Volume).where(Volume.id == volume_id).values(
                read_iops=curr_read_iops + 1,
                average_read_latency_ms=avg_read_latency
            )
        )

        return True, latency

    def _select_best_replica(self, chunk_id: int) -> Optional[Replica]:
        """
        Select the best available replica for a chunk.
        
        Preference order:
        1. Must be available and on UP SDS
        2. Prefer lowest average_latency_ms
        3. Fallback to any available
        
        Args:
            chunk_id: Chunk to select replica for
            
        Returns:
            Replica object or None
        """
        replicas = (
            self.db.query(Replica)
            .filter(Replica.chunk_id == chunk_id, Replica.is_available == True)
            .all()
        )

        if not replicas:
            return None

        # Score each replica by SDS latency
        best_replica = None
        best_score = float('inf')

        for replica in replicas:
            sds = self.db.query(SDSNode).filter(
                SDSNode.id == replica.sds_id
            ).first()
            if sds:
                from app.models import SDSNodeState
                
                if sds.state == SDSNodeState.UP:  # type: ignore
                    # Lower latency is better
                    sds_latency = float(sds.average_latency_ms)  # type: ignore
                    if sds_latency < best_score:  # type: ignore
                        best_score = sds_latency
                        best_replica = replica

        return best_replica if best_replica else replicas[0]

    # ========================================================================
    # METRICS AGGREGATION & TRACKING
    # ========================================================================

    def aggregate_volume_metrics(self, volume_id: int) -> dict:
        """
        Aggregate metrics for a volume.
        
        Calculates:
        - Total IOPS (read + write)
        - Bandwidth (IOPS × IO size)
        - Average latency (read + write)
        
        Args:
            volume_id: Volume to aggregate metrics for
            
        Returns:
            Dict with metrics
        """
        volume = self.db.query(Volume).filter(Volume.id == volume_id).first()
        if not volume:
            return {}

        # Calculate total IOPS with safe type conversions
        read_iops = int(volume.read_iops)  # type: ignore
        write_iops = int(volume.write_iops)  # type: ignore
        total_iops = read_iops + write_iops

        # Calculate bandwidth (IOPS × IO size KB ÷ 1MB)
        bandwidth_mbps = (total_iops * self.DEFAULT_IO_SIZE_KB) / 1024

        # Calculate average latency
        read_latency = float(volume.average_read_latency_ms)  # type: ignore
        write_latency = float(volume.average_write_latency_ms)  # type: ignore
        avg_latency = (read_latency + write_latency) / 2

        return {
            "volume_id": volume_id,
            "volume_name": volume.name,
            "total_iops": total_iops,
            "read_iops": read_iops,
            "write_iops": write_iops,
            "bandwidth_mbps": bandwidth_mbps,
            "average_read_latency_ms": read_latency,
            "average_write_latency_ms": write_latency,
            "average_latency_ms": avg_latency,
        }

    def aggregate_pool_metrics(self, pool_id: int) -> dict:
        """
        Aggregate metrics across all volumes in pool.
        
        Args:
            pool_id: Pool to aggregate metrics for
            
        Returns:
            Dict with aggregated metrics
        """
        pool = self.db.query(StoragePool).filter(StoragePool.id == pool_id).first()
        if not pool:
            return {}

        volumes = self.db.query(Volume).filter(Volume.pool_id == pool_id).all()
        volume_ids = [int(v.id) for v in volumes]  # type: ignore

        total_iops = 0
        total_bandwidth = 0
        latency_sum = 0
        latency_count = 0

        for volume_id in volume_ids:
            metrics = self.aggregate_volume_metrics(volume_id)
            if metrics:
                total_iops += metrics.get("total_iops", 0)
                total_bandwidth += metrics.get("bandwidth_mbps", 0)
                latency_sum += metrics.get("average_latency_ms", 0)
                latency_count += 1

        avg_latency = latency_sum / latency_count if latency_count > 0 else 0

        # Update pool metrics
        self.db.execute(
            sql_update(StoragePool).where(StoragePool.id == pool_id).values(
                total_iops=total_iops,
                total_bandwidth_mbps=total_bandwidth
            )
        )

        return {
            "pool_id": pool_id,
            "pool_name": pool.name,
            "total_iops": total_iops,
            "total_bandwidth_mbps": total_bandwidth,
            "average_latency_ms": avg_latency,
            "volume_count": len(volumes),
        }

    def aggregate_sds_metrics(self, sds_id: int) -> dict:
        """
        Aggregate metrics for an SDS node.
        
        Calculates IOPS and bandwidth from all replicas on this node.
        
        Args:
            sds_id: SDS node to aggregate metrics for
            
        Returns:
            Dict with SDS metrics
        """
        sds = self.db.query(SDSNode).filter(SDSNode.id == sds_id).first()
        if not sds:
            return {}

        # Get all replicas on this SDS
        replicas = self.db.query(Replica).filter(Replica.sds_id == sds_id).all()

        total_iops = 0
        latency_sum = 0
        latency_count = 0

        for replica in replicas:
            chunk = self.db.query(Chunk).filter(Chunk.id == replica.chunk_id).first()
            if chunk:
                volume = self.db.query(Volume).filter(
                    Volume.id == chunk.volume_id
                ).first()
                if volume:
                    # Proportional IOPS (replica gets portion of volume IOPS)
                    vol_read = int(volume.read_iops)  # type: ignore
                    vol_write = int(volume.write_iops)  # type: ignore
                    volume_iops = vol_read + vol_write
                    replica_count = (
                        self.db.query(Replica)
                        .filter(Replica.chunk_id == chunk.id, Replica.is_available == True)
                        .count()
                    )
                    if replica_count > 0:
                        replica_iops = volume_iops / replica_count
                        total_iops += replica_iops
                        latency_sum += float(volume.average_read_latency_ms)  # type: ignore
                        latency_count += 1

        avg_latency = latency_sum / latency_count if latency_count > 0 else 0
        bandwidth = (total_iops * self.DEFAULT_IO_SIZE_KB) / 1024

        # Update SDS metrics
        self.db.execute(
            sql_update(SDSNode).where(SDSNode.id == sds_id).values(
                current_iops=int(total_iops),
                current_bandwidth_mbps=bandwidth,
                average_latency_ms=avg_latency
            )
        )

        return {
            "sds_id": sds_id,
            "sds_name": sds.name,
            "current_iops": total_iops,
            "current_bandwidth_mbps": bandwidth,
            "average_latency_ms": avg_latency,
        }

    def aggregate_sdc_metrics(self, sdc_id: int) -> dict:
        """
        Aggregate metrics for an SDC client.
        
        Calculates IOPS and bandwidth from all mapped volumes.
        
        Args:
            sdc_id: SDC to aggregate metrics for
            
        Returns:
            Dict with SDC metrics
        """
        sdc = self.db.query(SDCClient).filter(SDCClient.id == sdc_id).first()
        if not sdc:
            return {}

        # Get all mappings for this SDC
        mappings = (
            self.db.query(VolumeMapping)
            .filter(VolumeMapping.sdc_id == sdc_id)
            .all()
        )

        total_iops = 0
        total_bandwidth = 0
        latency_sum = 0
        latency_count = 0

        for mapping in mappings:
            volume = self.db.query(Volume).filter(
                Volume.id == mapping.volume_id
            ).first()
            if volume:
                vol_read = int(volume.read_iops)  # type: ignore
                vol_write = int(volume.write_iops)  # type: ignore
                volume_iops = vol_read + vol_write
                total_iops += volume_iops
                
                bandwidth = (volume_iops * self.DEFAULT_IO_SIZE_KB) / 1024
                total_bandwidth += bandwidth
                
                latency_sum += float(volume.average_read_latency_ms)  # type: ignore
                latency_count += 1

        avg_latency = latency_sum / latency_count if latency_count > 0 else 0

        # Update SDC metrics
        self.db.execute(
            sql_update(SDCClient).where(SDCClient.id == sdc_id).values(
                current_iops=int(total_iops),
                current_bandwidth_mbps=total_bandwidth,
                average_latency_ms=avg_latency
            )
        )

        return {
            "sdc_id": sdc_id,
            "sdc_name": sdc.name,
            "current_iops": total_iops,
            "current_bandwidth_mbps": total_bandwidth,
            "average_latency_ms": avg_latency,
            "mapped_volume_count": len(mappings),
        }

    # ========================================================================
    # WORKLOAD GENERATION
    # ========================================================================

    def reset_metric_counters(self) -> None:
        """Reset IOPS and latency counters for metrics collection."""
        volumes = self.db.query(Volume).all()
        for volume in volumes:
            vol_id = int(volume.id)  # type: ignore
            self.db.execute(
                sql_update(Volume).where(Volume.id == vol_id).values(
                    read_iops=0,
                    write_iops=0
                )
            )
        self.db.commit()

    def generate_workload_tick(self, duration_ms: int = 100) -> dict:
        """
        Generate random IO workload for all mapped volumes.
        
        For each mapped volume:
        - Generate random reads/writes based on typical 50/50 split
        - Update counters and metrics
        - Return summary
        
        Args:
            duration_ms: Duration of this workload tick (for rate calculation)
            
        Returns:
            Dict with workload summary
        """
        # Get all mapped volumes
        mappings = self.db.query(VolumeMapping).all()
        volume_ids = set()
        for m in mappings:
            volume_ids.add(int(m.volume_id))  # type: ignore

        reads = 0
        writes = 0
        read_latency_sum = 0
        write_latency_sum = 0

        for volume_id in volume_ids:
            # Assume 100 IOs per second per mapped volume
            # Divided evenly between reads and writes
            ios_this_tick = int(100 * duration_ms / 1000)

            for _ in range(ios_this_tick):
                if random.random() < 0.5:
                    # Read
                    success, latency = self.simulate_volume_read(volume_id)
                    if success:
                        reads += 1
                        read_latency_sum += latency
                else:
                    # Write
                    success, latency = self.simulate_volume_write(volume_id)
                    if success:
                        writes += 1
                        write_latency_sum += latency

        self.db.commit()

        return {
            "reads": reads,
            "writes": writes,
            "total_ios": reads + writes,
            "read_latency_avg_ms": read_latency_sum / reads if reads > 0 else 0,
            "write_latency_avg_ms": write_latency_sum / writes if writes > 0 else 0,
        }
