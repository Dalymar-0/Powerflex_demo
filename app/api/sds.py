from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import SDSNode, SDSNodeState
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

@router.post("/sds/add")
def add_sds(sds: SDSCreate, db: Session = Depends(get_db)):
    sds_obj = SDSNode(
        name=sds.name,
        total_capacity_gb=sds.total_capacity_gb,
        used_capacity_gb=0,
        state=SDSNodeState.UP,
        devices=sds.devices,
        protection_domain_id=sds.protection_domain_id
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
    sds_nodes = db.query(SDSNode).all()
    return [{"id": s.id, "name": s.name, "state": s.state} for s in sds_nodes]

@router.post("/sds/{sds_id}/fail")
def fail_sds(sds_id: int, db: Session = Depends(get_db)):
    sds = db.query(SDSNode).get(sds_id)
    if not sds:
        return {"error": "SDS not found"}
    setattr(sds, "state", "DOWN")
    db.commit()
    return {"id": sds.id, "state": sds.state}

@router.post("/sds/{sds_id}/recover")
def recover_sds(sds_id: int, db: Session = Depends(get_db)):
    sds = db.query(SDSNode).get(sds_id)
    if not sds:
        return {"error": "SDS not found"}
    setattr(sds, "state", "UP")
    db.commit()
    return {"id": sds.id, "state": sds.state}
