"""
SDC Data Client - Phase 6

Execute IO operations to SDS data ports with token-based authorization.
This module handles the actual data transfer after token acquisition.

IO Flow:
1. Receive IO request from NBD server
2. Acquire token from MDM (token_requester)
3. Connect to SDS data port (TCP socket)
4. Send IO request with token
5. Receive response (data for reads, ok/error for writes)
6. Return to NBD client

Uses shared socket protocol (newline-delimited JSON frames).
"""

import socket
import json
import base64
import logging
from typing import Optional, Dict, Any, Tuple

from shared.socket_protocol import SocketProtocol

logger = logging.getLogger(__name__)


class SDCDataClient:
    """Execute IO operations to SDS with token verification"""
    
    def __init__(self, timeout_seconds: float = 30.0):
        """
        Initialize SDC data client.
        
        Args:
            timeout_seconds: Socket timeout for SDS connections
        """
        self.timeout_seconds = timeout_seconds
        self.protocol = SocketProtocol()
        logger.info(f"SDC data client initialized (timeout={timeout_seconds}s)")
    
    def execute_read(
        self,
        sds_address: str,
        sds_data_port: int,
        volume_id: int,
        chunk_id: int,
        offset_bytes: int,
        length_bytes: int,
        token: Dict[str, Any]
    ) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """
        Execute read operation to SDS.
        
        Args:
            sds_address: SDS host address
            sds_data_port: SDS TCP data port (9700+n)
            volume_id: Volume ID
            chunk_id: Chunk ID to read from
            offset_bytes: Offset within chunk
            length_bytes: Number of bytes to read
            token: Authorization token from MDM
        
        Returns:
            (success, data_bytes, error_message)
        """
        request = {
            "operation": "READ",
            "volume_id": volume_id,
            "chunk_id": chunk_id,
            "offset_bytes": offset_bytes,
            "length_bytes": length_bytes,
            "token": token
        }
        
        try:
            logger.debug(f"READ to {sds_address}:{sds_data_port} chunk={chunk_id} offset={offset_bytes} len={length_bytes}")
            
            # Connect to SDS
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout_seconds)
            sock.connect((sds_address, sds_data_port))
            
            # Send request
            self.protocol.send_message(sock, request)
            
            # Receive response
            response = self.protocol.receive_message(sock)
            sock.close()
            
            if not response:
                return False, None, "Empty response from SDS"
            
            if not response.get("ok"):
                error_msg = response.get("error", "Unknown SDS error")
                logger.error(f"Read failed: {error_msg}")
                return False, None, error_msg
            
            # Decode base64 data
            data_b64 = response.get("data_b64")
            if not data_b64:
                return False, None, "Missing data_b64 in response"
            
            data_bytes = base64.b64decode(data_b64)
            
            logger.debug(f"Read successful: {len(data_bytes)} bytes from {sds_address}:{sds_data_port}")
            return True, data_bytes, None
        
        except socket.timeout:
            logger.error(f"Read timeout to {sds_address}:{sds_data_port}")
            return False, None, f"Timeout connecting to SDS {sds_address}:{sds_data_port}"
        
        except ConnectionRefusedError:
            logger.error(f"Connection refused by {sds_address}:{sds_data_port}")
            return False, None, f"SDS {sds_address}:{sds_data_port} not available"
        
        except Exception as e:
            logger.error(f"Read error: {e}", exc_info=True)
            return False, None, str(e)
    
    def execute_write(
        self,
        sds_address: str,
        sds_data_port: int,
        volume_id: int,
        chunk_id: int,
        offset_bytes: int,
        data_bytes: bytes,
        token: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Execute write operation to SDS.
        
        Args:
            sds_address: SDS host address
            sds_data_port: SDS TCP data port (9700+n)
            volume_id: Volume ID
            chunk_id: Chunk ID to write to
            offset_bytes: Offset within chunk
            data_bytes: Data to write
            token: Authorization token from MDM
        
        Returns:
            (success, error_message)
        """
        data_b64 = base64.b64encode(data_bytes).decode("ascii")
        
        request = {
            "operation": "WRITE",
            "volume_id": volume_id,
            "chunk_id": chunk_id,
            "offset_bytes": offset_bytes,
            "length_bytes": len(data_bytes),
            "data_b64": data_b64,
            "token": token
        }
        
        try:
            logger.debug(f"WRITE to {sds_address}:{sds_data_port} chunk={chunk_id} offset={offset_bytes} len={len(data_bytes)}")
            
            # Connect to SDS
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout_seconds)
            sock.connect((sds_address, sds_data_port))
            
            # Send request
            self.protocol.send_message(sock, request)
            
            # Receive response
            response = self.protocol.receive_message(sock)
            sock.close()
            
            if not response:
                return False, "Empty response from SDS"
            
            if not response.get("ok"):
                error_msg = response.get("error", "Unknown SDS error")
                logger.error(f"Write failed: {error_msg}")
                return False, error_msg
            
            logger.debug(f"Write successful: {len(data_bytes)} bytes to {sds_address}:{sds_data_port}")
            return True, None
        
        except socket.timeout:
            logger.error(f"Write timeout to {sds_address}:{sds_data_port}")
            return False, f"Timeout connecting to SDS {sds_address}:{sds_data_port}"
        
        except ConnectionRefusedError:
            logger.error(f"Connection refused by {sds_address}:{sds_data_port}")
            return False, f"SDS {sds_address}:{sds_data_port} not available"
        
        except Exception as e:
            logger.error(f"Write error: {e}", exc_info=True)
            return False, str(e)
    
    def execute_io_plan(
        self,
        io_plan: Dict[str, Any],
        token: Dict[str, Any],
        data_bytes: Optional[bytes] = None
    ) -> Tuple[bool, Optional[bytes], Optional[str]]:
        """
        Execute full IO plan (multi-replica read/write).
        
        For reads: Try first replica, fall back to others on failure.
        For writes: Write to all replicas (according to plan).
        
        Args:
            io_plan: IO plan from MDM token (contains replica list)
            token: Authorization token
            data_bytes: Data to write (for WRITE operations, None for READ)
        
        Returns:
            (success, data_bytes_or_None, error_message)
        """
        operation = io_plan.get("operation")
        replicas = io_plan.get("replicas", [])
        
        if not replicas:
            return False, None, "No replicas in IO plan"
        
        if operation == "READ":
            # Try each replica until success
            for replica in replicas:
                success, data, error = self.execute_read(
                    sds_address=replica["sds_address"],
                    sds_data_port=replica["sds_data_port"],
                    volume_id=replica["volume_id"],
                    chunk_id=replica["chunk_id"],
                    offset_bytes=replica["offset_bytes"],
                    length_bytes=replica["length_bytes"],
                    token=token
                )
                
                if success:
                    return True, data, None
                
                logger.warning(f"Read from replica {replica['sds_address']}:{replica['sds_data_port']} failed: {error}")
            
            return False, None, "All read replicas failed"
        
        elif operation == "WRITE":
            if data_bytes is None:
                return False, None, "No data provided for write"
            
            # Write to all replicas
            success_count = 0
            errors = []
            
            for replica in replicas:
                success, error = self.execute_write(
                    sds_address=replica["sds_address"],
                    sds_data_port=replica["sds_data_port"],
                    volume_id=replica["volume_id"],
                    chunk_id=replica["chunk_id"],
                    offset_bytes=replica["offset_bytes"],
                    data_bytes=data_bytes,
                    token=token
                )
                
                if success:
                    success_count += 1
                else:
                    errors.append(f"{replica['sds_address']}:{replica['sds_data_port']}: {error}")
            
            if success_count == 0:
                return False, None, f"All write replicas failed: {'; '.join(errors)}"
            
            if success_count < len(replicas):
                logger.warning(f"Partial write success: {success_count}/{len(replicas)} replicas")
            
            return True, None, None
        
        else:
            return False, None, f"Unknown operation: {operation}"
