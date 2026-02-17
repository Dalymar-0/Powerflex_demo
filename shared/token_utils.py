"""
IO Authorization Token Utilities (Phase 4)

HMAC-SHA256 based token signing and verification for IO authorization.
Uses stdlib only - no external crypto libraries.
"""

from __future__ import annotations

import hmac
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional


def generate_token_id() -> str:
    """Generate unique token ID (UUID4)"""
    return str(uuid.uuid4())


def sign_token(
    token_id: str,
    volume_id: int,
    operation: str,
    cluster_secret: str,
    offset_bytes: int = 0,
    length_bytes: int = 0
) -> str:
    """
    Sign an IO token with HMAC-SHA256.
    
    Signature includes:
    - token_id (UUID4 uniqueness)
    - volume_id (bind to specific volume)
    - operation (read/write)
    - offset_bytes (bind to specific IO range)
    - length_bytes (bind to specific IO size)
    - cluster_secret (shared secret)
    
    Args:
        token_id: Unique token identifier (UUID4)
        volume_id: Volume ID for this IO
        operation: 'read' or 'write'
        cluster_secret: Shared cluster secret
        offset_bytes: IO offset in bytes
        length_bytes: IO length in bytes
    
    Returns:
        Hex-encoded HMAC-SHA256 signature (64 hex chars)
    """
    message = f"{token_id}|{volume_id}|{operation}|{offset_bytes}|{length_bytes}".encode()
    signature = hmac.new(
        cluster_secret.encode(),
        message,
        hashlib.sha256
    ).hexdigest()
    return signature


def verify_token(
    token_id: str,
    volume_id: int,
    operation: str,
    signature: str,
    cluster_secret: str,
    offset_bytes: int = 0,
    length_bytes: int = 0
) -> bool:
    """
    Verify an IO token signature.
    
    Args:
        token_id: Token ID from request
        volume_id: Volume ID from request
        operation: Operation from request ('read' or 'write')
        signature: Signature to verify
        cluster_secret: Shared cluster secret
        offset_bytes: IO offset from request
        length_bytes: IO length from request
    
    Returns:
        True if signature is valid, False otherwise
    """
    expected_signature = sign_token(
        token_id, volume_id, operation, cluster_secret, offset_bytes, length_bytes
    )
    
    # Use hmac.compare_digest to prevent timing attacks
    return hmac.compare_digest(signature, expected_signature)


def is_token_expired(expires_at: datetime) -> bool:
    """Check if token has expired"""
    return datetime.now(timezone.utc) > expires_at


def compute_token_expiry(ttl_seconds: int = 300) -> datetime:
    """
    Compute token expiry timestamp.
    
    Args:
        ttl_seconds: Time to live in seconds (default: 5 minutes)
    
    Returns:
        Expiry timestamp (UTC)
    """
    return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)


def build_token_payload(
    token_id: str,
    volume_id: int,
    sdc_id: int,
    operation: str,
    offset_bytes: int,
    length_bytes: int,
    signature: str,
    expires_at: datetime,
    io_plan: Dict
) -> Dict:
    """
    Build complete token payload for transmission.
    
    This is what MDM sends to SDC, and SDC forwards to SDS.
    
    Args:
        token_id: Unique token ID
        volume_id: Volume ID
        sdc_id: SDC client ID
        operation: 'read' or 'write'
        offset_bytes: IO offset
        length_bytes: IO length
        signature: HMAC signature
        expires_at: Expiry timestamp
        io_plan: IO execution plan (chunk→SDS mappings)
    
    Returns:
        Complete token dict
    """
    return {
        "token_id": token_id,
        "volume_id": volume_id,
        "sdc_id": sdc_id,
        "operation": operation,
        "offset_bytes": offset_bytes,
        "length_bytes": length_bytes,
        "signature": signature,
        "expires_at": expires_at.isoformat(),
        "io_plan": io_plan
    }


def parse_token_payload(payload: Dict) -> Dict:
    """
    Parse and validate token payload structure.
    
    Args:
        payload: Token dict
    
    Returns:
        Validated token dict with parsed expires_at
    
    Raises:
        ValueError: If payload is missing required fields
    """
    required_fields = [
        "token_id", "volume_id", "sdc_id", "operation",
        "offset_bytes", "length_bytes", "signature", "expires_at"
    ]
    
    for field in required_fields:
        if field not in payload:
            raise ValueError(f"Token payload missing required field: {field}")
    
    # Parse ISO timestamp
    try:
        payload["expires_at"] = datetime.fromisoformat(payload["expires_at"])
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid expires_at timestamp: {e}")
    
    return payload


def validate_token_for_io(
    token: Dict,
    volume_id: int,
    operation: str,
    cluster_secret: str,
    offset_bytes: Optional[int] = None,
    length_bytes: Optional[int] = None
) -> tuple[bool, Optional[str]]:
    """
    Validate token for IO execution.
    
    Checks:
    1. Token not expired
    2. Signature valid
    3. Volume ID matches
    4. Operation matches
    5. Offset/length matches (if provided)
    
    Args:
        token: Parsed token dict
        volume_id: Expected volume ID
        operation: Expected operation ('read' or 'write')
        cluster_secret: Shared cluster secret
        offset_bytes: Expected offset (None to skip check)
        length_bytes: Expected length (None to skip check)
    
    Returns:
        (is_valid: bool, error_message: Optional[str])
    """
    # Check expiry
    if is_token_expired(token["expires_at"]):
        return False, "Token expired"
    
    # Check volume ID
    if token["volume_id"] != volume_id:
        return False, f"Token volume mismatch: expected {volume_id}, got {token['volume_id']}"
    
    # Check operation
    if token["operation"] != operation:
        return False, f"Token operation mismatch: expected {operation}, got {token['operation']}"
    
    # Check offset/length if provided
    if offset_bytes is not None and token["offset_bytes"] != offset_bytes:
        return False, f"Token offset mismatch: expected {offset_bytes}, got {token['offset_bytes']}"
    
    if length_bytes is not None and token["length_bytes"] != length_bytes:
        return False, f"Token length mismatch: expected {length_bytes}, got {token['length_bytes']}"
    
    # Verify signature
    is_valid = verify_token(
        token["token_id"],
        token["volume_id"],
        token["operation"],
        token["signature"],
        cluster_secret,
        token["offset_bytes"],
        token["length_bytes"]
    )
    
    if not is_valid:
        return False, "Invalid token signature"
    
    return True, None
