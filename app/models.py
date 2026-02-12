from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum

Base = declarative_base()

# ============================================================================
# ENUM DEFINITIONS
# ============================================================================

class SDSNodeState(str, enum.Enum):
    """SDS node operational state"""
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"

class PoolHealth(str, enum.Enum):
    """Storage pool health status"""
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"

class VolumeState(str, enum.Enum):
    """Volume operational state"""
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    DEGRADED = "DEGRADED"
    CREATING = "CREATING"
    DELETING = "DELETING"

class ProtectionPolicy(str, enum.Enum):
    """Data protection policy for pool"""
    TWO_COPIES = "two_copies"
    EC = "erasure_coding"

class ProvisioningType(str, enum.Enum):
    """Volume provisioning type"""
    THIN = "thin"
    THICK = "thick"

class AccessMode(str, enum.Enum):
    """Volume access mode for SDC mapping"""
    READ_WRITE = "readWrite"
    READ_ONLY = "readOnly"

class EventType(str, enum.Enum):
    """Event log event types"""
    SDS_STATE_CHANGE = "sds_state_change"
    POOL_HEALTH_CHANGE = "pool_health_change"
    VOLUME_CREATE = "volume_create"
    VOLUME_DELETE = "volume_delete"
    VOLUME_MAP = "volume_map"
    VOLUME_UNMAP = "volume_unmap"
    VOLUME_EXTEND = "volume_extend"
    REBUILD_START = "rebuild_start"
    REBUILD_COMPLETE = "rebuild_complete"
    REBUILD_FAILED = "rebuild_failed"
    IO_ERROR = "io_error"
    REPLICA_DEGRADED = "replica_degraded"

class RebuildState(str, enum.Enum):
    """Rebuild operation state"""
    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    STALLED = "stalled"
    COMPLETED = "completed"
    FAILED = "failed"

# ============================================================================
# CORE MODEL DEFINITIONS
# ============================================================================

class ProtectionDomain(Base):
    """Top-level organizational container for pools and nodes"""
    __tablename__ = "protection_domains"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pools = relationship("StoragePool", back_populates="pd", cascade="all, delete-orphan")
    sds_nodes = relationship("SDSNode", back_populates="pd", cascade="all, delete-orphan")
    fault_sets = relationship("FaultSet", back_populates="pd", cascade="all, delete-orphan")


class FaultSet(Base):
    """Fault domain for failure isolation (e.g., rack, chassis)"""
    __tablename__ = "fault_sets"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    pd_id = Column(Integer, ForeignKey("protection_domains.id"), nullable=False)
    fault_domain_type = Column(String)  # rack, chassis, etc.
    
    # Relationships
    pd = relationship("ProtectionDomain", back_populates="fault_sets")
    sds_nodes = relationship("SDSNode", back_populates="fault_set")


class StoragePool(Base):
    """Container for volumes with consistent protection policy and capacity management"""
    __tablename__ = "storage_pools"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    pd_id = Column(Integer, ForeignKey("protection_domains.id"), nullable=False)
    
    # Capacity
    total_capacity_gb = Column(Float, nullable=False)
    used_capacity_gb = Column(Float, default=0)
    reserved_capacity_gb = Column(Float, default=0)  # For thick volumes
    
    # Configuration
    protection_policy = Column(Enum(ProtectionPolicy), nullable=False)
    chunk_size_mb = Column(Float, default=4)  # Typical 4MB chunks
    rebuild_rate_limit_mbps = Column(Float, default=100)  # Rate limiting
    
    # State
    health = Column(Enum(PoolHealth), default=PoolHealth.OK)
    rebuild_state = Column(Enum(RebuildState), default=RebuildState.IDLE)
    rebuild_progress_percent = Column(Float, default=0)  # 0-100
    
    # Metrics tracking
    total_iops = Column(Float, default=0)
    total_bandwidth_mbps = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pd = relationship("ProtectionDomain", back_populates="pools")
    volumes = relationship("Volume", back_populates="pool", cascade="all, delete-orphan")


class SDSNode(Base):
    """Storage Data Server - physical node holding data"""
    __tablename__ = "sds_nodes"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    ip_address = Column(String)
    port = Column(Integer, default=7072)
    
    # Capacity
    total_capacity_gb = Column(Float, nullable=False)
    used_capacity_gb = Column(Float, default=0)
    
    # State
    state = Column(Enum(SDSNodeState), default=SDSNodeState.UP)
    
    # Configuration
    devices = Column(String)  # Comma-separated device paths
    protection_domain_id = Column(Integer, ForeignKey("protection_domains.id"), nullable=False)
    fault_set_id = Column(Integer, ForeignKey("fault_sets.id"))
    
    # Metrics
    current_iops = Column(Float, default=0)
    current_bandwidth_mbps = Column(Float, default=0)
    average_latency_ms = Column(Float, default=0)
    failed_chunks_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    state_last_change = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pd = relationship("ProtectionDomain", back_populates="sds_nodes")
    fault_set = relationship("FaultSet", back_populates="sds_nodes")
    replicas = relationship("Replica", back_populates="sds_node")


