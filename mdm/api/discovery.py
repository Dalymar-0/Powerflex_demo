"""
MDM Discovery & Registration API (Phase 2)

Components register with MDM on boot to join the cluster and discover peers.
MDM acts as the central registry for all component addresses and capabilities.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import hashlib
import json
import logging

from mdm.database import SessionLocal
from mdm.models import ComponentRegistry, ClusterConfig

router = APIRouter(prefix="/discovery", tags=["discovery"])
logger = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    """Component registration request"""
    component_id: str  # e.g., 'sds-10.0.1.10', 'sdc-vm42', 'mdm-primary'
    component_type: str  # 'MDM', 'SDS', 'SDC', 'MGMT'
    address: Optional[str] = None
    network_address: Optional[str] = None
    control_port: Optional[int] = None
    data_port: Optional[int] = None
    mgmt_port: Optional[int] = None
    ports: Optional[dict] = None
    metadata: Optional[dict] = None  # Component-specific metadata (devices, capacity, etc.)
    auth_token: Optional[str] = None  # SHA256(cluster_secret + component_id) for authentication


class RegisterResponse(BaseModel):
    """Registration response with cluster membership info"""
    status: str  # 'registered', 'updated', 'rejected'
    component_id: str
    cluster_name: str
    cluster_secret: Optional[str] = None  # Returned only on first registration
    message: str


class ComponentInfo(BaseModel):
    """Component information for topology queries"""
    component_id: str
    component_type: str
    address: str
    control_port: Optional[int] = None
    data_port: Optional[int] = None
    mgmt_port: Optional[int] = None
    status: str
    registered_at: datetime
    last_heartbeat_at: datetime
    metadata: Optional[dict] = None


class TopologyResponse(BaseModel):
    """Complete cluster topology"""
    cluster_name: str
    components: List[ComponentInfo]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_cluster_config(db: Session, key: str) -> Optional[str]:
    """Fetch cluster config value by key"""
    config = db.scalars(select(ClusterConfig).where(ClusterConfig.key == key)).first()
    return config.value if config else None


def verify_auth_token(component_id: str, auth_token: str, cluster_secret: str) -> bool:
    """Verify component authentication token"""
    if not auth_token:
        return False
    expected = hashlib.sha256(f"{cluster_secret}{component_id}".encode()).hexdigest()
    return auth_token == expected


@router.post("/register", response_model=RegisterResponse)
def register_component(request: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a component with the MDM discovery registry.
    
    First-time registration:
    - Component sends component_id, type, address, ports
    - MDM returns cluster_secret + cluster_name
    - Component stores cluster_secret and uses it for subsequent auth
    
    Subsequent registrations (after restart):
    - Component sends auth_token = SHA256(cluster_secret + component_id)
    - MDM verifies token and updates registration
    """
    
    # Get cluster config
    cluster_name = get_cluster_config(db, "cluster_name") or "powerflex_cluster_default"
    cluster_secret = get_cluster_config(db, "cluster_secret")
    
    if not cluster_secret:
        raise HTTPException(status_code=500, detail="Cluster secret not initialized. Run init_db().")

    address = request.address or request.network_address
    if not address:
        raise HTTPException(status_code=422, detail="address is required")

    ports = request.ports if isinstance(request.ports, dict) else {}
    control_port = request.control_port or ports.get("control")
    data_port = request.data_port or ports.get("data")
    mgmt_port = request.mgmt_port or ports.get("mgmt")
    
    # Check if component already registered
    existing = db.scalars(select(ComponentRegistry).where(
        ComponentRegistry.component_id == request.component_id
    )).first()
    
    if existing:
        # Verify auth token for existing components when provided.
        # For legacy agents that do not send auth_token, allow re-registration.
        if request.auth_token and not verify_auth_token(request.component_id, request.auth_token, cluster_secret):
            raise HTTPException(
                status_code=403,
                detail="Invalid auth token. Re-registration requires valid authentication."
            )
        if not request.auth_token:
            logger.warning("Legacy re-registration without auth_token accepted for component %s", request.component_id)
        
        # Update existing registration
        existing.address = address
        existing.control_port = control_port
        existing.data_port = data_port
        existing.mgmt_port = mgmt_port
        existing.status = "ACTIVE"
        existing.last_heartbeat_at = datetime.utcnow()
        if request.metadata:
            existing.metadata_json = json.dumps(request.metadata)
        
        db.commit()
        
        return RegisterResponse(
            status="updated",
            component_id=request.component_id,
            cluster_name=cluster_name,
            cluster_secret=cluster_secret,
            message=f"Component {request.component_id} re-registered successfully"
        )
    
    else:
        # First-time registration - create new entry
        auth_token_hash = hashlib.sha256(f"{cluster_secret}{request.component_id}".encode()).hexdigest()
        
        new_component = ComponentRegistry(
            component_id=request.component_id,
            component_type=request.component_type.upper(),
            address=address,
            control_port=control_port,
            data_port=data_port,
            mgmt_port=mgmt_port,
            status="ACTIVE",
            cluster_name=cluster_name,
            auth_token_hash=auth_token_hash,
            metadata_json=json.dumps(request.metadata) if request.metadata else None,
            registered_at=datetime.utcnow(),
            last_heartbeat_at=datetime.utcnow()
        )
        
        db.add(new_component)
        db.commit()
        db.refresh(new_component)
        
        return RegisterResponse(
            status="registered",
            component_id=request.component_id,
            cluster_name=cluster_name,
            cluster_secret=cluster_secret,  # Send secret on first registration
            message=f"Component {request.component_id} registered successfully. Store cluster_secret securely."
        )


