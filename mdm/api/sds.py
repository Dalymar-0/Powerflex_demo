from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from mdm.database import SessionLocal
from mdm.models import SDSNode, SDSNodeState
from mdm.services.capability_guard import validate_node_capability
from mdm.logic import fail_sds_node, recover_sds_node
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SDSCreate(BaseModel):
    name: str
    total_capacity_gb: float
    devices: str
    protection_domain_id: int
    cluster_node_id: str

@router.post("/sds/add")
def add_sds(sds: SDSCreate, db: Session = Depends(get_db)):
    ok, msg, _ = validate_node_capability(db, sds.cluster_node_id, "SDS", require_active=True)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    sds_obj = SDSNode(
        name=sds.name,
        total_capacity_gb=sds.total_capacity_gb,
        used_capacity_gb=0,
        state=SDSNodeState.UP,
        devices=sds.devices,
        protection_domain_id=sds.protection_domain_id,
        cluster_node_id=sds.cluster_node_id,
    )
    try:
        db.add(sds_obj)
        db.commit()
        db.refresh(sds_obj)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"SDS '{sds.name}' already exists or references invalid PD")
    return {"id": sds_obj.id, "name": sds_obj.name}

@router.get("/sds/list")
def list_sds(db: Session = Depends(get_db)):
    sds_nodes = db.scalars(select(SDSNode)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "state": s.state,
            "cluster_node_id": s.cluster_node_id,
            "protection_domain_id": s.protection_domain_id,
            "total_capacity_gb": s.total_capacity_gb,
            "used_capacity_gb": s.used_capacity_gb,
            "devices": s.devices,
        }
        for s in sds_nodes
    ]


@router.get("/sds/{sds_id}")
def get_sds(sds_id: int, db: Session = Depends(get_db)):
    sds = db.get(SDSNode, sds_id)
    if not sds:
        raise HTTPException(status_code=404, detail="SDS not found")
    return {
        "id": sds.id,
        "name": sds.name,
        "state": sds.state,
        "cluster_node_id": sds.cluster_node_id,
        "protection_domain_id": sds.protection_domain_id,
        "total_capacity_gb": sds.total_capacity_gb,
        "used_capacity_gb": sds.used_capacity_gb,
        "devices": sds.devices,
        "ip_address": sds.ip_address,
        "port": sds.port,
    }

@router.post("/sds/{sds_id}/fail")
def fail_sds(sds_id: int, db: Session = Depends(get_db)):
    sds = db.get(SDSNode, sds_id)
    if not sds:
        raise HTTPException(status_code=404, detail="SDS not found")
    try:
        message = fail_sds_node(sds_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    refreshed = db.get(SDSNode, sds_id)
    return {
        "id": sds_id,
        "state": getattr(refreshed, "state", SDSNodeState.DOWN),
        "message": message,
    }

@router.post("/sds/{sds_id}/recover")
def recover_sds(sds_id: int, db: Session = Depends(get_db)):
    sds = db.get(SDSNode, sds_id)
    if not sds:
        raise HTTPException(status_code=404, detail="SDS not found")
    try:
        message = recover_sds_node(sds_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    refreshed = db.get(SDSNode, sds_id)
    return {
        "id": sds_id,
        "state": getattr(refreshed, "state", SDSNodeState.UP),
        "message": message,
    }
