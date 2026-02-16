"""
Lightweight component monitor for MGMT.

Polls key MDM endpoints in a background thread and stores an in-memory cache
for dashboard rendering.
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_cache_data: Dict[str, Any] = {}
_cache_ts: Dict[str, datetime] = {}


def get_cached_data(key: str) -> Optional[Any]:
    with _cache_lock:
        return _cache_data.get(key)


def get_all_cached_keys() -> Dict[str, str]:
    with _cache_lock:
        return {k: v.isoformat() for k, v in _cache_ts.items()}


class ComponentMonitor:
    def __init__(
        self,
        mdm_base_url: str = "http://127.0.0.1:8001",
        poll_interval: int = 10,
        cache_ttl: int = 30,
        max_retries: int = 2,
        retry_delay: float = 1.0,
    ):
        self.mdm_base_url = mdm_base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._session = requests.Session()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("MGMT monitor started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._session.close()
        logger.info("MGMT monitor stopped")

    def _monitor_loop(self):
        while self._running:
            try:
                self._poll_all()
            except Exception as exc:
                logger.warning("Monitor poll failed: %s", exc)
            time.sleep(self.poll_interval)

    def _http_get(self, path: str) -> Optional[Any]:
        url = f"{self.mdm_base_url}{path}"
        for attempt in range(self.max_retries):
            try:
                response = self._session.get(url, timeout=5)
                if response.status_code == 200:
                    return response.json()
            except Exception:
                pass
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)
        return None

    def _put_cache(self, key: str, data: Any):
        with _cache_lock:
            _cache_data[key] = data
            _cache_ts[key] = datetime.utcnow()

    def _poll_all(self):
        health = self._http_get("/health")
        if health is not None:
            self._put_cache("health_summary", health)

        components = self._http_get("/health/components")
        if components is not None:
            self._put_cache("component_health", components)

        metrics = self._http_get("/health/metrics")
        if metrics is not None:
            self._put_cache("health_metrics", metrics)

        pools = self._http_get("/pool/list")
        if pools is not None:
            self._put_cache("pool_list", pools)

        volumes = self._http_get("/vol/list")
        if volumes is not None:
            self._put_cache("volume_list", volumes)

        topology = self._http_get("/discovery/topology")
        if topology is not None:
            self._put_cache("cluster_topology", topology)