@router.get("/topology", response_model=TopologyResponse)
def get_topology(db: Session = Depends(get_db)):
    """
    Get complete cluster topology (all registered components).
    Used by MGMT for monitoring and by components for peer discovery.
    """
    cluster_name = get_cluster_config(db, "cluster_name") or "powerflex_cluster_default"
    
    components = db.scalars(select(ComponentRegistry)).all()
    
    component_list = []
    for comp in components:
        metadata = json.loads(comp.metadata_json) if comp.metadata_json else None
        component_list.append(ComponentInfo(
            component_id=comp.component_id,
            component_type=comp.component_type,
            address=comp.address,
            control_port=comp.control_port,
            data_port=comp.data_port,
            mgmt_port=comp.mgmt_port,
            status=comp.status,
            registered_at=comp.registered_at,
            last_heartbeat_at=comp.last_heartbeat_at,
            metadata=metadata
        ))
    
    return TopologyResponse(
        cluster_name=cluster_name,
        components=component_list
    )


@router.get("/peers/{component_type}", response_model=List[ComponentInfo])
def get_peers_by_type(component_type: str, db: Session = Depends(get_db)):
    """
    Get all components of a specific type (e.g., all SDS nodes, all SDC clients).
    Used by components to discover peers without fetching full topology.
    """
    components = db.scalars(select(ComponentRegistry).where(
        ComponentRegistry.component_type == component_type.upper(),
        ComponentRegistry.status == "ACTIVE"
    )).all()
    
    result = []
    for comp in components:
        metadata = json.loads(comp.metadata_json) if comp.metadata_json else None
        result.append(ComponentInfo(
            component_id=comp.component_id,
            component_type=comp.component_type,
            address=comp.address,
            control_port=comp.control_port,
            data_port=comp.data_port,
            mgmt_port=comp.mgmt_port,
            status=comp.status,
            registered_at=comp.registered_at,
            last_heartbeat_at=comp.last_heartbeat_at,
            metadata=metadata
        ))
    
    return result


@router.post("/heartbeat/{component_id}")
def component_heartbeat(component_id: str, db: Session = Depends(get_db)):
    """
    Update component heartbeat timestamp.
    Called periodically by all components to indicate liveness.
    """
    component = db.scalars(select(ComponentRegistry).where(
        ComponentRegistry.component_id == component_id
    )).first()
    
    if not component:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not registered")
    
    component.last_heartbeat_at = datetime.utcnow()
    component.status = "ACTIVE"
    db.commit()
    
    return {"status": "ok", "component_id": component_id, "timestamp": component.last_heartbeat_at}


@router.delete("/unregister/{component_id}")
def unregister_component(component_id: str, db: Session = Depends(get_db)):
    """
    Remove component from registry (graceful shutdown).
    Component should call this before shutting down cleanly.
    """
    component = db.scalars(select(ComponentRegistry).where(
        ComponentRegistry.component_id == component_id
    )).first()
    
    if not component:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not registered")
    
    db.delete(component)
    db.commit()
    
    return {"status": "unregistered", "component_id": component_id}
