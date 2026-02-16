"""
SDS ACK Sender (Phase 5)

Background thread that batches transaction ACKs and sends them to MDM.
Runs every 5 seconds to batch-report IO transaction completions.
"""

import requests
import threading
import time
import logging
from typing import List
from datetime import datetime

from sds.models import AckQueue

logger = logging.getLogger(__name__)


class AckSender:
    """
    Batches and sends transaction ACKs to MDM.
    Picks up pending ACKs from ack_queue table and POSTs to MDM /io/tx/ack.
    """
    
    def __init__(
        self,
        db_session_factory,
        mdm_url: str,
        sds_id: int,
        sds_address: str,
        interval_seconds: int = 5,
        batch_size: int = 100
    ):
        """
        Initialize ACK sender.
        
        Args:
            db_session_factory: SQLAlchemy session factory (scoped_session)
            mdm_url: MDM base URL (e.g., "http://10.0.1.1:8001")
            sds_id: SDS ID from MDM's powerflex.db
            sds_address: SDS data port address (e.g., "10.0.1.10:9700")
            interval_seconds: Batch send interval (default: 5 seconds)
            batch_size: Max ACKs per batch (default: 100)
        """
        self.db_session_factory = db_session_factory
        self.mdm_url = mdm_url.rstrip("/")
        self.sds_id = sds_id
        self.sds_address = sds_address
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        
        self.running = False
        self.thread = None
        
        logger.info(f"ACK sender initialized: mdm={mdm_url}, sds_id={sds_id}, interval={interval_seconds}s, batch={batch_size}")
    
    def start(self):
        """Start ACK sender thread"""
        if self.running:
            logger.warning("ACK sender already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
        logger.info("ACK sender started")
    
    def stop(self):
        """Stop ACK sender thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("ACK sender stopped")
    
    def _run(self):
        """Main ACK batch loop"""
        while self.running:
            try:
                self._send_batch()
            except Exception as e:
                logger.error(f"ACK batch send failed: {e}", exc_info=True)
            
            # Sleep in small increments for responsive shutdown
            for _ in range(self.interval_seconds * 10):
                if not self.running:
                    break
                time.sleep(0.1)
    
    def _send_batch(self):
        """Send batch of pending ACKs to MDM"""
        db = self.db_session_factory()
        
        try:
            # Fetch pending ACKs
            pending_acks = db.query(AckQueue).filter(
                AckQueue.ack_status == "PENDING"
            ).limit(self.batch_size).all()
            
            if not pending_acks:
                logger.debug("No pending ACKs to send")
                return
            
            logger.info(f"Sending ACK batch: {len(pending_acks)} ACKs")
            
            # Send each ACK to MDM
            sent_count = 0
            failed_count = 0
            
            for ack in pending_acks:
                success = self._send_single_ack(ack)
                
                if success:
                    ack.ack_status = "SENT"
                    ack.sent_at = datetime.utcnow()
                    sent_count += 1
                else:
                    ack.ack_status = "FAILED"
                    ack.retry_count += 1
                    ack.last_retry_at = datetime.utcnow()
                    failed_count += 1
                
                db.commit()
            
            logger.info(f"ACK batch complete: sent={sent_count}, failed={failed_count}")
            
        except Exception as e:
            logger.error(f"ACK batch error: {e}", exc_info=True)
        finally:
            db.close()
    
    def _send_single_ack(self, ack: AckQueue) -> bool:
        """
        Send single ACK to MDM.
        
        Args:
            ack: AckQueue record
        
        Returns:
            True if successful, False otherwise
        """
        try:
            endpoint = f"{self.mdm_url}/io/tx/ack"
            
            payload = {
                "token_id": ack.token_id,
                "sds_id": self.sds_id,
                "success": ack.success,
                "bytes_processed": ack.bytes_processed,
                "execution_duration_ms": ack.execution_duration_ms,
                "sds_address": self.sds_address,
                "metadata": {
                    "chunk_id": ack.chunk_id,
                    "checksum": ack.checksum,
                    "generation": ack.generation
                }
            }
            
            if ack.error_message:
                payload["error_message"] = ack.error_message
            
            response = requests.post(
                endpoint,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.debug(f"ACK sent: token_id={ack.token_id}")
                return True
            else:
                logger.warning(f"ACK failed: status={response.status_code}, token={ack.token_id}")
                return False
        
        except requests.exceptions.RequestException as e:
            logger.error(f"ACK request error for token {ack.token_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"ACK error for token {ack.token_id}: {e}", exc_info=True)
            return False
