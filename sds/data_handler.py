"""
SDS Data Handler (Phase 5)

TCP socket server handling disk IO operations with token verification.
Listens on SDS_DATA_PORT (9700+n) and serves read/write requests from SDC.

CRITICAL: Every IO request MUST include a valid authorization token from MDM.
No token = no disk access.

Protocol: Newline-delimited JSON over TCP (from shared/socket_protocol.py)
"""

import socket
import threading
import json
import base64
import time
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from shared.socket_protocol import SocketProtocol
from sds.token_verifier import TokenVerifier
from sds.database import get_db
from sds.models import LocalReplica, LocalDevice, WriteJournal, AckQueue

logger = logging.getLogger(__name__)


class SDSDataHandler:
    """
    SDS data plane handler with token verification.
    Services IO requests from SDC after verifying MDM-signed tokens.
    """
    
    def __init__(
        self,
        host: str,
        port: int,
        storage_root: str,
        cluster_secret: str,
        sds_id: int,
        component_id: str
    ):
        """
        Initialize SDS data handler.
        
        Args:
            host: Listen address (e.g., "0.0.0.0" or "127.0.0.1")
            port: Data port (e.g., 9700)
            storage_root: Root directory for chunk storage
            cluster_secret: Shared secret for token verification
            sds_id: SDS ID from MDM's powerflex.db
            component_id: Discovery component ID (e.g., "sds-10.0.1.10")
        """
        self.host = host
        self.port = port
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.cluster_secret = cluster_secret
        self.sds_id = sds_id
        self.component_id = component_id
        
        self.server_socket = None
        self.running = False
        self.protocol = SocketProtocol()
        
        logger.info(f"SDS data handler initialized: {host}:{port}, storage={storage_root}")
    
    def start(self):
        """Start listening for IO requests"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True
        
        logger.info(f"SDS data handler listening on {self.host}:{self.port}")
        
        while self.running:
            try:
                client_socket, client_addr = self.server_socket.accept()
                logger.debug(f"Accepted connection from {client_addr}")
                
                # Handle each client in a separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, client_addr),
                    daemon=True
                )
                client_thread.start()
                
            except Exception as e:
                if self.running:
                    logger.error(f"Error accepting connection: {e}")
    
    def stop(self):
        """Stop the data handler"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        logger.info("SDS data handler stopped")
    
    def _handle_client(self, client_socket: socket.socket, client_addr):
        """Handle a single client connection"""
        try:
            while True:
                # Receive JSON frame
                frame = self.protocol.receive_frame(client_socket)
                if frame is None:
                    break  # Connection closed
                
                # Process request
                response = self._process_request(frame)
                
                # Send response
                self.protocol.send_frame(client_socket, response)
                
        except Exception as e:
            logger.error(f"Error handling client {client_addr}: {e}")
        finally:
            client_socket.close()
            logger.debug(f"Connection closed: {client_addr}")
    
    def _process_request(self, request: Dict) -> Dict:
        """
        Process IO request with token verification.
        
        Request format:
        {
            "action": "read" | "write" | "init_volume",
            "token": {...},  # IO authorization token (required for read/write)
            "volume_id": int,
            "chunk_id": int,
            "offset_bytes": int,
            "length_bytes": int,  # for read
            "data_b64": str  # for write
        }
        """
        action = request.get("action")
        
        if action == "init_volume":
            return self._handle_init_volume(request)
        elif action == "read":
            return self._handle_read(request)
        elif action == "write":
            return self._handle_write(request)
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}
    
    def _handle_init_volume(self, request: Dict) -> Dict:
        """
        Initialize volume chunk storage (legacy support).
        In Phase 5, chunk allocation is controlled by MDM via control plane.
        """
        volume_id = request.get("volume_id")
        size_bytes = request.get("size_bytes", 1073741824)  # Default 1GB
        
        # This is now handled by control plane, but keep for compatibility
        logger.info(f"Init volume request: volume_id={volume_id}, size={size_bytes}")
        
        return {"ok": True, "message": "Volume init handled by control plane"}
    
    def _handle_read(self, request: Dict) -> Dict:
        """Handle read request with token verification"""
        start_time = time.time()
        
        # Extract request fields
        token = request.get("token")
        volume_id = request.get("volume_id")
        chunk_id = request.get("chunk_id")
        offset_bytes = request.get("offset_bytes", 0)
        length_bytes = request.get("length_bytes")
        
        # Type validation
        if not token or not isinstance(token, dict):
            return {"ok": False, "error": "Missing or invalid authorization token"}
        if not isinstance(volume_id, int):
            return {"ok": False, "error": "Invalid volume_id type"}
        if not isinstance(chunk_id, int):
            return {"ok": False, "error": "Invalid chunk_id type"}
        if not isinstance(offset_bytes, int):
            return {"ok": False, "error": "Invalid offset_bytes type"}
        if not isinstance(length_bytes, int):
            return {"ok": False, "error": "Invalid length_bytes type"}
        
        # Get database session
        from sds.database import SessionLocal
        db = SessionLocal()
        
        try:
            # Verify token
            verifier = TokenVerifier(db, self.cluster_secret)
            is_valid, error = verifier.verify_io_token(
                token=token,
                volume_id=volume_id,
                chunk_id=chunk_id,
                operation="read",
                offset_bytes=offset_bytes,
                length_bytes=length_bytes
            )
            
            if not is_valid:
                logger.warning(f"Token verification failed for read: {error}")
                return {"ok": False, "error": f"Token verification failed: {error}"}
            
            # Find local replica
            replica = db.query(LocalReplica).filter(
                LocalReplica.chunk_id == chunk_id,
                LocalReplica.volume_id == volume_id
            ).first()
            
            if not replica:
                return {"ok": False, "error": f"Chunk {chunk_id} not found on this SDS"}
            
            # Read from disk
            chunk_file = Path(str(replica.local_file_path))  # type: ignore[arg-type]
            if not chunk_file.exists():
                return {"ok": False, "error": f"Chunk file missing: {chunk_file}"}
            
            with open(chunk_file, "rb") as f:
                f.seek(offset_bytes)
                data = f.read(length_bytes)
            
            # Mark token consumed
            execution_ms = (time.time() - start_time) * 1000
            verifier.mark_token_consumed(
                token_id=token["token_id"],
                volume_id=volume_id,
                chunk_id=chunk_id,
                operation="read",
                offset_bytes=offset_bytes,
                length_bytes=length_bytes,
                success=True,
                bytes_processed=len(data),
                execution_duration_ms=execution_ms
            )
            
            # Queue ACK to MDM (asynchronous batch sender will pick this up)
            ack = AckQueue(
                token_id=token["token_id"],
                chunk_id=chunk_id,
                success=True,
                bytes_processed=len(data),
                execution_duration_ms=execution_ms,
                checksum=replica.checksum,
                generation=replica.generation
            )
            db.add(ack)
            db.commit()
            
            logger.info(f"Read successful: volume={volume_id}, chunk={chunk_id}, bytes={len(data)}")
            
            return {
                "ok": True,
                "data_b64": base64.b64encode(data).decode("ascii"),
                "bytes_read": len(data),
                "generation": replica.generation,
                "checksum": replica.checksum
            }
            
        except Exception as e:
            logger.error(f"Read error: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}
        finally:
            db.close()
    
    def _handle_write(self, request: Dict) -> Dict:
        """Handle write request with token verification"""
        start_time = time.time()
        
        # Extract request fields
        token = request.get("token")
        volume_id = request.get("volume_id")
        chunk_id = request.get("chunk_id")
        offset_bytes = request.get("offset_bytes", 0)
        data_b64 = request.get("data_b64")
        
        # Type validation
        if not token or not isinstance(token, dict):
            return {"ok": False, "error": "Missing or invalid authorization token"}
        if not isinstance(volume_id, int):
            return {"ok": False, "error": "Invalid volume_id type"}
        if not isinstance(chunk_id, int):
            return {"ok": False, "error": "Invalid chunk_id type"}
        if not isinstance(offset_bytes, int):
            return {"ok": False, "error": "Invalid offset_bytes type"}
        
        if not data_b64 or not isinstance(data_b64, str):
            return {"ok": False, "error": "Missing or invalid data_b64"}
        
        # Decode data
        try:
            data = base64.b64decode(data_b64)
        except Exception as e:
            return {"ok": False, "error": f"Invalid base64 data: {e}"}
        
        length_bytes = len(data)
        
        # Get database session
        from sds.database import SessionLocal
        db = SessionLocal()
        
        try:
            # Verify token
            verifier = TokenVerifier(db, self.cluster_secret)
            is_valid, error = verifier.verify_io_token(
                token=token,
                volume_id=volume_id,
                chunk_id=chunk_id,
                operation="write",
                offset_bytes=offset_bytes,
                length_bytes=length_bytes
            )
            
            if not is_valid:
                logger.warning(f"Token verification failed for write: {error}")
                return {"ok": False, "error": f"Token verification failed: {error}"}
            
            # Find local replica
            replica = db.query(LocalReplica).filter(
                LocalReplica.chunk_id == chunk_id,
                LocalReplica.volume_id == volume_id
            ).first()
            
            if not replica:
                return {"ok": False, "error": f"Chunk {chunk_id} not found on this SDS"}
            
            # Write journal entry (crash recovery)
            journal_entry = WriteJournal(
                token_id=token["token_id"],
                chunk_id=chunk_id,
                operation="write",
                offset_bytes=offset_bytes,
                length_bytes=length_bytes,
                status="PENDING",
                generation_before=replica.generation,
                generation_after=replica.generation + 1
            )
            db.add(journal_entry)
            db.commit()
            
            # Write to disk
            chunk_file = Path(str(replica.local_file_path))  # type: ignore[arg-type]
            chunk_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(chunk_file, "r+b" if chunk_file.exists() else "wb") as f:
                f.seek(offset_bytes)
                f.write(data)
                f.flush()
            
            # Update replica metadata
            replica.generation += 1
            replica.last_write_at = datetime.utcnow()
            db.commit()
            
            # Mark journal committed
            journal_entry.status = "COMMITTED"
            journal_entry.committed_at = datetime.utcnow()
            db.commit()
            
            # Mark token consumed
            execution_ms = (time.time() - start_time) * 1000
            verifier.mark_token_consumed(
                token_id=token["token_id"],
                volume_id=volume_id,
                chunk_id=chunk_id,
                operation="write",
                offset_bytes=offset_bytes,
                length_bytes=length_bytes,
                success=True,
                bytes_processed=length_bytes,
                execution_duration_ms=execution_ms
            )
            
            # Queue ACK to MDM
            ack = AckQueue(
                token_id=token["token_id"],
                chunk_id=chunk_id,
                success=True,
                bytes_processed=length_bytes,
                execution_duration_ms=execution_ms,
                generation=replica.generation
            )
            db.add(ack)
            db.commit()
            
            logger.info(f"Write successful: volume={volume_id}, chunk={chunk_id}, bytes={length_bytes}, gen={replica.generation}")
            
            return {
                "ok": True,
                "bytes_written": length_bytes,
                "generation": replica.generation
            }
            
        except Exception as e:
            logger.error(f"Write error: {e}", exc_info=True)
            
            # Mark journal aborted if it was created
            try:
                if journal_entry.id is not None:  # Check if journal_entry exists and was persisted
                    journal_entry.status = "ABORTED"  # type: ignore[assignment]
                    db.commit()
            except (NameError, AttributeError):
                pass  # journal_entry not created yet, nothing to abort
            
            return {"ok": False, "error": str(e)}
        finally:
            db.close()
