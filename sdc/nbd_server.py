"""
SDC NBD Server - Phase 6

NBD-like (Network Block Device) protocol server that exposes volumes as block devices.
Listens on port 8005 and handles IO requests from VMs/applications.

Protocol:
- Simple request/response over TCP
- Newline-delimited JSON frames
- Operations: READ, WRITE, FLUSH, DISCONNECT
- Each IO triggers token acquisition from MDM

This is NOT standard NBD protocol - it's a simplified PowerFlex-specific protocol
that demonstrates the concept of exposing volumes as network block devices.

Flow:
1. Client connects to port 8005
2. Client sends CONNECT request with volume_id
3. Server validates volume mapping
4. Client sends READ/WRITE requests
5. Server acquires token from MDM
6. Server executes IO via data_client to SDS
7. Server returns result to client

Per REFORM_PLAN.md Phase 6, this implements the SDC device protocol.
"""

import socket
import threading
import logging
import json
from typing import Dict, Optional
from pathlib import Path

from shared.socket_protocol import SocketProtocol
from sdc.token_requester import TokenRequester
from sdc.data_client import SDCDataClient

logger = logging.getLogger(__name__)


class NBDServer:
    """
    NBD-like server exposing volumes as block devices.
    Runs in background thread, handles multiple concurrent connections.
    """
    
    def __init__(
        self,
        sdc_id: int,
        listen_address: str,
        listen_port: int,
        mdm_address: str,
        mdm_port: int,
        db_session_factory
    ):
        """
        Initialize NBD server.
        
        Args:
            sdc_id: This SDC's ID from registration
            listen_address: Address to bind to (usually 127.0.0.1 or 0.0.0.0)
            listen_port: Port to listen on (8005)
            mdm_address: MDM host for token requests
            mdm_port: MDM port (8001)
            db_session_factory: SQLAlchemy session factory for local DB
        """
        self.sdc_id = sdc_id
        self.listen_address = listen_address
        self.listen_port = listen_port
        self.db_session_factory = db_session_factory
        
        self.token_requester = TokenRequester(mdm_address, mdm_port, sdc_id)
        self.data_client = SDCDataClient(timeout_seconds=30.0)
        self.protocol = SocketProtocol()
        
        self.running = False
        self.server_thread: Optional[threading.Thread] = None
        self.active_connections: Dict[str, socket.socket] = {}  # client_id → socket
        
        logger.info(f"NBD server initialized on {listen_address}:{listen_port}")
    
    def start(self):
        """Start NBD server in background thread"""
        if self.running:
            logger.warning("NBD server already running")
            return
        
        self.running = True
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()
        logger.info(f"NBD server started on {self.listen_address}:{self.listen_port}")
    
    def stop(self):
        """Stop NBD server"""
        if not self.running:
            return
        
        self.running = False
        
        # Close all active connections
        for client_id, sock in list(self.active_connections.items()):
            try:
                sock.close()
            except:
                pass
        
        self.active_connections.clear()
        
        if self.server_thread:
            self.server_thread.join(timeout=5)
        
        logger.info("NBD server stopped")
    
    def _server_loop(self):
        """Main server loop (runs in background thread)"""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server_sock.bind((self.listen_address, self.listen_port))
            server_sock.listen(10)
            server_sock.settimeout(1.0)  # Allow periodic check of self.running
            
            logger.info(f"NBD server listening on {self.listen_address}:{self.listen_port}")
            
            while self.running:
                try:
                    client_sock, client_addr = server_sock.accept()
                    logger.info(f"NBD client connected: {client_addr}")
                    
                    # Handle client in separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_sock, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                
                except socket.timeout:
                    continue  # Check self.running
                
                except Exception as e:
                    if self.running:
                        logger.error(f"Accept error: {e}")
        
        finally:
            server_sock.close()
            logger.info("NBD server socket closed")
    
    def _handle_client(self, client_sock: socket.socket, client_addr: tuple):
        """Handle individual client connection"""
        client_id = f"{client_addr[0]}:{client_addr[1]}"
        self.active_connections[client_id] = client_sock
        
        try:
            client_sock.settimeout(60.0)
            
            # Client session state
            mounted_volume_id: Optional[int] = None
            
            while self.running:
                # Receive request
                request = self.protocol.receive_message(client_sock)
                
                if not request:
                    logger.info(f"Client {client_id} disconnected")
                    break
                
                operation = request.get("operation")
                
                if operation == "CONNECT":
                    # Mount volume
                    volume_id = request.get("volume_id")
                    
                    if not isinstance(volume_id, int):
                        self._send_error(client_sock, "Invalid volume_id")
                        continue
                    
                    # Validate volume mapping
                    if not self._is_volume_mapped(volume_id):
                        self._send_error(client_sock, f"Volume {volume_id} not mapped to this SDC")
                        continue
                    
                    mounted_volume_id = volume_id
                    
                    # Get volume info
                    volume_info = self._get_volume_info(volume_id)
                    
                    response = {
                        "ok": True,
                        "volume_id": volume_id,
                        "size_bytes": volume_info.get("size_bytes", 0) if volume_info else 0,
                        "message": f"Volume {volume_id} mounted"
                    }
                    
                    self.protocol.send_message(client_sock, response)
                    logger.info(f"Client {client_id} mounted volume {volume_id}")
                
                elif operation == "READ":
                    if mounted_volume_id is None:
                        self._send_error(client_sock, "No volume mounted. Send CONNECT first.")
                        continue
                    
                    self._handle_read(client_sock, mounted_volume_id, request)
                
                elif operation == "WRITE":
                    if mounted_volume_id is None:
                        self._send_error(client_sock, "No volume mounted. Send CONNECT first.")
                        continue
                    
                    self._handle_write(client_sock, mounted_volume_id, request)
                
                elif operation == "DISCONNECT":
                    logger.info(f"Client {client_id} requested disconnect")
                    self.protocol.send_message(client_sock, {"ok": True, "message": "Disconnected"})
                    break
                
                else:
                    self._send_error(client_sock, f"Unknown operation: {operation}")
        
        except socket.timeout:
            logger.warning(f"Client {client_id} timeout")
        
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}", exc_info=True)
        
        finally:
            del self.active_connections[client_id]
            client_sock.close()
            logger.info(f"Client {client_id} connection closed")
    
    def _handle_read(self, client_sock: socket.socket, volume_id: int, request: dict):
        """Handle READ operation"""
        offset_bytes = request.get("offset_bytes")
        length_bytes = request.get("length_bytes")
        
        if not isinstance(offset_bytes, int) or not isinstance(length_bytes, int):
            self._send_error(client_sock, "Invalid offset_bytes or length_bytes")
            return
        
        # Request token from MDM
        token = self.token_requester.request_token(
            volume_id=volume_id,
            operation="READ",
            offset_bytes=offset_bytes,
            length_bytes=length_bytes
        )
        
        if not token:
            self._send_error(client_sock, "Failed to acquire IO token from MDM")
            return
        
        # Execute IO using token's plan
        io_plan = token.get("io_plan")
        if not io_plan:
            self._send_error(client_sock, "Token missing IO plan")
            return
        
        success, data_bytes, error = self.data_client.execute_io_plan(io_plan, token, data_bytes=None)
        
        if success:
            import base64
            data_b64 = base64.b64encode(data_bytes).decode("ascii") if data_bytes else ""
            
            response = {
                "ok": True,
                "data_b64": data_b64,
                "length_bytes": len(data_bytes) if data_bytes else 0
            }
            
            self.protocol.send_message(client_sock, response)
            logger.debug(f"Read completed: {len(data_bytes) if data_bytes else 0} bytes")
        
        else:
            self._send_error(client_sock, error or "Read failed")
    
    def _handle_write(self, client_sock: socket.socket, volume_id: int, request: dict):
        """Handle WRITE operation"""
        offset_bytes = request.get("offset_bytes")
        data_b64 = request.get("data_b64")
        
        if not isinstance(offset_bytes, int) or not isinstance(data_b64, str):
            self._send_error(client_sock, "Invalid offset_bytes or data_b64")
            return
        
        # Decode data
        import base64
        try:
            data_bytes = base64.b64decode(data_b64)
        except Exception as e:
            self._send_error(client_sock, f"Invalid base64 data: {e}")
            return
        
        # Request token from MDM
        token = self.token_requester.request_token(
            volume_id=volume_id,
            operation="WRITE",
            offset_bytes=offset_bytes,
            length_bytes=len(data_bytes)
        )
        
        if not token:
            self._send_error(client_sock, "Failed to acquire IO token from MDM")
            return
        
        # Execute IO using token's plan
        io_plan = token.get("io_plan")
        if not io_plan:
            self._send_error(client_sock, "Token missing IO plan")
            return
        
        success, _, error = self.data_client.execute_io_plan(io_plan, token, data_bytes=data_bytes)
        
        if success:
            response = {
                "ok": True,
                "bytes_written": len(data_bytes)
            }
            
            self.protocol.send_message(client_sock, response)
            logger.debug(f"Write completed: {len(data_bytes)} bytes")
        
        else:
            self._send_error(client_sock, error or "Write failed")
    
    def _send_error(self, client_sock: socket.socket, error_message: str):
        """Send error response to client"""
        response = {"ok": False, "error": error_message}
        self.protocol.send_message(client_sock, response)
        logger.debug(f"Sent error: {error_message}")
    
    def _is_volume_mapped(self, volume_id: int) -> bool:
        """Check if volume is mapped to this SDC"""
        db = self.db_session_factory()
        try:
            from sdc.models import VolumeMappingCache
            
            mapping = db.query(VolumeMappingCache).filter(
                VolumeMappingCache.volume_id == volume_id
            ).first()
            
            return mapping is not None
        
        finally:
            db.close()
    
    def _get_volume_info(self, volume_id: int) -> Optional[dict]:
        """Get volume information from cache"""
        db = self.db_session_factory()
        try:
            from sdc.models import VolumeMappingCache
            
            mapping = db.query(VolumeMappingCache).filter(
                VolumeMappingCache.volume_id == volume_id
            ).first()
            
            if mapping:
                return {
                    "volume_id": volume_id,
                    "volume_name": mapping.volume_name,  # type: ignore[attr-defined]
                    "size_bytes": mapping.size_bytes,  # type: ignore[attr-defined]
                    "access_mode": mapping.access_mode  # type: ignore[attr-defined]
                }
            
            return None
        
        finally:
            db.close()
