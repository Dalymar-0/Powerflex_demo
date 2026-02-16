"""
MDM Health Monitor - Phase 7

Background service that monitors component health via heartbeat tracking.
Detects failed/stale components and generates alerts.

Key responsibilities:
- Monitor all registered components (SDS, SDC, MGMT)
- Mark components INACTIVE if no heartbeat within threshold
- Track component uptime and availability
- Generate health reports for MGMT dashboard
- Detect and alert on component failures

Runs in background thread, checks every 10 seconds.
"""

import threading
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select

from mdm.models import ComponentRegistry, ClusterConfig

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitor component health via heartbeat tracking.
    Runs in background thread.
    """
    
    def __init__(self, session_factory, check_interval_seconds: int = 10, heartbeat_timeout_seconds: int = 30):
        """
        Initialize health monitor.
        
        Args:
            session_factory: SQLAlchemy session factory
            check_interval_seconds: How often to check component health (default 10s)
            heartbeat_timeout_seconds: Mark INACTIVE after this many seconds without heartbeat (default 30s)
        """
        self.session_factory = session_factory
        self.check_interval = check_interval_seconds
        self.heartbeat_timeout = heartbeat_timeout_seconds
        
        self.running = False
        self.monitor_thread: threading.Thread = None
        
        logger.info(f"Health monitor initialized: check_interval={check_interval_seconds}s, timeout={heartbeat_timeout_seconds}s")
    
    def start(self):
        """Start health monitor in background thread"""
        if self.running:
            logger.warning("Health monitor already running")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info("Health monitor started")
    
    def stop(self):
        """Stop health monitor"""
        if not self.running:
            return
        
        self.running = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        logger.info("Health monitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop (runs in background thread)"""
        while self.running:
            try:
                self._check_component_health()
            except Exception as e:
                logger.error(f"Health check error: {e}", exc_info=True)
            
            # Wait before next check
            time.sleep(self.check_interval)
    
    def _check_component_health(self):
        """Check all registered components for heartbeat timeout"""
        db = self.session_factory()
        try:
            now = datetime.utcnow()
            timeout_threshold = now - timedelta(seconds=self.heartbeat_timeout)
            
            # Get all registered components
            components = db.scalars(select(ComponentRegistry)).all()
            
            inactive_count = 0
            recovered_count = 0
            
            for component in components:
                last_heartbeat = component.last_heartbeat_at  # type: ignore[attr-defined]
                current_status = component.status  # type: ignore[attr-defined]
                component_id = component.component_id  # type: ignore[attr-defined]
                
                # Check if heartbeat is stale
                if last_heartbeat < timeout_threshold:
                    if current_status == "ACTIVE":
                        # Mark as INACTIVE
                        component.status = "INACTIVE"  # type: ignore[assignment]
                        db.commit()
                        
                        time_since_last = (now - last_heartbeat).total_seconds()
                        logger.warning(f"Component {component_id} marked INACTIVE (no heartbeat for {time_since_last:.1f}s)")
                        
                        inactive_count += 1
                        
                        # Generate alert (Phase 9 will implement alert storage)
                        self._generate_alert(db, component_id, "COMPONENT_INACTIVE", 
                                            f"No heartbeat for {time_since_last:.1f}s")
                
                else:
                    # Heartbeat is recent
                    if current_status == "INACTIVE":
                        # Component recovered
                        component.status = "ACTIVE"  # type: ignore[assignment]
                        db.commit()
                        
                        logger.info(f"Component {component_id} recovered (status → ACTIVE)")
                        recovered_count += 1
                        
                        self._generate_alert(db, component_id, "COMPONENT_RECOVERED", "Component is back online")
            
            if inactive_count > 0 or recovered_count > 0:
                logger.info(f"Health check: {inactive_count} components marked INACTIVE, {recovered_count} recovered")
        
        finally:
            db.close()
    
    def _generate_alert(self, db: Session, component_id: str, alert_type: str, message: str):
        """
        Generate alert for component health change.
        
        For Phase 7, this just logs. Phase 9 will add alert storage in mgmt.db.
        """
        logger.warning(f"ALERT [{alert_type}] {component_id}: {message}")
        
        # TODO Phase 9: Store alert in mgmt.db for dashboard display
    
    def get_health_summary(self) -> Dict[str, Any]:
        """
        Get cluster health summary for MGMT monitoring.
        
        Returns:
            Dict with component counts, statuses, and health score
        """
        db = self.session_factory()
        try:
            components = db.scalars(select(ComponentRegistry)).all()
            
            total_count = len(components)
            active_count = sum(1 for c in components if c.status == "ACTIVE")  # type: ignore[attr-defined]
            inactive_count = total_count - active_count
            
            # Count by type
            by_type = {}
            for component in components:
                comp_type = component.component_type  # type: ignore[attr-defined]
                if comp_type not in by_type:
                    by_type[comp_type] = {"total": 0, "active": 0, "inactive": 0}
                
                by_type[comp_type]["total"] += 1
                if component.status == "ACTIVE":  # type: ignore[attr-defined]
                    by_type[comp_type]["active"] += 1
                else:
                    by_type[comp_type]["inactive"] += 1
            
            # Calculate health score (0-100)
            health_score = int((active_count / total_count * 100)) if total_count > 0 else 100
            
            # Determine overall status
            if inactive_count == 0:
                overall_status = "healthy"
            elif active_count == 0:
                overall_status = "critical"
            elif inactive_count / total_count > 0.5:
                overall_status = "degraded"
            else:
                overall_status = "warning"
            
            return {
                "status": overall_status,
                "health_score": health_score,
                "timestamp": datetime.utcnow().isoformat(),
                "components": {
                    "total": total_count,
                    "active": active_count,
                    "inactive": inactive_count
                },
                "by_type": by_type,
                "heartbeat_timeout_seconds": self.heartbeat_timeout
            }
        
        finally:
            db.close()
    
    def get_component_details(self) -> List[Dict[str, Any]]:
        """
        Get detailed status of all components.
        
        Returns:
            List of component status dicts with uptime, last heartbeat, etc.
        """
        db = self.session_factory()
        try:
            components = db.scalars(select(ComponentRegistry)).all()
            now = datetime.utcnow()
            
            result = []
            for component in components:
                last_heartbeat = component.last_heartbeat_at  # type: ignore[attr-defined]
                time_since_heartbeat = (now - last_heartbeat).total_seconds()
                
                result.append({
                    "component_id": component.component_id,  # type: ignore[attr-defined]
                    "component_type": component.component_type,  # type: ignore[attr-defined]
                    "address": component.address,  # type: ignore[attr-defined]
                    "status": component.status,  # type: ignore[attr-defined]
                    "registered_at": component.registered_at.isoformat(),  # type: ignore[attr-defined]
                    "last_heartbeat_at": last_heartbeat.isoformat(),
                    "seconds_since_heartbeat": round(time_since_heartbeat, 1),
                    "is_stale": time_since_heartbeat > self.heartbeat_timeout,
                    "control_port": component.control_port,  # type: ignore[attr-defined]
                    "data_port": component.data_port,  # type: ignore[attr-defined]
                    "mgmt_port": component.mgmt_port  # type: ignore[attr-defined]
                })
            
            return result
        
        finally:
            db.close()
