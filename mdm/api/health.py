"""
MDM Health API - Phase 7

Health check and monitoring endpoints for MGMT dashboard.
Aggregates cluster health status from component heartbeats.

Endpoints:
- GET /health: Overall cluster health summary
- GET /health/components: Detailed component status
- GET /health/metrics: Health metrics over time
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# Will be injected by service.py
_health_monitor = None

def set_health_monitor(monitor):
    """Set health monitor reference (called by service.py)"""
    global _health_monitor
    _health_monitor = monitor


class HealthSummary(BaseModel):
    """Overall cluster health summary"""
    status: str  # 'healthy', 'warning', 'degraded', 'critical'
    health_score: int  # 0-100
    timestamp: str
    components: Dict[str, int]  # total, active, inactive
    by_type: Dict[str, Dict[str, int]]
    heartbeat_timeout_seconds: int


class ComponentStatus(BaseModel):
    """Individual component status"""
    component_id: str
    component_type: str
    address: str
    status: str
    registered_at: str
    last_heartbeat_at: str
    seconds_since_heartbeat: float
    is_stale: bool
    control_port: int | None = None  # Optional, not all components have all ports
    data_port: int | None = None
    mgmt_port: int | None = None


@router.get("/", response_model=HealthSummary)
def get_health_summary():
    """
    Get overall cluster health summary.
    Used by MGMT dashboard for health indicators.
    """
    if _health_monitor is None:
        return {
            "status": "unknown",
            "health_score": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {"total": 0, "active": 0, "inactive": 0},
            "by_type": {},
            "heartbeat_timeout_seconds": 30
        }
    
    return _health_monitor.get_health_summary()


@router.get("/components", response_model=List[ComponentStatus])
def get_component_statuses():
    """
    Get detailed status of all registered components.
    Shows last heartbeat time, staleness, and ports.
    """
    if _health_monitor is None:
        return []
    
    return _health_monitor.get_component_details()


@router.get("/metrics")
def get_health_metrics() -> Dict[str, Any]:
    """
    Get health metrics for monitoring.
    Includes component counts, availability percentage, stale components.
    """
    if _health_monitor is None:
        return {
            "error": "Health monitor not initialized",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    summary = _health_monitor.get_health_summary()
    details = _health_monitor.get_component_details()
    
    # Calculate additional metrics
    stale_components = [c for c in details if c["is_stale"]]
    avg_heartbeat_age = sum(c["seconds_since_heartbeat"] for c in details) / len(details) if details else 0
    
    return {
        "health_score": summary["health_score"],
        "total_components": summary["components"]["total"],
        "active_components": summary["components"]["active"],
        "inactive_components": summary["components"]["inactive"],
        "stale_components": len(stale_components),
        "availability_percentage": summary["health_score"],
        "avg_heartbeat_age_seconds": round(avg_heartbeat_age, 1),
        "by_type": summary["by_type"],
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/status/{component_id}")
def get_component_status(component_id: str) -> Dict[str, Any]:
    """
    Get status of specific component by ID.
    """
    if _health_monitor is None:
        return {"error": "Health monitor not initialized"}
    
    details = _health_monitor.get_component_details()
    
    for component in details:
        if component["component_id"] == component_id:
            return component
    
    return {"error": f"Component {component_id} not found"}
