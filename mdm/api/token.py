"""
MDM Token API (Phase 4)

Endpoints for IO authorization token issuance and transaction ACKs.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Dict, List
from datetime import datetime

from mdm.database import SessionLocal
from mdm.token_authority import TokenAuthority, get_cluster_secret
from mdm.models import IOToken, IOTransactionAck

router = APIRouter(prefix="/io", tags=["io-tokens"])


class TokenRequest(BaseModel):
    """Request for IO authorization token"""
    volume_id: int
    sdc_id: int
    operation: str  # 'read' or 'write'
    offset_bytes: int
    length_bytes: int
    io_plan: Dict  # Chunk→SDS mappings from existing volume.py logic
    ttl_seconds: Optional[int] = 300  # Default 5 minutes


class TokenResponse(BaseModel):
    """IO authorization token response"""
    token_id: str
    volume_id: int
    sdc_id: int
    operation: str
    offset_bytes: int
    length_bytes: int
    signature: str
    expires_at: str  # ISO timestamp
    io_plan: Dict
    status: str


class TransactionAckRequest(BaseModel):
    """Transaction acknowledgment from SDS"""
    token_id: str
    sds_id: int
    success: bool
    bytes_processed: Optional[int] = None
    error_message: Optional[str] = None
    execution_duration_ms: Optional[float] = None
    replica_id: Optional[int] = None
    sds_address: Optional[str] = None
    metadata: Optional[Dict] = None


class TransactionAckResponse(BaseModel):
    """ACK reception confirmation"""
    ack_id: int
    token_id: str
    status: str
    message: str


class TokenStatsResponse(BaseModel):
    """Token statistics"""
    tokens: Dict
    acks: Dict


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/authorize", response_model=TokenResponse)
def authorize_io(request: TokenRequest, db: Session = Depends(get_db)):
    """
    Issue IO authorization token.
    
    Called by SDC before executing IO. SDC must include this token
    in all subsequent IO frames to SDS.
    
    Workflow:
    1. SDC requests token from MDM (this endpoint)
    2. MDM validates request and generates signed token
    3. SDC receives token + IO plan
    4. SDC sends IO + token to SDS data port
    5. SDS verifies token before touching disk
    6. SDS sends ACK to MDM after execution
    """
    try:
        cluster_secret = get_cluster_secret(db)
        authority = TokenAuthority(db, cluster_secret)
        
        # Issue token
        token_payload = authority.issue_token(
            volume_id=request.volume_id,
            sdc_id=request.sdc_id,
            operation=request.operation,
            offset_bytes=request.offset_bytes,
            length_bytes=request.length_bytes,
            io_plan=request.io_plan,
            ttl_seconds=request.ttl_seconds if request.ttl_seconds is not None else 300
        )
        
        return TokenResponse(
            token_id=token_payload["token_id"],
            volume_id=token_payload["volume_id"],
            sdc_id=token_payload["sdc_id"],
            operation=token_payload["operation"],
            offset_bytes=token_payload["offset_bytes"],
            length_bytes=token_payload["length_bytes"],
            signature=token_payload["signature"],
            expires_at=token_payload["expires_at"],
            io_plan=token_payload["io_plan"],
            status="ISSUED"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token issuance failed: {str(e)}")


@router.post("/tx/ack", response_model=TransactionAckResponse)
def acknowledge_transaction(request: TransactionAckRequest, db: Session = Depends(get_db)):
    """
    Record transaction ACK from SDS.
    
    Called by SDS after IO execution to confirm completion.
    Updates token status and records execution metrics.
    
    Workflow:
    1. SDS receives IO request with token from SDC
    2. SDS verifies token signature
    3. SDS executes IO (write/read to disk)
    4. SDS sends ACK to MDM (this endpoint)
    5. MDM records ACK and marks token consumed
    """
    try:
        cluster_secret = get_cluster_secret(db)
        authority = TokenAuthority(db, cluster_secret)
        
        # Verify token exists
        token = authority.get_token(request.token_id)
        if not token:
            raise HTTPException(status_code=404, detail=f"Token {request.token_id} not found")
        
        # Record ACK
        ack = authority.record_transaction_ack(
            token_id=request.token_id,
            sds_id=request.sds_id,
            success=request.success,
            bytes_processed=request.bytes_processed,
            error_message=request.error_message,
            execution_duration_ms=request.execution_duration_ms,
            replica_id=request.replica_id,
            sds_address=request.sds_address,
            metadata=request.metadata
        )
        
        return TransactionAckResponse(
            ack_id=ack.id,
            token_id=request.token_id,
            status="ACK_RECORDED",
            message=f"{'Success' if request.success else 'Failure'} ACK recorded for token {request.token_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ACK recording failed: {str(e)}")


@router.get("/token/{token_id}")
def get_token_info(token_id: str, db: Session = Depends(get_db)):
    """Get token details (for debugging/monitoring)"""
    token = db.scalars(select(IOToken).where(IOToken.token_id == token_id)).first()
    if not token:
        raise HTTPException(status_code=404, detail=f"Token {token_id} not found")
    
    return {
        "token_id": token.token_id,
        "volume_id": token.volume_id,
        "sdc_id": token.sdc_id,
        "operation": token.operation,
        "offset_bytes": token.offset_bytes,
        "length_bytes": token.length_bytes,
        "status": token.status,
        "issued_at": token.issued_at.isoformat(),
        "expires_at": token.expires_at.isoformat(),
        "consumed_at": token.consumed_at.isoformat() if token.consumed_at else None
    }


@router.get("/token/{token_id}/acks")
def get_token_acks(token_id: str, db: Session = Depends(get_db)):
    """Get all ACKs for a token"""
    acks = db.scalars(select(IOTransactionAck).where(IOTransactionAck.token_id == token_id)).all()
    
    return {
        "token_id": token_id,
        "ack_count": len(acks),
        "acks": [
            {
                "ack_id": ack.id,
                "sds_id": ack.sds_id,
                "success": ack.success,
                "bytes_processed": ack.bytes_processed,
                "error_message": ack.error_message,
                "execution_duration_ms": ack.execution_duration_ms,
                "received_at": ack.received_at.isoformat()
            }
            for ack in acks
        ]
    }


@router.get("/stats", response_model=TokenStatsResponse)
def get_token_stats(db: Session = Depends(get_db)):
    """Get token system statistics"""
    try:
        cluster_secret = get_cluster_secret(db)
        authority = TokenAuthority(db, cluster_secret)
        stats = authority.get_token_stats()
        return TokenStatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats retrieval failed: {str(e)}")


@router.post("/cleanup/expired")
def cleanup_expired_tokens(db: Session = Depends(get_db)):
    """
    Cleanup expired tokens (admin/cron endpoint).
    
    Marks expired tokens as EXPIRED. Should be called periodically
    by a background job or cron.
    """
    try:
        cluster_secret = get_cluster_secret(db)
        authority = TokenAuthority(db, cluster_secret)
        count = authority.cleanup_expired_tokens()
        return {
            "status": "cleanup_complete",
            "expired_tokens_marked": count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


@router.delete("/token/{token_id}/revoke")
def revoke_token(token_id: str, db: Session = Depends(get_db)):
    """
    Revoke a token (admin action).
    
    Marks token as REVOKED. Any subsequent use will be rejected by SDS.
    """
    try:
        cluster_secret = get_cluster_secret(db)
        authority = TokenAuthority(db, cluster_secret)
        
        if authority.revoke_token(token_id):
            return {
                "status": "revoked",
                "token_id": token_id,
                "message": f"Token {token_id} revoked successfully"
            }
        else:
            raise HTTPException(status_code=404, detail=f"Token {token_id} not found")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Revocation failed: {str(e)}")
