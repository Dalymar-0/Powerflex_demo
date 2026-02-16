"""
MDM Token Authority (Phase 4)

Issues and tracks IO authorization tokens.
Every IO transaction requires a token signed by MDM and verified by SDS.
"""

import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Dict, List, Optional

from shared.token_utils import (
    generate_token_id, sign_token, compute_token_expiry,
    build_token_payload
)
from mdm.models import IOToken, IOTransactionAck, Volume, SDCClient, ClusterConfig


class TokenAuthority:
    """
    MDM Token Authority for IO authorization.
    
    Responsibilities:
    - Issue short-lived tokens for SDC IO requests
    - Track issued tokens in database
    - Receive and record transaction ACKs from SDS
    - Enforce token expiry and revocation
    """
    
    def __init__(self, db: Session, cluster_secret: str):
        """
        Initialize token authority.
        
        Args:
            db: SQLAlchemy database session
            cluster_secret: Shared cluster secret for signing
        """
        self.db = db
        self.cluster_secret = cluster_secret
    
    def issue_token(
        self,
        volume_id: int,
        sdc_id: int,
        operation: str,
        offset_bytes: int,
        length_bytes: int,
        io_plan: Dict,
        ttl_seconds: int = 300
    ) -> Dict:
        """
        Issue a new IO authorization token.
        
        Args:
            volume_id: Volume ID
            sdc_id: SDC client ID requesting IO
            operation: 'read' or 'write'
            offset_bytes: IO offset
            length_bytes: IO length
            io_plan: IO execution plan (chunk→SDS mappings)
            ttl_seconds: Token time-to-live (default: 5 minutes)
        
        Returns:
            Complete token payload dict
        
        Raises:
            ValueError: If volume or SDC not found, or invalid operation
        """
        # Validate operation
        if operation not in ("read", "write"):
            raise ValueError(f"Invalid operation: {operation}")
        
        # Verify volume exists
        volume = self.db.scalars(select(Volume).where(Volume.id == volume_id)).first()
        if not volume:
            raise ValueError(f"Volume {volume_id} not found")
        
        # Verify SDC exists
        sdc = self.db.scalars(select(SDCClient).where(SDCClient.id == sdc_id)).first()
        if not sdc:
            raise ValueError(f"SDC {sdc_id} not found")
        
        # Generate token
        token_id = generate_token_id()
        expires_at = compute_token_expiry(ttl_seconds)
        
        # Sign token
        signature = sign_token(
            token_id=token_id,
            volume_id=volume_id,
            operation=operation,
            cluster_secret=self.cluster_secret,
            offset_bytes=offset_bytes,
            length_bytes=length_bytes
        )
        
        # Store in database
        io_token = IOToken(
            token_id=token_id,
            volume_id=volume_id,
            sdc_id=sdc_id,
            operation=operation,
            offset_bytes=offset_bytes,
            length_bytes=length_bytes,
            issued_at=datetime.utcnow(),
            expires_at=expires_at,
            signature=signature,
            io_plan_json=json.dumps(io_plan),
            status="ISSUED"
        )
        
        self.db.add(io_token)
        self.db.commit()
        self.db.refresh(io_token)
        
        # Build payload
        payload = build_token_payload(
            token_id=token_id,
            volume_id=volume_id,
            sdc_id=sdc_id,
            operation=operation,
            offset_bytes=offset_bytes,
            length_bytes=length_bytes,
            signature=signature,
            expires_at=expires_at,
            io_plan=io_plan
        )
        
        return payload
    
    def get_token(self, token_id: str) -> Optional[IOToken]:
        """Fetch token by ID"""
        return self.db.scalars(select(IOToken).where(IOToken.token_id == token_id)).first()
    
    def mark_token_consumed(self, token_id: str) -> bool:
        """
        Mark token as consumed (SDS verified and executed).
        
        Args:
            token_id: Token ID
        
        Returns:
            True if marked successfully, False if token not found
        """
        token = self.get_token(token_id)
        if not token:
            return False
        
        token.status = "CONSUMED"
        token.consumed_at = datetime.utcnow()
        self.db.commit()
        return True
    
    def record_transaction_ack(
        self,
        token_id: str,
        sds_id: int,
        success: bool,
        bytes_processed: Optional[int] = None,
        error_message: Optional[str] = None,
        execution_duration_ms: Optional[float] = None,
        replica_id: Optional[int] = None,
        sds_address: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> IOTransactionAck:
        """
        Record transaction acknowledgment from SDS.
        
        Called by SDS after IO execution to confirm completion.
        
        Args:
            token_id: Token ID
            sds_id: SDS node that executed IO
            success: Whether IO succeeded
            bytes_processed: Actual bytes written/read
            error_message: Error message if failed
            execution_duration_ms: Execution time in milliseconds
            replica_id: Replica ID (if applicable)
            sds_address: SDS address for tracking
            metadata: Additional metadata (JSON)
        
        Returns:
            Created IOTransactionAck record
        """
        # Mark token as consumed if successful
        if success:
            self.mark_token_consumed(token_id)
        
        # Create ACK record
        ack = IOTransactionAck(
            token_id=token_id,
            sds_id=sds_id,
            replica_id=replica_id,
            success=success,
            error_message=error_message,
            bytes_processed=bytes_processed,
            received_at=datetime.utcnow(),
            execution_duration_ms=execution_duration_ms,
            sds_address=sds_address,
            metadata_json=json.dumps(metadata) if metadata else None
        )
        
        self.db.add(ack)
        self.db.commit()
        self.db.refresh(ack)
        
        return ack
    
    def get_token_acks(self, token_id: str) -> List[IOTransactionAck]:
        """Get all ACKs for a token"""
        return self.db.scalars(select(IOTransactionAck).where(
            IOTransactionAck.token_id == token_id
        )).all()
    
    def revoke_token(self, token_id: str) -> bool:
        """
        Revoke a token (admin action).
        
        Args:
            token_id: Token ID to revoke
        
        Returns:
            True if revoked, False if token not found
        """
        token = self.get_token(token_id)
        if not token:
            return False
        
        token.status = "REVOKED"
        self.db.commit()
        return True
    
    def cleanup_expired_tokens(self, batch_size: int = 1000) -> int:
        """
        Mark expired tokens as EXPIRED (periodic cleanup job).
        
        Args:
            batch_size: Max tokens to process per call
        
        Returns:
            Number of tokens marked as expired
        """
        expired = self.db.scalars(select(IOToken).where(
            IOToken.status == "ISSUED",
            IOToken.expires_at < datetime.utcnow()
        ).limit(batch_size)).all()
        
        for token in expired:
            token.status = "EXPIRED"
        
        self.db.commit()
        return len(expired)
    
    def get_token_stats(self) -> Dict:
        """Get token statistics (for monitoring)"""
        total = self.db.scalar(select(func.count()).select_from(IOToken))
        issued = self.db.scalar(select(func.count()).select_from(IOToken).where(IOToken.status == "ISSUED"))
        consumed = self.db.scalar(select(func.count()).select_from(IOToken).where(IOToken.status == "CONSUMED"))
        expired = self.db.scalar(select(func.count()).select_from(IOToken).where(IOToken.status == "EXPIRED"))
        revoked = self.db.scalar(select(func.count()).select_from(IOToken).where(IOToken.status == "REVOKED"))
        
        total_acks = self.db.scalar(select(func.count()).select_from(IOTransactionAck))
        successful_acks = self.db.scalar(select(func.count()).select_from(IOTransactionAck).where(
            IOTransactionAck.success == True
        ))
        
        return {
            "tokens": {
                "total": total,
                "issued": issued,
                "consumed": consumed,
                "expired": expired,
                "revoked": revoked
            },
            "acks": {
                "total": total_acks,
                "successful": successful_acks,
                "failed": total_acks - successful_acks
            }
        }


def get_cluster_secret(db: Session) -> str:
    """Helper to fetch cluster_secret from config"""
    config = db.scalars(select(ClusterConfig).where(ClusterConfig.key == "cluster_secret")).first()
    if not config:
        raise ValueError("Cluster secret not configured. Run init_db().")
    return config.value
