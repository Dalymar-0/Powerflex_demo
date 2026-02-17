"""
MGMT Database Initialization (Phase 3)

Manages the MGMT-specific database (mgmt.db) — completely separate from MDM's powerflex.db.
This database is owned exclusively by the MGMT component.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from mgmt.models import Base, User, UserRole, MGMTConfig, AlertRule, AlertSeverity
import bcrypt
import logging

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = (Path(__file__).resolve().parent / "data" / "mgmt.db")
os.makedirs(_DEFAULT_DB_PATH.parent, exist_ok=True)
DATABASE_URL = str(os.getenv("POWERFLEX_MGMT_DB_URL", f"sqlite:///{_DEFAULT_DB_PATH.as_posix()}"))

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


def init_db():
    """
    Initialize mgmt.db database with schema and seed data.
    Creates all tables and adds default admin user + alert rules.
    """
    logger.info("Initializing MGMT database (mgmt.db)...")
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("MGMT database schema created")
    
    # Run migrations (additive only)
    _run_migrations()
    
    # Seed default data
    _seed_default_data()
    
    logger.info("MGMT database initialization complete")


def _run_migrations():
    """
    Run additive migrations for mgmt.db.
    Only adds new columns/tables, never drops existing data.
    """
    inspector = inspect(engine)
    
    # Phase 3 migrations (none yet, but placeholder for future)
    # Example:
    # if "users" in inspector.get_table_names():
    #     user_cols = {col["name"] for col in inspector.get_columns("users")}
    #     if "new_column" not in user_cols:
    #         with engine.begin() as conn:
    #             conn.execute(text("ALTER TABLE users ADD COLUMN new_column VARCHAR"))
    
    pass


def _seed_default_data():
    """Seed default users, config, and alert rules if not exists"""
    db = SessionLocal()
    
    try:
        # Create default admin user if no users exist
        user_count = db.query(User).count()
        if user_count == 0:
            admin_password = "admin123"  # Default password (should be changed on first login)
            password_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
            
            admin_user = User(
                username="admin",
                password_hash=password_hash,
                email="admin@powerflex.local",
                full_name="System Administrator",
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin_user)
            logger.info("Created default admin user (username: admin, password: admin123)")
        
        # Seed MGMT config
        config_count = db.query(MGMTConfig).filter(MGMTConfig.key == "mdm_url").count()
        if config_count == 0:
            mdm_config = MGMTConfig(
                key="mdm_url",
                value="http://127.0.0.1:8001",
                description="MDM API base URL for control-plane operations"
            )
            db.add(mdm_config)
            logger.info("Seeded default MDM URL config")
        
        refresh_config = db.query(MGMTConfig).filter(MGMTConfig.key == "topology_refresh_seconds").count()
        if refresh_config == 0:
            refresh = MGMTConfig(
                key="topology_refresh_seconds",
                value="30",
                description="How often to refresh topology cache from MDM discovery"
            )
            db.add(refresh)
        
        monitor_config = db.query(MGMTConfig).filter(MGMTConfig.key == "monitoring_poll_seconds").count()
        if monitor_config == 0:
            monitor = MGMTConfig(
                key="monitoring_poll_seconds",
                value="15",
                description="How often to poll component mgmt ports for metrics"
            )
            db.add(monitor)
        
        # Seed default alert rules
        alert_rules = [
            {
                "name": "SDS Heartbeat Missed",
                "description": "SDS node hasn't sent heartbeat in over 60 seconds",
                "component_type": "SDS",
                "metric_name": "heartbeat_age_seconds",
                "threshold_value": 60.0,
                "threshold_operator": ">",
                "severity": AlertSeverity.CRITICAL,
                "check_interval_seconds": 30,
                "consecutive_failures_required": 2
            },
            {
                "name": "SDC Heartbeat Missed",
                "description": "SDC client hasn't sent heartbeat in over 60 seconds",
                "component_type": "SDC",
                "metric_name": "heartbeat_age_seconds",
                "threshold_value": 60.0,
                "threshold_operator": ">",
                "severity": AlertSeverity.ERROR,
                "check_interval_seconds": 30,
                "consecutive_failures_required": 2
            },
            {
                "name": "Pool Capacity Warning",
                "description": "Storage pool is over 80% full",
                "component_type": "POOL",
                "metric_name": "capacity_used_percent",
                "threshold_value": 80.0,
                "threshold_operator": ">",
                "severity": AlertSeverity.WARNING,
                "check_interval_seconds": 60,
                "consecutive_failures_required": 1
            },
            {
                "name": "Pool Capacity Critical",
                "description": "Storage pool is over 95% full",
                "component_type": "POOL",
                "metric_name": "capacity_used_percent",
                "threshold_value": 95.0,
                "threshold_operator": ">",
                "severity": AlertSeverity.CRITICAL,
                "check_interval_seconds": 60,
                "consecutive_failures_required": 1
            },
            {
                "name": "High IO Error Rate",
                "description": "Volume IO error rate exceeds 1%",
                "component_type": "VOLUME",
                "metric_name": "io_error_rate_percent",
                "threshold_value": 1.0,
                "threshold_operator": ">",
                "severity": AlertSeverity.ERROR,
                "check_interval_seconds": 60,
                "consecutive_failures_required": 3
            }
        ]
        
        for rule_data in alert_rules:
            existing = db.query(AlertRule).filter(AlertRule.name == rule_data["name"]).first()
            if not existing:
                rule = AlertRule(**rule_data)
                db.add(rule)
                logger.info(f"Seeded alert rule: {rule_data['name']}")
        
        db.commit()
        logger.info("Default data seeding complete")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to seed default data: {e}")
        raise
    finally:
        db.close()


def get_db():
    """FastAPI/Flask dependency for database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_db():
    """
    Drop all tables and recreate (DESTRUCTIVE - dev/test only).
    Never use in production - this deletes all MGMT data including users and audit logs.
    """
    logger.warning("Resetting MGMT database - all data will be lost!")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_default_data()
    logger.info("MGMT database reset complete")