class SDCClient(Base):
    """Storage Data Client - host accessing volumes"""
    __tablename__ = "sdc_clients"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    ip_address = Column(String)
    hostname = Column(String)
    
    # Metrics
    current_iops = Column(Float, default=0)
    current_bandwidth_mbps = Column(Float, default=0)
    average_latency_ms = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    mapped_volumes = relationship("VolumeMapping", back_populates="sdc", cascade="all, delete-orphan")


class Volume(Base):
    """Logical storage volume exposed to SDCs"""
    __tablename__ = "volumes"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    
    # Size and provisioning
    size_gb = Column(Float, nullable=False)
    provisioning = Column(Enum(ProvisioningType), nullable=False)
    
    # Storage placement
    pool_id = Column(Integer, ForeignKey("storage_pools.id"), nullable=False)
    used_capacity_gb = Column(Float, default=0)
    
    # State
    state = Column(Enum(VolumeState), default=VolumeState.AVAILABLE)
    mapping_count = Column(Integer, default=0)  # Number of SDCs with access
    
    # Metrics
    current_iops = Column(Float, default=0)
    current_bandwidth_mbps = Column(Float, default=0)
    read_iops = Column(Float, default=0)
    write_iops = Column(Float, default=0)
    average_read_latency_ms = Column(Float, default=0)
    average_write_latency_ms = Column(Float, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pool = relationship("StoragePool", back_populates="volumes")
    mappings = relationship("VolumeMapping", back_populates="volume", cascade="all, delete-orphan")
    chunks = relationship("Chunk", back_populates="volume", cascade="all, delete-orphan")
    snapshots = relationship("Snapshot", back_populates="volume", cascade="all, delete-orphan")


class VolumeMapping(Base):
    """Mapping of volume to SDC - enables access control"""
    __tablename__ = "volume_mappings"
    
    id = Column(Integer, primary_key=True)
    volume_id = Column(Integer, ForeignKey("volumes.id"), nullable=False)
    sdc_id = Column(Integer, ForeignKey("sdc_clients.id"), nullable=False)
    access_mode = Column(Enum(AccessMode), default=AccessMode.READ_WRITE)
    
    mapped_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    volume = relationship("Volume", back_populates="mappings")
    sdc = relationship("SDCClient", back_populates="mapped_volumes")


class Chunk(Base):
    """Logical unit of volume data (typically 4MB)"""
    __tablename__ = "chunks"
    
    id = Column(Integer, primary_key=True)
    volume_id = Column(Integer, ForeignKey("volumes.id"), nullable=False)
    logical_offset_mb = Column(Integer, nullable=False)  # Offset in volume
    
    # State
    is_degraded = Column(Boolean, default=False)  # Not all replicas available
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    volume = relationship("Volume", back_populates="chunks")
    replicas = relationship("Replica", back_populates="chunk", cascade="all, delete-orphan")


class Replica(Base):
    """Copy of chunk data on an SDS node"""
    __tablename__ = "replicas"
    
    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("chunks.id"), nullable=False)
    sds_id = Column(Integer, ForeignKey("sds_nodes.id"), nullable=False)
    
    # State
    is_available = Column(Boolean, default=True)
    is_current = Column(Boolean, default=True)  # Latest version
    is_rebuilding = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    chunk = relationship("Chunk", back_populates="replicas")
    sds_node = relationship("SDSNode", back_populates="replicas")


class Snapshot(Base):
    """Point-in-time copy of a volume"""
    __tablename__ = "snapshots"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    volume_id = Column(Integer, ForeignKey("volumes.id"), nullable=False)
    
    # Metadata
    size_gb = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    volume = relationship("Volume", back_populates="snapshots")


class EventLog(Base):
    """System event tracking for audit and debugging"""
    __tablename__ = "event_logs"
    
    id = Column(Integer, primary_key=True)
    event_type = Column(Enum(EventType), nullable=False)
    message = Column(Text, nullable=False)
    
    # Context references
    pool_id = Column(Integer, ForeignKey("storage_pools.id"))
    volume_id = Column(Integer, ForeignKey("volumes.id"))
    sds_id = Column(Integer, ForeignKey("sds_nodes.id"))
    sdc_id = Column(Integer, ForeignKey("sdc_clients.id"))
    
    # Timing
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pool = relationship("StoragePool", foreign_keys=[pool_id])
    volume = relationship("Volume", foreign_keys=[volume_id])
    sds_node = relationship("SDSNode", foreign_keys=[sds_id])
    sdc = relationship("SDCClient", foreign_keys=[sdc_id])


class RebuildJob(Base):
    """Tracks in-progress rebuild operations"""
    __tablename__ = "rebuild_jobs"
    
    id = Column(Integer, primary_key=True)
    pool_id = Column(Integer, ForeignKey("storage_pools.id"), nullable=False)
    
    # State
    state = Column(Enum(RebuildState), default=RebuildState.IN_PROGRESS)
    progress_percent = Column(Float, default=0)
    
    # Metrics
    total_bytes_to_rebuild = Column(Float, default=0)
    bytes_rebuilt = Column(Float, default=0)
    estimated_time_remaining_seconds = Column(Integer, default=0)
    current_rebuild_rate_mbps = Column(Float, default=0)
    
    # Tracking
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    # Relationships
    pool = relationship("StoragePool", foreign_keys=[pool_id])
