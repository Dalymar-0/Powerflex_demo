"""
SDS Service (Phase 5)

Multi-listener service launcher for SDS node.
Runs 3 servers in parallel threads:
- Data server (TCP socket, port 9700+n)
- Control server (HTTP FastAPI, port 9100+n)
- Management server (HTTP FastAPI, port 9200+n)

Plus 2 background workers:
- Heartbeat sender → MDM (every 10s)
- ACK batch sender → MDM (every 5s)

Usage:
    python -m sds.service --sds-id 1 --component-id sds-10.0.1.10 \
        --storage-root ./vm_storage/sds1 --mdm-url http://10.0.1.1:8001 \
        --data-port 9700 --control-port 9100 --mgmt-port 9200
"""

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime

import uvicorn
from sqlalchemy.orm import Session

# SDS components
from sds.database import init_session_factory, init_sds_db
from sds.data_handler import SDSDataHandler
from sds.heartbeat_sender import HeartbeatSender
from sds.ack_sender import AckSender
from sds.models import SDSMetadata

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class SDSService:
    """
    Main SDS service orchestrator.
    Manages lifecycle of all 3 listeners + 2 background workers.
    """
    
    def __init__(
        self,
        sds_id: int,
        component_id: str,
        storage_root: str,
        mdm_url: str,
        cluster_secret: str,
        data_host: str = "0.0.0.0",
        data_port: int = 9700,
        control_host: str = "0.0.0.0",
        control_port: int = 9100,
        mgmt_host: str = "0.0.0.0",
        mgmt_port: int = 9200
    ):
        """
        Initialize SDS service.
        
        Args:
            sds_id: SDS ID from MDM's powerflex.db
            component_id: Discovery component ID (e.g., "sds-10.0.1.10")
            storage_root: Storage directory for this SDS node
            mdm_url: MDM base URL
            cluster_secret: Shared secret from discovery registration
            data_host: Data server host (default: 0.0.0.0)
            data_port: Data server port (default: 9700)
            control_host: Control server host (default: 0.0.0.0)
            control_port: Control server port (default: 9100)
            mgmt_host: Management server host (default: 0.0.0.0)
            mgmt_port: Management server port (default: 9200)
        """
        self.sds_id = sds_id
        self.component_id = component_id
        self.storage_root = storage_root
        self.mdm_url = mdm_url.rstrip("/")
        self.cluster_secret = cluster_secret
        
        self.data_host = data_host
        self.data_port = data_port
        self.control_host = control_host
        self.control_port = control_port
        self.mgmt_host = mgmt_host
        self.mgmt_port = mgmt_port
        
        # Components
        self.data_handler = None
        self.heartbeat_sender = None
        self.ack_sender = None
        
        # Threads
        self.data_thread = None
        self.control_thread = None
        self.mgmt_thread = None
        
        # Shutdown coordination
        self.running = threading.Event()
        self.running.set()
        
        logger.info(f"SDS Service initialized: sds_id={sds_id}, component={component_id}")
        logger.info(f"  Data port: {data_host}:{data_port}")
        logger.info(f"  Control port: {control_host}:{control_port}")
        logger.info(f"  Management port: {mgmt_host}:{mgmt_port}")
    
    def start(self):
        """
        Start all SDS components.
        """
        logger.info("Starting SDS Service...")
        
        # 1. Initialize local database
        logger.info("Initializing SDS local database...")
        init_sds_db(self.storage_root)
        init_session_factory(self.storage_root)
        
        # 2. Store metadata
        self._init_metadata()
        
        # 3. Start data handler (TCP socket server)
        logger.info("Starting data handler...")
        self.data_handler = SDSDataHandler(
            host=self.data_host,
            port=self.data_port,
            storage_root=self.storage_root,
            cluster_secret=self.cluster_secret,
            sds_id=self.sds_id,
            component_id=self.component_id
        )
        self.data_thread = threading.Thread(
            target=self.data_handler.start,
            daemon=False
        )
        self.data_thread.start()
        
        # 4. Start control server (FastAPI)
        logger.info("Starting control server...")
        self.control_thread = threading.Thread(
            target=self._run_control_server,
            daemon=False
        )
        self.control_thread.start()
        
        # 5. Start management server (FastAPI)
        logger.info("Starting management server...")
        self.mgmt_thread = threading.Thread(
            target=self._run_mgmt_server,
            daemon=False
        )
        self.mgmt_thread.start()
        
        # 6. Start heartbeat sender
        logger.info("Starting heartbeat sender...")
        from sds.database import get_sds_session_factory
        session_factory = get_sds_session_factory(self.storage_root)
        
        self.heartbeat_sender = HeartbeatSender(
            db_session_factory=session_factory,
            mdm_url=self.mdm_url,
            component_id=self.component_id,
            interval_seconds=10
        )
        self.heartbeat_sender.start()
        
        # 7. Start ACK sender
        logger.info("Starting ACK sender...")
        sds_address = f"{self.data_host}:{self.data_port}"
        self.ack_sender = AckSender(
            db_session_factory=session_factory,
            mdm_url=self.mdm_url,
            sds_id=self.sds_id,
            sds_address=sds_address,
            interval_seconds=5,
            batch_size=100
        )
        self.ack_sender.start()
        
        logger.info("✓ SDS Service started successfully")
        logger.info(f"  Data port listening: {self.data_host}:{self.data_port}")
        logger.info(f"  Control API: http://{self.control_host}:{self.control_port}")
        logger.info(f"  Management API: http://{self.mgmt_host}:{self.mgmt_port}")
    
    def stop(self):
        """
        Stop all SDS components.
        """
        logger.info("Stopping SDS Service...")
        
        # Signal stop
        self.running.clear()
        
        # Stop background workers
        if self.heartbeat_sender:
            self.heartbeat_sender.stop()
        
        if self.ack_sender:
            self.ack_sender.stop()
        
        # Stop data handler
        if self.data_handler:
            self.data_handler.stop()
        
        # Wait for threads to finish
        if self.data_thread and self.data_thread.is_alive():
            self.data_thread.join(timeout=5)
        
        if self.control_thread and self.control_thread.is_alive():
            self.control_thread.join(timeout=5)
        
        if self.mgmt_thread and self.mgmt_thread.is_alive():
            self.mgmt_thread.join(timeout=5)
        
        logger.info("✓ SDS Service stopped")
    
    def _init_metadata(self):
        """Initialize or update SDSMetadata record"""
        from sds.database import get_db
        
        db = next(get_db())
        try:
            metadata = db.query(SDSMetadata).filter(SDSMetadata.id == 1).first()
            
            if not metadata:
                # Create new metadata
                metadata = SDSMetadata(
                    id=1,
                    sds_id=self.sds_id,
                    component_id=self.component_id,
                    cluster_secret=self.cluster_secret,
                    data_host=self.data_host,
                    data_port=self.data_port,
                    control_host=self.control_host,
                    control_port=self.control_port,
                    mgmt_host=self.mgmt_host,
                    mgmt_port=self.mgmt_port,
                    mdm_url=self.mdm_url,
                    status="ACTIVE",
                    startup_time=datetime.utcnow()
                )
                db.add(metadata)
                logger.info("Created SDS metadata record")
            else:
                # Update existing
                metadata.sds_id = self.sds_id
                metadata.component_id = self.component_id
                metadata.cluster_secret = self.cluster_secret
                metadata.data_host = self.data_host
                metadata.data_port = self.data_port
                metadata.control_host = self.control_host
                metadata.control_port = self.control_port
                metadata.mgmt_host = self.mgmt_host
                metadata.mgmt_port = self.mgmt_port
                metadata.mdm_url = self.mdm_url
                metadata.status = "ACTIVE"
                metadata.startup_time = datetime.utcnow()
                logger.info("Updated SDS metadata record")
            
            db.commit()
        finally:
            db.close()
    
    def _run_control_server(self):
        """Run control FastAPI server in thread"""
        try:
            from sds.control_app import app
            
            # Set storage_root on app state for database access
            app.state.storage_root = self.storage_root
            
            uvicorn.run(
                app,
                host=self.control_host,
                port=self.control_port,
                log_level="info",
                access_log=False
            )
        except Exception as e:
            logger.error(f"Control server error: {e}", exc_info=True)
    
    def _run_mgmt_server(self):
        """Run management FastAPI server in thread"""
        try:
            from sds.mgmt_app import app
            
            # Set storage_root on app state for database access
            app.state.storage_root = self.storage_root
            
            uvicorn.run(
                app,
                host=self.mgmt_host,
                port=self.mgmt_port,
                log_level="info",
                access_log=False
            )
        except Exception as e:
            logger.error(f"Management server error: {e}", exc_info=True)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="PowerFlex SDS Service")
    
    parser.add_argument(
        "--sds-id",
        type=int,
        required=True,
        help="SDS ID from MDM"
    )
    parser.add_argument(
        "--component-id",
        type=str,
        required=True,
        help="Discovery component ID (e.g., sds-10.0.1.10)"
    )
    parser.add_argument(
        "--storage-root",
        type=str,
        required=True,
        help="Storage directory for this SDS node"
    )
    parser.add_argument(
        "--mdm-url",
        type=str,
        required=True,
        help="MDM base URL (e.g., http://10.0.1.1:8001)"
    )
    parser.add_argument(
        "--cluster-secret",
        type=str,
        required=True,
        help="Shared cluster secret from discovery"
    )
    parser.add_argument(
        "--data-host",
        type=str,
        default="0.0.0.0",
        help="Data server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--data-port",
        type=int,
        default=9700,
        help="Data server port (default: 9700)"
    )
    parser.add_argument(
        "--control-host",
        type=str,
        default="0.0.0.0",
        help="Control server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=9100,
        help="Control server port (default: 9100)"
    )
    parser.add_argument(
        "--mgmt-host",
        type=str,
        default="0.0.0.0",
        help="Management server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--mgmt-port",
        type=int,
        default=9200,
        help="Management server port (default: 9200)"
    )
    
    args = parser.parse_args()
    
    # Create service
    service = SDSService(
        sds_id=args.sds_id,
        component_id=args.component_id,
        storage_root=args.storage_root,
        mdm_url=args.mdm_url,
        cluster_secret=args.cluster_secret,
        data_host=args.data_host,
        data_port=args.data_port,
        control_host=args.control_host,
        control_port=args.control_port,
        mgmt_host=args.mgmt_host,
        mgmt_port=args.mgmt_port
    )
    
    # Signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"\nReceived signal {signum}, shutting down...")
        service.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start service
    service.start()
    
    # Keep main thread alive
    try:
        while service.running.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt, shutting down...")
        service.stop()


if __name__ == "__main__":
    main()
