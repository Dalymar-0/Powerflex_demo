"""
SDC Local Database Models - Phase 6

Local SQLite database (sdc_local.db) for SDC-specific state.
Separate from central powerflex.db (MDM-owned) and sds_local.db.

Tables:
- chunk_locations: Cached chunk→SDS mappings from MDM plans
- token_cache: Recently used IO tokens (for replay prevention)
- volume_mappings_cache: Local copy of mapped volumes
- pending_ios: In-flight IO operations (for crash recovery)
- device_registry: NBD device→volume mappings
"""

from sqlalchemy import Column, Integer, String, DateTime, Float, create_engine
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class ChunkLocation(Base):
    """
    Cached chunk location from MDM IO plans.
    Avoids repeated MDM queries for chunk→SDS mapping.
    """
    __tablename__ = "chunk_locations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    volume_id = Column(Integer, nullable=False, index=True)
    chunk_id = Column(Integer, nullable=False, index=True)
    sds_address = Column(String, nullable=False)
    sds_data_port = Column(Integer, nullable=False)
    generation = Column(Integer, default=0)  # Invalidate on rebuild
    cached_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, default=datetime.utcnow)


class TokenCache(Base):
    """
    Cache of recently used tokens (for replay detection).
    Tokens are single-use; cache tracks consumed tokens.
    """
    __tablename__ = "token_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    token_id = Column(String, unique=True, nullable=False, index=True)
    volume_id = Column(Integer, nullable=False)
    operation = Column(String, nullable=False)  # 'READ', 'WRITE'
    offset_bytes = Column(Integer, nullable=False)
    length_bytes = Column(Integer, nullable=False)
    issued_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class VolumeMappingCache(Base):
    """
    Local cache of volume mappings (this SDC's mapped volumes).
    Reduces MDM queries for mapping validation.
    """
    __tablename__ = "volume_mappings_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    volume_id = Column(Integer, nullable=False, unique=True, index=True)
    volume_name = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    access_mode = Column(String, nullable=False)  # 'readOnly', 'readWrite'
    mapped_at = Column(DateTime, default=datetime.utcnow)
    last_io_at = Column(DateTime, nullable=True)
    io_count = Column(Integer, default=0)


class PendingIO(Base):
    """
    Track in-flight IO operations for crash recovery.
    Cleared on successful completion, replayed on restart.
    """
    __tablename__ = "pending_ios"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    volume_id = Column(Integer, nullable=False, index=True)
    operation = Column(String, nullable=False)  # 'READ', 'WRITE'
    offset_bytes = Column(Integer, nullable=False)
    length_bytes = Column(Integer, nullable=False)
    token_id = Column(String, nullable=True)
    status = Column(String, default="PENDING")  # PENDING, IN_PROGRESS, FAILED
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)


class DeviceRegistry(Base):
    """
    NBD device registry: tracks which volumes are exposed as devices.
    Maps device paths (naa.60000000...) to volume IDs.
    """
    __tablename__ = "device_registry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_path = Column(String, unique=True, nullable=False, index=True)  # e.g., 'naa.60000000abcd1234'
    volume_id = Column(Integer, nullable=False, index=True)
    volume_name = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    port = Column(Integer, nullable=False)  # NBD server port (8005+n)
    status = Column(String, default="ACTIVE")  # ACTIVE, DETACHED
    mounted_at = Column(DateTime, default=datetime.utcnow)
    last_access_at = Column(DateTime, default=datetime.utcnow)
    total_reads = Column(Integer, default=0)
    total_writes = Column(Integer, default=0)
    total_bytes_read = Column(Integer, default=0)
    total_bytes_written = Column(Integer, default=0)
