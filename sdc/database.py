"""
SDC Local Database Initialization - Phase 6

Manages sdc_local.db (SQLite) for SDC-specific state.
Each SDC instance has its own database file.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool
import logging
from pathlib import Path

from sdc.models import Base

logger = logging.getLogger(__name__)


def get_sdc_db_path(sdc_id: str) -> Path:
    """Get database path for this SDC instance"""
    storage_root = Path("vm_storage/sdc")
    storage_root.mkdir(parents=True, exist_ok=True)
    return storage_root / f"sdc_{sdc_id}_local.db"


def init_sdc_database(sdc_id: str) -> tuple:
    """
    Initialize SDC local database and return engine + session factory.
    
    Returns:
        (engine, SessionLocal) tuple
    """
    db_path = get_sdc_db_path(sdc_id)
    db_url = f"sqlite:///{db_path}"
    
    logger.info(f"Initializing SDC database at {db_path}")
    
    # Create engine with thread safety for multi-threaded SDC service
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create scoped session factory
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    SessionLocal = scoped_session(session_factory)
    
    logger.info(f"SDC database initialized with {len(Base.metadata.tables)} tables")
    
    return engine, SessionLocal


def cleanup_stale_data(SessionLocal, max_age_hours: int = 24):
    """
    Clean up stale cached data (chunk locations, tokens).
    Called periodically by SDC service.
    """
    from datetime import datetime, timedelta
    from sdc.models import ChunkLocation, TokenCache
    
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        # Clean old chunk location cache
        deleted_chunks = db.query(ChunkLocation).filter(
            ChunkLocation.last_used_at < cutoff
        ).delete()
        
        # Clean expired tokens
        deleted_tokens = db.query(TokenCache).filter(
            TokenCache.expires_at < datetime.utcnow()
        ).delete()
        
        db.commit()
        
        if deleted_chunks > 0 or deleted_tokens > 0:
            logger.info(f"Cleaned {deleted_chunks} chunk cache entries, {deleted_tokens} expired tokens")
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()
