"""
MGMT Database Models (Phase 3)

MGMT has its OWN database (mgmt.db) separate from MDM's powerflex.db.
This database stores:
- User accounts and authentication
- Session management
- Alert rules and history
- Monitoring snapshots (polled from component mgmt ports)
- Audit logs
- Cached topology data

MGMT never writes to powerflex.db — it only reads via MDM API.
"""

from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import enum

Base = declarative_base()


# ============================================================================
# ENUM DEFINITIONS
# ============================================================================

class UserRole(str, enum.Enum):
    """User role for RBAC"""
    ADMIN = "admin"  # Full access (create/delete volumes, manage users)
    OPERATOR = "operator"  # Control-plane access (create/map volumes, view health)
    VIEWER = "viewer"  # Read-only (view dashboard, no modifications)


class AlertSeverity(str, enum.Enum):
    """Alert severity level"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    """Alert lifecycle status"""
    ACTIVE = "active"  # Currently firing
    ACKNOWLEDGED = "acknowledged"  # User acknowledged but not resolved
    RESOLVED = "resolved"  # Condition cleared
    SUPPRESSED = "suppressed"  # Manually suppressed by user


class ComponentHealth(str, enum.Enum):
    """Component health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class AuditEventType(str, enum.Enum):
    """Audit log event types"""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_CREATED = "user_created"
    USER_DELETED = "user_deleted"
    VOLUME_CREATED = "volume_created"
    VOLUME_DELETED = "volume_deleted"
    VOLUME_MAPPED = "volume_mapped"
    VOLUME_UNMAPPED = "volume_unmapped"
    SDS_ADDED = "sds_added"
    SDS_REMOVED = "sds_removed"
    POOL_CREATED = "pool_created"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    ALERT_SUPPRESSED = "alert_suppressed"
    CONFIG_CHANGED = "config_changed"


# ============================================================================
# CORE MODEL DEFINITIONS
# ============================================================================

class User(Base):
    """User accounts for MGMT GUI authentication"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # bcrypt hash
    email = Column(String)
    full_name = Column(String)
    
    # RBAC
    role = Column(Enum(UserRole), default=UserRole.VIEWER)
    is_active = Column(Boolean, default=True)
    
    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)
    failed_login_attempts = Column(Integer, default=0)
    
    # Relationships
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", foreign_keys="AuditLog.user_id")


class Session(Base):
    """User session tracking for GUI login"""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String, unique=True, nullable=False, index=True)  # Random token
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Session metadata
    ip_address = Column(String)
    user_agent = Column(String)
    
    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_activity_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")


class Alert(Base):
    """Simple alert model for component monitoring (used by ComponentMonitor)"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    alert_id = Column(String, unique=True, nullable=False, index=True)  # Unique identifier like "component_inactive_sds-1"
    
    # Alert details
    severity = Column(String, nullable=False)  # 'info', 'warning', 'error', 'critical'
    component_type = Column(String)  # 'SDS', 'SDC', 'MDM', 'POOL', 'VOLUME'
    component_id = Column(String)  # Component identifier
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    
    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    
    # Metadata
    details = Column(JSON)  # JSON blob with additional context


class AlertRule(Base):
    """Alert threshold configuration"""
    __tablename__ = "alert_rules"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    
    # Rule definition
    component_type = Column(String)  # 'SDS', 'SDC', 'POOL', 'VOLUME', 'CLUSTER'
    metric_name = Column(String, nullable=False)  # 'heartbeat_missed', 'capacity_percent', 'io_error_rate'
    threshold_value = Column(Float, nullable=False)
    threshold_operator = Column(String, nullable=False)  # '>', '<', '>=', '<=', '=='
    
    # Alert behavior
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.WARNING)
    check_interval_seconds = Column(Integer, default=60)
    consecutive_failures_required = Column(Integer, default=1)
    
    # State
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    alert_history = relationship("AlertHistory", back_populates="rule", cascade="all, delete-orphan")


class AlertHistory(Base):
    """Alert firing history"""
    __tablename__ = "alert_history"
    
    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=False)
    
    # Alert instance
    component_id = Column(String)  # e.g., 'sds-10.0.1.10', 'pool-1', 'volume-42'
    status = Column(Enum(AlertStatus), default=AlertStatus.ACTIVE)
    severity = Column(Enum(AlertSeverity), nullable=False)
    
    # Details
    message = Column(Text, nullable=False)
    metric_value = Column(Float)
    threshold_value = Column(Float)
    
    # Lifecycle
    fired_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime)
    acknowledged_by_user_id = Column(Integer, ForeignKey("users.id"))
    resolved_at = Column(DateTime)
    
    # Metadata
    details_json = Column(Text)  # JSON blob with additional context
    
    # Relationships
    rule = relationship("AlertRule", back_populates="alert_history")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])


class MonitoringSnapshot(Base):
    """Periodic snapshots from component mgmt ports"""
    __tablename__ = "monitoring_snapshots"
    
    id = Column(Integer, primary_key=True)
    component_id = Column(String, nullable=False, index=True)
    component_type = Column(String, nullable=False)  # 'MDM', 'SDS', 'SDC'
    
    # Health
    health = Column(Enum(ComponentHealth), default=ComponentHealth.UNKNOWN)
    
    # Metrics (JSON blob)
    metrics_json = Column(Text, nullable=False)  # e.g., {"io_ops_per_sec": 1234, "capacity_used_gb": 256}
    
    # Timing
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Retention
    # Old snapshots should be purged periodically (keep last 7 days)


class AuditLog(Base):
    """Audit trail for user actions"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    event_type = Column(Enum(AuditEventType), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Context
    resource_type = Column(String)  # 'volume', 'pool', 'sds', 'user', 'alert'
    resource_id = Column(String)
    
    # Details
    message = Column(Text, nullable=False)
    details_json = Column(Text)  # JSON blob with extra context
    
    # Metadata
    ip_address = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs", foreign_keys=[user_id])


class TopologyCache(Base):
    """Cached topology from MDM discovery (refreshed periodically)"""
    __tablename__ = "topology_cache"
    
    id = Column(Integer, primary_key=True)
    component_id = Column(String, unique=True, nullable=False)
    component_type = Column(String, nullable=False)
    
    # Addressing
    address = Column(String, nullable=False)
    control_port = Column(Integer)
    data_port = Column(Integer)
    mgmt_port = Column(Integer)
    
    # Status
    status = Column(String)
    last_heartbeat_at = Column(DateTime)
    
    # Metadata
    metadata_json = Column(Text)
    
    # Cache metadata
    cached_at = Column(DateTime, default=datetime.utcnow)
    refreshed_at = Column(DateTime, default=datetime.utcnow)


class MGMTConfig(Base):
    """MGMT-specific configuration"""
    __tablename__ = "mgmt_config"
    
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
