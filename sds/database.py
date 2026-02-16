"""
SDS Local Database Initialization (Phase 5)

Each SDS maintains its own sds_local.db SQLite database.
This file initializes the schema and provides session management.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sds.models import Base
from pathlib import Path


def get_sds_database_url(storage_root: str = "./vm_storage/sds") -> str:
    """
    Get SQLite database URL for this SDS node.
    
    Args:
        storage_root: Root directory for this SDS's storage
    
    Returns:
        SQLite connection URL
    """
    storage_path = Path(storage_root)
    storage_path.mkdir(parents=True, exist_ok=True)
    
    db_path = storage_path / "sds_local.db"
    return f"sqlite:///{db_path}"


def create_sds_engine(storage_root: str = "./vm_storage/sds"):
    """
    Create SQLAlchemy engine for SDS local database.
    
    Args:
        storage_root: Root directory for this SDS's storage
    
    Returns:
        SQLAlchemy Engine
    """
    database_url = get_sds_database_url(storage_root)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True
    )
    return engine


def init_sds_db(storage_root: str = "./vm_storage/sds"):
    """
    Initialize SDS local database schema.
    Creates all tables if they don't exist.
    
    Args:
        storage_root: Root directory for this SDS's storage
    """
    engine = create_sds_engine(storage_root)
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Run migrations (additive only)
    inspector = inspect(engine)
    
    # Add any missing columns to existing tables (future migrations)
    # Example: if "local_replicas" in inspector.get_table_names():
    #     cols = {col["name"] for col in inspector.get_columns("local_replicas")}
    #     if "new_field" not in cols:
    #         with engine.begin() as conn:
    #             conn.execute(text("ALTER TABLE local_replicas ADD COLUMN new_field VARCHAR"))
    
    return engine


def get_sds_session_factory(storage_root: str = "./vm_storage/sds"):
    """
    Get SQLAlchemy session factory for SDS local database.
    
    Args:
        storage_root: Root directory for this SDS's storage
    
    Returns:
        scoped_session factory
    """
    engine = init_sds_db(storage_root)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return scoped_session(session_factory)


# Default session factory (can be overridden by passing storage_root)
SessionLocal = None


def init_session_factory(storage_root: str = "./vm_storage/sds"):
    """
    Initialize global session factory.
    Call this at SDS service startup with the correct storage_root.
    
    Args:
        storage_root: Root directory for this SDS's storage
    """
    global SessionLocal
    SessionLocal = get_sds_session_factory(storage_root)
    return SessionLocal


def get_db():
    """
    FastAPI dependency for database sessions.
    Usage: db: Session = Depends(get_db)
    """
    if SessionLocal is None:
        raise RuntimeError("SessionLocal not initialized. Call init_session_factory() first.")
    
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
