"""
Component Health Monitor for MGMT (Phase 9)

Background service that polls MDM health endpoints and caches data in mgmt.db.
This provides fast dashboard rendering without hammering MDM with every page load.

Monitors:
---------
- Cluster health (via /health endpoint)
- Component status (via /health/components)
- Health metrics (via /health/metrics)
- Volume stats (via /vol/list)
- Pool capacity (via /pool/list)

Architecture:
-------------
MGMT Monitor (background thread) → MDM HTTP API (poll every 10s) → Cache in mgmt.db
Dashboard UI → Read from cache → Fast page loads
"""

import requests
import threading
import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text

from mgmt.models import AlertHistory, AlertSeverity, AlertStatus, Alert
from mgmt.database import SessionLocal

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Alert model is now directly imported from models


class ComponentMonitor:
    """
    Background monitor that polls MDM for health data.
    
    Runs in a separate thread, wakes every poll_interval seconds,
    fetches health data from MDM, and caches in mgmt.db.
    """
    
    def __init__(
        self,
        mdm_base_url: str = "http://127.0.0.1:8001",
        poll_interval: int = 10,
        cache_ttl: int = 30,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize component monitor.
        
        Args:
            mdm_base_url: MDM HTTP API base URL
            poll_interval: Seconds between polls
            cache_ttl: Seconds until cached data expires
            max_retries: Maximum retry attempts for failed HTTP requests
            retry_delay: Initial delay between retries (exponential backoff)
        """
        self.mdm_base_url = mdm_base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self._running = False
        selflogger.warning("Monitor already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Monitor started (poll every {self.poll_interval}s, cache TTL {self.cache_ttl}s)")
    
    def stop(self):
        """Stop background monitoring thread."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        
        # Close HTTP session
        self._session.close()
        logger.info("Monitor loop started")
        while self._running:
            try:
                self._poll_all_endpoints()
            except Exception as e:
                logger.exception(f"xponential backoff.
        
        Args:
            url: Full URL to fetch
            timeout: Request timeout in seconds
            
        Returns:
            Response object if successful, None if all retries failed
        """
        for attempt in range(self.max_retries):
            try:
                resp = self._session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code >= 500:
                    # Server error - retry
                    logger.warning(f"HTTP {resp.status_code} from {url}, attempt {attempt + 1}/{self.max_retries}")
                else:
                    # Client error (4xx) - don't retry
                    logger.error(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
                    return None
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching {url}, attempt {attempt + 1}/{self.max_retries}")
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error fetching {url}: {e}, attempt {attempt + 1}/{self.max_retries}")
            except Exception as e:
                logger.error(f"Unexpected error fetching {url}: {e}")
                return None
            
            # Exponential backoff
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)
                time.sleep(delay)
        
        logger.error(f"All {self.max_retries} retry attempts failed for {url}")
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/health")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "health_summary", data)
                logger.debug("Polled health summary successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /health: {e}")
        elif resp:
            logger.warning(f"Health summary returned {resp.status_code}")
    
    def _poll_component_health(self, db: Session):
        """Poll /health/components for component details."""
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/health/components")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "component_health", data)
                
                # Check for component state changes and generate alerts
                self._check_component_alerts(db, data)
                logger.debug("Polled component health successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /health/components: {e}")
        elif resp:
            logger.warning(f"Component health returned {resp.status_code}")
    
    def _poll_health_metrics(self, db: Session):
        """Poll /health/metrics for cluster metrics."""
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/health/metrics")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "health_metrics", data)
                logger.debug("Polled health metrics successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /health/metrics: {e}")
        elif resp:
            logger.warning(f"Health metrics returned {resp.status_code}")
    
    def _poll_volume_list(self, db: Session):
        """Poll /vol/list for volume statistics."""
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/vol/list")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "volume_list", data)
                logger.debug("Polled volume list successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /vol/list: {e}")
        elif resp:
            logger.warning(f"Volume list returned {resp.status_cod
            db.commit()
        finally:
            db.close()
    
    def _poll_health_summary(self, db: Session):
        """Poll /health for overall cluster health."""
        try:
            resp = requests.get(f"{self.mdm_base_url}/health", timeout=5)
            if resp.status_code == 200:
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/pool/list")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "pool_list", data)
                logger.debug("Polled pool list successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /pool/list: {e}")
        elif resp:
            logger.warning(f"Pool list returned {resp.status_code}")
    
    def _poll_cluster_topology(self, db: Session):
        """Poll /discovery/topology for cluster topology."""
        resp = self._http_get_with_retry(f"{self.mdm_base_url}/discovery/topology")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                self._cache_data(db, "cluster_topology", data)
                logger.debug("Polled cluster topology successfully")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from /discovery/topology: {e}")
        elif resp:
            logger.warning(f"Topology returned {resp.status_coderror: {e}")
    
    def _poll_health_metrics(self, db: Session):
        """Poll /health/metrics for cluster metrics."""
        try:
            resp = requests.get(f"{self.mdm_base_url}/health/metrics", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self._cache_data(db, "health_metrics", data)
            else:
                print(f"[MGMT Monitor] Health metrics failed: {resp.status_code}")
        except Exception as e:
            print(f"[MGMT Monitor] Health metrics error: {e}")
    
    def _poll_volume_list(self, db: Session):
        """Poll /vol/list for volume statistics."""
        try:
            resp = requests.get(f"{self.mdm_base_url}/vol/list", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self._cache_data(db, "volume_list", data)
            else:
                print(f"[MGMT Monitor] Volume list failed: {resp.status_code}")
        except Exception as e:
            print(f"[MGMT Monitor] Volume list error: {e}")
    
    def _poll_pool_list(self, db: Session):
        """Poll /pool/list for pool capacity statistics."""
        try:
            resp = requests.get(f"{self.mdm_base_url}/pool/list", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self._cache_data(db, "pool_list", data)
            else:
                print(f"[MGMT Monitor] Pool list failed: {resp.status_code}")
        except Exception as e:
            print(f"[MGMT Monitor] Pool list error: {e}")
    
    def _poll_cluster_topology(self, db: Session):
        """Poll /discovery/topology for cluster topology."""
        try:
            resp = requests.get(f"{self.mdm_base_url}/discovery/topology", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self._cache_data(db, "cluster_topology", data)
            else:
                print(f"[MGMT Monitor] Topology failed: {resp.status_code}")
        except Exception as e:
            print(f"[MGMT Monitor] Topology error: {e}")
    
    def _cache_data(self, db: Session, cache_key: str, data: Any):
        """Store data in in-memory cache."""
        global _global_cache
        expires_at = datetime.utcnow() + timedelta(seconds=self.cache_ttl)
        _global_cache[cache_key] = {
            'data': data,
            'cached_at': datetime.utcnow(),
            'expires_at': expires_at,
        }
    
    def _check_component_alerts(self, db: Session, components: List[Dict[str, Any]]):
        """
        Check component health and generate alerts for state changes.
        
        Generates alerts when:
        - Component becomes INACTIVE
        - Component recovers to ACTIVE
        - Component misses heartbeats (stale)
        """
        for comp in components:
            comp_id = comp.get("component_id", "unknown")
            comp_type = comp.get("type", "unknown")
            status = comp.get("status", "unknown")
            is_stale = comp.get("is_stale", False)
            
            # Check for inactive component
            if status == "INACTIVE":
                alert_id = f"component_inactive_{comp_id}"
                existing = db.query(Alert).filter_by(alert_id=alert_id, resolved=False).first()
                if not existing:
                    # New alert: component went down
                    alert = Alert(
                        alert_id=alert_id,
                        severity=AlertSeverity.CRITICAL.value,
                        component_type=comp_type,
                    logger.warning(f"ALERT RAISED: {alert.title}", extra={"alert_id": alert_id, "severity": "CRITICAL"})
            
            # Check for component recovery
            elif status == "ACTIVE":
                alert_id = f"component_inactive_{comp_id}"
                existing = db.query(Alert).filter_by(alert_id=alert_id, resolved=False).first()
                if existing:
                    # Component recovered - resolve alert
                    existing.resolved = True
                    existing.resolved_at = datetime.utcnow()
                    logger.info(f"ALERT RESOLVED: Component {comp_id} recovered", extra={"alert_id": alert_id}
                alert_id = f"component_inactive_{comp_id}"
                existing = db.query(Alert).filter_by(alert_id=alert_id, resolved=False).first()
                if existing:
                    # Component recovered - resolve alert
                    existing.resolved = True
                    existing.resolved_at = datetime.utcnow()
                    print(f"[MGMT Monitor] RESOLVED: Component {comp_id} recovered")
            
            # Check for stale heartbeat warning
            if is_stale and status == "ACTIVE":
                alert_id = f"component_stale_{comp_id}"
                existing = db.query(Alert).filter_by(alert_id=alert_id, resolved=False).first()
                if not existing:
                    alert = Alert(
                        alert_id=alert_id,
                        severity=AlertSeverity.WARNING.value,
                        component_type=comp_type,
                        component_id=comp_id,
                    logger.warning(f"ALERT RAISED: {alert.title}", extra={"alert_id": alert_id, "severity": "WARNING"}_id}",
                        message=f"Component {comp_id} ({comp_type}) has a stale heartbeat (>20s old).",
                        details=comp,
                        created_at=datetime.utcnow(),
                    )
                    db.add(alert)
                    print(f"[MGMT Monitor] WARNING: {alert.title}")


# Phase 9: Simple in-memory cache (Phase 10 can add persistent cache)
_global_cache: Dict[str, Any] = {}

def get_cached_data(cache_key: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached data from in-memory cache.
    
    Returns None if cache miss or expired.
    """
    if cache_key not in _global_cache:
        return None
    
    entry = _global_cache[cache_key]
    if entry['expires_at'] < datetime.utcnow():
        return None
    
    return entry['data']


def get_all_cached_keys() -> List[str]:
    """Get list of all cache keys in in-memory cache."""
    return list(_global_cache.keys())


def clear_expired_cache():
    """Rlogger.debug(f"ries from in-memory cache."""
    now = datetime.utcnow()
    expired_keys = [k for k, v in _global_cache.items() if v['expires_at'] < now]
    for key in expired_keys:
        del _global_cache[key]
    if expired_keys:
        print(f"[MGMT Monitor] Cleared {len(expired_keys)} expired cache entries")
