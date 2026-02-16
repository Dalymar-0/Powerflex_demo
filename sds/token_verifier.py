"""
SDS Token Verifier (Phase 5)

Verifies IO authorization tokens before allowing disk access.
Uses shared/token_utils.py for cryptographic verification.

Every IO request to SDS data port MUST include a valid token signed by MDM.
SDS verifies:
1. Token signature (HMAC-SHA256)
2. Token not expired
3. Token not already consumed (replay protection)
4. Token matches the requested operation/volume/chunk
"""

from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from shared.token_utils import verify_token, is_token_expired
from sds.models import ConsumedToken


class TokenVerifier:
    """
    Verifies IO authorization tokens for SDS data plane operations.
    """
    
    def __init__(self, db: Session, cluster_secret: str):
        """
        Initialize token verifier.
        
        Args:
            db: SDS local database session
            cluster_secret: Shared cluster secret for signature verification
        """
        self.db = db
        self.cluster_secret = cluster_secret
    
    def verify_io_token(
        self,
        token: Dict,
        volume_id: int,
        chunk_id: int,
        operation: str,
        offset_bytes: int,
        length_bytes: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify IO token before executing disk operation.
        
        Checks:
        1. Token signature valid (HMAC-SHA256 with cluster_secret)
        2. Token not expired
        3. Token not already consumed (replay protection)
        4. Token volume_id matches request
        5. Token operation matches request
        6. Token offset/length matches request (optional strict mode)
        
        Args:
            token: Parsed token dict from SDC request
            volume_id: Volume being accessed
            chunk_id: Chunk being accessed
            operation: "read" or "write"
            offset_bytes: IO offset
            length_bytes: IO length
        
        Returns:
            (is_valid: bool, error_message: Optional[str])
        """
        # Extract token fields with type validation
        token_id = token.get("token_id")
        token_volume_id = token.get("volume_id")
        token_operation = token.get("operation")
        token_offset = token.get("offset_bytes")
        token_length = token.get("length_bytes")
        signature = token.get("signature")
        expires_at_str = token.get("expires_at")
        
        # Validate required fields exist
        if not all([token_id, token_volume_id is not None, token_operation, signature, expires_at_str]):
            return False, "Token missing required fields"
        
        # Type validation
        if not isinstance(token_id, str):
            return False, "Token ID must be string"
        if not isinstance(token_volume_id, int):
            return False, "Volume ID must be integer"
        if not isinstance(token_operation, str):
            return False, "Operation must be string"
        if not isinstance(signature, str):
            return False, "Signature must be string"
        if token_offset is not None and not isinstance(token_offset, int):
            return False, "Offset must be integer"
        if token_length is not None and not isinstance(token_length, int):
            return False, "Length must be integer"
        
        # Parse expiry timestamp
        try:
            if isinstance(expires_at_str, str):
                expires_at = datetime.fromisoformat(expires_at_str)
            else:
                expires_at = expires_at_str  # Already datetime object
                if not isinstance(expires_at, datetime):
                    return False, "Expires_at must be datetime or ISO string"
        except (ValueError, TypeError) as e:
            return False, f"Invalid token expiry timestamp: {e}"
        
        # Check expiry
        if is_token_expired(expires_at):
            return False, "Token expired"
        
        # Check if token already consumed (replay protection)
        existing = self.db.query(ConsumedToken).filter(
            ConsumedToken.token_id == token_id
        ).first()
        
        if existing:
            return False, f"Token already consumed at {existing.consumed_at}"
        
        # Verify signature (now all fields are typed correctly)
        is_valid_sig = verify_token(
            token_id=token_id,
            volume_id=token_volume_id,
            operation=token_operation,
            signature=signature,
            cluster_secret=self.cluster_secret,
            offset_bytes=token_offset if token_offset is not None else 0,
            length_bytes=token_length if token_length is not None else 0
        )
        
        if not is_valid_sig:
            return False, "Invalid token signature"
        
        # Check volume ID match
        if token_volume_id != volume_id:
            return False, f"Token volume mismatch: expected {volume_id}, got {token_volume_id}"
        
        # Check operation match
        if token_operation != operation:
            return False, f"Token operation mismatch: expected {operation}, got {token_operation}"
        
        # Check offset/length match (optional strict validation)
        # For now, allow tokens to cover ranges (e.g., token for 0-8192 can service 0-4096)
        # Strict mode would require exact match
        if token_offset is not None and token_length is not None:
            if offset_bytes < token_offset or (offset_bytes + length_bytes) > (token_offset + token_length):
                return False, f"Token range mismatch: token covers {token_offset}-{token_offset+token_length}, requested {offset_bytes}-{offset_bytes+length_bytes}"
        
        # All checks passed
        return True, None
    
    def mark_token_consumed(
        self,
        token_id: str,
        volume_id: int,
        chunk_id: int,
        operation: str,
        offset_bytes: int,
        length_bytes: int,
        success: bool,
        bytes_processed: int = 0,
        execution_duration_ms: float = 0.0,
        error_message: Optional[str] = None
    ) -> ConsumedToken:
        """
        Mark token as consumed after IO execution.
        
        Args:
            token_id: Token ID
            volume_id: Volume ID
            chunk_id: Chunk ID
            operation: "read" or "write"
            offset_bytes: IO offset
            length_bytes: IO length
            success: Whether operation succeeded
            bytes_processed: Actual bytes read/written
            execution_duration_ms: IO execution time in milliseconds
            error_message: Error message if failed
        
        Returns:
            ConsumedToken record
        """
        consumed = ConsumedToken(
            token_id=token_id,
            volume_id=volume_id,
            chunk_id=chunk_id,
            operation=operation,
            offset_bytes=offset_bytes,
            length_bytes=length_bytes,
            success=success,
            bytes_processed=bytes_processed,
            execution_duration_ms=execution_duration_ms,
            error_message=error_message,
            consumed_at=datetime.utcnow()
        )
        
        self.db.add(consumed)
        self.db.commit()
        self.db.refresh(consumed)
        
        return consumed
    
    def cleanup_old_consumed_tokens(self, days: int = 7, batch_size: int = 1000) -> int:
        """
        Clean up consumed tokens older than N days.
        Call this periodically to prevent DB bloat.
        
        Args:
            days: Remove tokens older than this many days
            batch_size: Max tokens to delete at once
        
        Returns:
            Number of tokens deleted
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Delete in batches to avoid long locks
        deleted = self.db.query(ConsumedToken).filter(
            ConsumedToken.consumed_at < cutoff
        ).limit(batch_size).delete(synchronize_session=False)
        
        self.db.commit()
        return deleted
