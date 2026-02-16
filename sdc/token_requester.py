"""
SDC Token Requester - Phase 6

Request IO authorization tokens from MDM before executing operations.
Every IO (read/write) requires a fresh token from MDM's token authority.

Token Lifecycle:
1. SDC receives IO request from NBD client
2. SDC requests token from MDM POST /io/authorize
3. SDC executes IO to SDS with token
4. SDS verifies token with MDM
5. SDS ACKs transaction to MDM
6. Token marked CONSUMED

This module handles step 2: token acquisition.
"""

import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class TokenRequester:
    """Request IO tokens from MDM token authority"""
    
    def __init__(self, mdm_address: str, mdm_port: int, sdc_id: int):
        """
        Initialize token requester.
        
        Args:
            mdm_address: MDM host address
            mdm_port: MDM API port (default 8001)
            sdc_id: This SDC's ID from registration
        """
        self.mdm_base_url = f"http://{mdm_address}:{mdm_port}"
        self.sdc_id = sdc_id
        self.token_endpoint = f"{self.mdm_base_url}/io/authorize"
        logger.info(f"Token requester initialized for SDC {sdc_id} → MDM {self.mdm_base_url}")
    
    def request_token(
        self,
        volume_id: int,
        operation: str,
        offset_bytes: int,
        length_bytes: int,
        io_plan: Optional[Dict[str, Any]] = None,
        ttl_seconds: int = 300
    ) -> Optional[Dict[str, Any]]:
        """
        Request IO authorization token from MDM.
        
        Args:
            volume_id: Volume ID to access
            operation: 'READ' or 'WRITE'
            offset_bytes: IO offset
            length_bytes: IO length
            io_plan: Optional pre-computed IO plan (for optimization)
            ttl_seconds: Token TTL (default 300s)
        
        Returns:
            Token payload dict with:
            {
                "token_id": str,
                "volume_id": int,
                "operation": str,
                "offset_bytes": int,
                "length_bytes": int,
                "expires_at": str (ISO timestamp),
                "signature": str (HMAC-SHA256),
                "io_plan": {...}
            }
            
            Returns None if request fails.
        """
        request_payload = {
            "volume_id": volume_id,
            "sdc_id": self.sdc_id,
            "operation": operation,
            "offset_bytes": offset_bytes,
            "length_bytes": length_bytes,
            "ttl_seconds": ttl_seconds
        }
        
        if io_plan:
            request_payload["io_plan"] = io_plan
        
        try:
            logger.debug(f"Requesting token: {operation} vol={volume_id} offset={offset_bytes} len={length_bytes}")
            
            response = requests.post(
                self.token_endpoint,
                json=request_payload,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Token request failed: {response.status_code} {response.text}")
                return None
            
            token_data = response.json()
            
            logger.debug(f"Token acquired: {token_data.get('token_id')} expires={token_data.get('expires_at')}")
            
            return token_data
        
        except requests.exceptions.Timeout:
            logger.error(f"Token request timeout to MDM {self.mdm_base_url}")
            return None
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to MDM {self.mdm_base_url}: {e}")
            return None
        
        except Exception as e:
            logger.error(f"Token request error: {e}", exc_info=True)
            return None
    
    def cache_token(self, token_data: Dict[str, Any], db_session):
        """
        Cache token locally for replay detection.
        
        Args:
            token_data: Token payload from MDM
            db_session: SDC local database session
        """
        from sdc.models import TokenCache
        from datetime import datetime
        
        try:
            cached_token = TokenCache(
                token_id=token_data["token_id"],
                volume_id=token_data["volume_id"],
                operation=token_data["operation"],
                offset_bytes=token_data.get("offset_bytes", 0),
                length_bytes=token_data.get("length_bytes", 0),
                issued_at=datetime.fromisoformat(token_data["issued_at"]) if "issued_at" in token_data else datetime.utcnow(),
                expires_at=datetime.fromisoformat(token_data["expires_at"])
            )
            
            db_session.add(cached_token)
            db_session.commit()
            
            logger.debug(f"Token {token_data['token_id']} cached locally")
        
        except Exception as e:
            logger.error(f"Token caching failed: {e}")
            db_session.rollback()
    
    def is_token_cached(self, token_id: str, db_session) -> bool:
        """Check if token already used (replay detection)"""
        from sdc.models import TokenCache
        
        cached = db_session.query(TokenCache).filter(
            TokenCache.token_id == token_id
        ).first()
        
        return cached is not None
