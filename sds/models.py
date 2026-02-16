"""
SDS Local Database Models (Phase 5)

Each SDS maintains its own local SQLite database (sds_local.db) tracking:
- local_replicas: Chunks stored on this SDS node
- local_devices: Physical devices/disks attached to this SDS
- write_journal: Recent write operations for crash recovery
- consumed_tokens: IO tokens already processed (prevent replay)
- ack_queue: Pending transaction ACKs to send to MDM

This DB is NEVER shared between SDS nodes.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class LocalReplica(Base):
    """
    Chunks stored on this SDS node.
    Tracks local file path, size, checksum, and sync status.
    """
    __tablename__ = "local_replicas"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # MDM identifiers (from central powerflex.db)
    chunk_id = Column(Integer, nullable=False, unique=True, index=True)
    volume_id = Column(Integer, nullable=False, index=True)
    
    # Local storage
    local_file_path = Column(String, nullable=False)  # e.g., "./vm_storage/sds1/vol_42_chunk_0.img"
    size_bytes = Column(Integer, nullable=False)
    
    # Data integrity
    checksum = Column(String)  # SHA256 hex digest
    generation = Column(Integer, default=0)  # Incremented on every write
    
    # Sync status
    status = Column(String, default="ACTIVE")  # ACTIVE, DEGRADED, REBUILDING, MISSING
    last_write_at = Column(DateTime)
    last_verified_at = Column(DateTime)  # Last checksum verification
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_local_replicas_volume", "volume_id"),
        Index("idx_local_replicas_status", "status"),
    )


class LocalDevice(Base):
    """
    Physical devices attached to this SDS node.
    Maps device names to local paths and tracks capacity/health.
    """
    __tablename__ = "local_devices"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Device identification
    device_name = Column(String, nullable=False, unique=True, index=True)  # e.g., "blk0", "blk1"
    device_path = Column(String, nullable=False)  # e.g., "./vm_storage/sds1/devices/blk0"
    
    # Capacity
    total_capacity_gb = Column(Float, nullable=False)
    used_capacity_gb = Column(Float, default=0.0)
    
    # Health
    status = Column(String, default="ONLINE")  # ONLINE, DEGRADED, FAILED, MAINTENANCE
    error_count = Column(Integer, default=0)
    last_error_at = Column(DateTime)
    last_error_message = Column(Text)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WriteJournal(Base):
    """
    Write-ahead log for crash recovery.
    Records write operations before they complete.
    """
    __tablename__ = "write_journal"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Transaction identification
    token_id = Column(String, nullable=False, index=True)  # IO authorization token
    chunk_id = Column(Integer, nullable=False, index=True)
    
    # Operation details
    operation = Column(String, nullable=False)  # "write", "replicate"
    offset_bytes = Column(Integer, nullable=False)
    length_bytes = Column(Integer, nullable=False)
    
    # Status tracking
    status = Column(String, default="PENDING")  # PENDING, COMMITTED, ABORTED
    committed_at = Column(DateTime)
    
    # Metadata
    checksum = Column(String)  # Expected checksum after write
    generation_before = Column(Integer)
    generation_after = Column(Integer)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    
    __table_args__ = (
        Index("idx_write_journal_status_created", "status", "created_at"),
    )


class ConsumedToken(Base):
    """
    Tokens already processed by this SDS.
    Prevents replay attacks and duplicate IO execution.
    """
    __tablename__ = "consumed_tokens"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Token identification
    token_id = Column(String, nullable=False, unique=True, index=True)
    volume_id = Column(Integer, nullable=False)
    chunk_id = Column(Integer, nullable=False)
    
    # Operation details
    operation = Column(String, nullable=False)  # "read", "write"
    offset_bytes = Column(Integer, nullable=False)
    length_bytes = Column(Integer, nullable=False)
    
    # Execution result
    success = Column(Boolean, nullable=False)
    bytes_processed = Column(Integer, default=0)
    execution_duration_ms = Column(Float)
    error_message = Column(Text)
    
    # Timestamps
    consumed_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index("idx_consumed_tokens_consumed_at", "consumed_at"),
    )


class AckQueue(Base):
    """
    Pending transaction ACKs to send to MDM.
    Batched and sent asynchronously every few seconds.
    """
    __tablename__ = "ack_queue"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Transaction identification
    token_id = Column(String, nullable=False, index=True)
    chunk_id = Column(Integer, nullable=False)
    
    # Execution result
    success = Column(Boolean, nullable=False)
    bytes_processed = Column(Integer, default=0)
    execution_duration_ms = Column(Float)
    error_message = Column(Text)
    
    # ACK status
    ack_status = Column(String, default="PENDING")  # PENDING, SENT, CONFIRMED, FAILED
    retry_count = Column(Integer, default=0)
    last_retry_at = Column(DateTime)
    
    # Metadata
    checksum = Column(String)
    generation = Column(Integer)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    
    __table_args__ = (
        Index("idx_ack_queue_status_created", "ack_status", "created_at"),
    )


class SDSMetadata(Base):
    """
    SDS node metadata and configuration.
    Single-row table with node-specific settings.
    """
    __tablename__ = "sds_metadata"
    
    id = Column(Integer, primary_key=True, default=1)  # Always 1 (singleton)
    
    # Node identification
    sds_id = Column(Integer)  # ID from MDM's powerflex.db sds_nodes table
    component_id = Column(String)  # Discovery component_id (e.g., "sds-10.0.1.10")
    cluster_secret = Column(String)  # Shared secret for token verification
    
    # Network configuration
    address = Column(String)
    data_port = Column(Integer)
    control_port = Column(Integer)
    mgmt_port = Column(Integer)
    
    # MDM connection
    mdm_url = Column(String)  # e.g., "http://10.0.1.1:8001"
    last_heartbeat_sent_at = Column(DateTime)
    last_ack_batch_sent_at = Column(DateTime)
    
    # Statistics
    total_io_operations = Column(Integer, default=0)
    total_bytes_read = Column(Integer, default=0)
    total_bytes_written = Column(Integer, default=0)
    total_errors = Column(Integer, default=0)
    
    # Timestamps
    initialized_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
