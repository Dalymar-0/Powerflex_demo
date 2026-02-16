"""
SDC Service Launcher - Phase 6

Multi-threaded SDC service that runs:
1. NBD server (port 8005) - Block device protocol for VM/app access
2. Control API (port 8003) - FastAPI control plane
3. Management API (port 8004) - FastAPI management plane
4. Heartbeat sender - Periodic heartbeat to MDM discovery

Per REFORM_PLAN.md Phase 6, this implements the full SDC multi-listener pattern.

Usage:
    from sdc.service import SDCService
    
    service = SDCService(
        sdc_id=1,
        sdc_component_id="sdc-10.0.1.20",
        listen_address="127.0.0.1",
        nbd_port=8005,
        control_port=8003,
        mgmt_port=8004,
        mdm_address="127.0.0.1",
        mdm_port=8001
    )
    
    service.start()
    # ... service runs in background threads ...
    service.stop()
"""

import threading
import time
import logging
import requests
from typing import Optional
from datetime import datetime
from fastapi import FastAPI
import uvicorn

from sdc.database import init_sdc_database, cleanup_stale_data
from sdc.nbd_server import NBDServer
from sdc import control_app, mgmt_app

logger = logging.getLogger(__name__)


class SDCService:
    """
    Multi-threaded SDC service orchestrator.
    Manages all SDC components and their lifecycles.
    """
    
    def __init__(
        self,
        sdc_id: int,
        sdc_component_id: str,
        listen_address: str,
        nbd_port: int = 8005,
        control_port: int = 8003,
        mgmt_port: int = 8004,
        mdm_address: str = "127.0.0.1",
        mdm_port: int = 8001,
        cluster_secret: Optional[str] = None
    ):
        """
        Initialize SDC service.
        
        Args:
            sdc_id: SDC ID from MDM registration
            sdc_component_id: Component ID for discovery (e.g., 'sdc-10.0.1.20')
            listen_address: Address to bind all servers to
            nbd_port: NBD device server port (default 8005)
            control_port: Control API port (default 8003)
            mgmt_port: Management API port (default 8004)
            mdm_address: MDM host for registration/tokens
            mdm_port: MDM port (default 8001)
            cluster_secret: Cluster secret for authentication
        """
        self.sdc_id = sdc_id
        self.sdc_component_id = sdc_component_id
        self.listen_address = listen_address
        self.nbd_port = nbd_port
        self.control_port = control_port
        self.mgmt_port = mgmt_port
        self.mdm_address = mdm_address
        self.mdm_port = mdm_port
        self.cluster_secret = cluster_secret
        
        # Initialize database
        self.engine, self.SessionLocal = init_sdc_database(self.sdc_component_id)
        
        # Inject session factory into API modules
        control_app.set_db_session_factory(self.SessionLocal)
        mgmt_app.set_db_session_factory(self.SessionLocal)
        
        # Initialize NBD server
        self.nbd_server = NBDServer(
            sdc_id=sdc_id,
            listen_address=listen_address,
            listen_port=nbd_port,
            mdm_address=mdm_address,
            mdm_port=mdm_port,
            db_session_factory=self.SessionLocal
        )
        
        # Inject NBD server into mgmt API for stats
        mgmt_app.set_nbd_server(self.nbd_server)
        
        # Create FastAPI apps
        self.control_app = self._create_control_app()
        self.mgmt_app = self._create_mgmt_app()
        
        # Service state
        self.running = False
        self.control_thread: Optional[threading.Thread] = None
        self.mgmt_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.cleanup_thread: Optional[threading.Thread] = None
        self.start_time = datetime.utcnow()
        
        logger.info(f"SDC service initialized: {sdc_component_id} on {listen_address}")
    
    def _create_control_app(self) -> FastAPI:
        """Create control plane FastAPI app"""
        app = FastAPI(title="SDC Control Plane", version="0.6.0")
        app.include_router(control_app.router)
        
        @app.get("/")
        def root():
            return {
                "service": "sdc_control",
                "component_id": self.sdc_component_id,
                "port": self.control_port,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return app
    
    def _create_mgmt_app(self) -> FastAPI:
        """Create management plane FastAPI app"""
        app = FastAPI(title="SDC Management Plane", version="0.6.0")
        app.include_router(mgmt_app.router)
        
        @app.get("/")
        def root():
            return {
                "service": "sdc_mgmt",
                "component_id": self.sdc_component_id,
                "sdc_id": self.sdc_id,
                "nbd_port": self.nbd_port,
                "control_port": self.control_port,
                "mgmt_port": self.mgmt_port,
                "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return app
    
    def start(self):
        """Start all SDC components"""
        if self.running:
            logger.warning("SDC service already running")
            return
        
        self.running = True
        self.start_time = datetime.utcnow()
        
        logger.info("Starting SDC service components...")
        
        # Start NBD server
        self.nbd_server.start()
        
        # Start control API
        self.control_thread = threading.Thread(
            target=self._run_control_api,
            daemon=True
        )
        self.control_thread.start()
        
        # Start management API
        self.mgmt_thread = threading.Thread(
            target=self._run_mgmt_api,
            daemon=True
        )
        self.mgmt_thread.start()
        
        # Start heartbeat sender
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True
        )
        self.heartbeat_thread.start()
        
        # Start cleanup thread
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True
        )
        self.cleanup_thread.start()
        
        logger.info(f"SDC service started: NBD={self.nbd_port}, Control={self.control_port}, Mgmt={self.mgmt_port}")
    
    def stop(self):
        """Stop all SDC components"""
        if not self.running:
            return
        
        logger.info("Stopping SDC service...")
        
        self.running = False
        
        # Stop NBD server
        self.nbd_server.stop()
        
        # Wait for threads to finish
        for thread in [self.control_thread, self.mgmt_thread, self.heartbeat_thread, self.cleanup_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)
        
        logger.info("SDC service stopped")
    
    def _run_control_api(self):
        """Run control API server (runs in background thread)"""
        try:
            uvicorn.run(
                self.control_app,
                host=self.listen_address,
                port=self.control_port,
                log_level="info",
                access_log=False
            )
        except Exception as e:
            logger.error(f"Control API error: {e}", exc_info=True)
    
    def _run_mgmt_api(self):
        """Run management API server (runs in background thread)"""
        try:
            uvicorn.run(
                self.mgmt_app,
                host=self.listen_address,
                port=self.mgmt_port,
                log_level="info",
                access_log=False
            )
        except Exception as e:
            logger.error(f"Management API error: {e}", exc_info=True)
    
    def _heartbeat_loop(self):
        """Send periodic heartbeats to MDM (runs in background thread)"""
        heartbeat_url = f"http://{self.mdm_address}:{self.mdm_port}/discovery/heartbeat/{self.sdc_component_id}"
        
        while self.running:
            try:
                response = requests.post(heartbeat_url, timeout=5)
                
                if response.status_code == 200:
                    logger.debug(f"Heartbeat sent: {self.sdc_component_id}")
                else:
                    logger.warning(f"Heartbeat failed: {response.status_code}")
            
            except requests.exceptions.ConnectionError:
                logger.warning(f"Cannot reach MDM at {self.mdm_address}:{self.mdm_port}")
            
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            
            # Wait 10 seconds between heartbeats
            time.sleep(10)
    
    def _cleanup_loop(self):
        """Periodic cleanup of stale cache data (runs in background thread)"""
        while self.running:
            try:
                cleanup_stale_data(self.SessionLocal, max_age_hours=24)
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            
            # Run cleanup every hour
            time.sleep(3600)
    
    def wait(self):
        """Block until service stops (for main process)"""
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            self.stop()
