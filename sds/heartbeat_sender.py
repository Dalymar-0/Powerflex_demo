"""
SDS Heartbeat Sender (Phase 5)

Background thread that sends periodic heartbeats to MDM.
Runs every 10 seconds to indicate liveness.
"""

import requests
import threading
import time
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from sds.models import SDSMetadata

logger = logging.getLogger(__name__)


class HeartbeatSender:
    """
    Sends periodic heartbeats to MDM via discovery API.
    """
    
    def __init__(
        self,
        db_session_factory,
        mdm_url: str,
        component_id: str,
        interval_seconds: int = 10
    ):
        """
        Initialize heartbeat sender.
        
        Args:
            db_session_factory: SQLAlchemy session factory (scoped_session)
            mdm_url: MDM base URL (e.g., "http://10.0.1.1:8001")
            component_id: Discovery component ID (e.g., "sds-10.0.1.10")
            interval_seconds: Heartbeat interval (default: 10 seconds)
        """
        self.db_session_factory = db_session_factory
        self.mdm_url = mdm_url.rstrip("/")
        self.component_id = component_id
        self.interval_seconds = interval_seconds
        
        self.running = False
        self.thread = None
        
        logger.info(f"Heartbeat sender initialized: mdm={mdm_url}, component={component_id}, interval={interval_seconds}s")
    
    def start(self):
        """Start heartbeat sender thread"""
        if self.running:
            logger.warning("Heartbeat sender already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
        logger.info("Heartbeat sender started")
    
    def stop(self):
        """Stop heartbeat sender thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("Heartbeat sender stopped")
    
    def _run(self):
        """Main heartbeat loop"""
        while self.running:
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.error(f"Heartbeat send failed: {e}")
            
            # Sleep in small increments for responsive shutdown
            for _ in range(self.interval_seconds * 10):
                if not self.running:
                    break
                time.sleep(0.1)
    
    def _send_heartbeat(self):
        """Send single heartbeat to MDM"""
        try:
            endpoint = f"{self.mdm_url}/discovery/heartbeat/{self.component_id}"
            
            response = requests.post(
                endpoint,
                timeout=5
            )
            
            if response.status_code == 200:
                logger.debug(f"Heartbeat sent successfully: {self.component_id}")
                
                # Update local metadata
                db = self.db_session_factory()
                try:
                    metadata = db.query(SDSMetadata).filter(SDSMetadata.id == 1).first()
                    if metadata:
                        metadata.last_heartbeat_sent_at = datetime.utcnow()
                        db.commit()
                finally:
                    db.close()
            else:
                logger.warning(f"Heartbeat failed: status={response.status_code}")
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Heartbeat request error: {e}")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}", exc_info=True)
