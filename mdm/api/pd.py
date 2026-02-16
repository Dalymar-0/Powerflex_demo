from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, func
from mdm.database import SessionLocal
from mdm.models import ProtectionDomain, StoragePool, SDSNode
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PDCreate(BaseModel):
    name: str

@router.post("/pd/create")
def create_pd(pd: PDCreate, db: Session = Depends(get_db)):
    pd_obj = ProtectionDomain(name=pd.name)
    try:
        db.add(pd_obj)
        db.commit()
        db.refresh(pd_obj)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Protection domain '{pd.name}' already exists")
    return {"id": pd_obj.id, "name": pd_obj.name}

@router.get("/pd/list")
def list_pds(db: Session = Depends(get_db)):
    pds = db.scalars(select(ProtectionDomain)).all()
    return [
        {
            "id": pd.id,
            "name": pd.name,
            "description": pd.description,
            "pool_count": db.scalar(select(func.count()).select_from(StoragePool).where(StoragePool.pd_id == pd.id)),
            "sds_count": db.scalar(select(func.count()).select_from(SDSNode).where(SDSNode.protection_domain_id == pd.id)),
        }
        for pd in pds
    ]


@router.get("/pd/{pd_id}")
def get_pd(pd_id: int, db: Session = Depends(get_db)):
    pd = db.get(ProtectionDomain, pd_id)
    if not pd:
        raise HTTPException(status_code=404, detail="PD not found")

    pools = db.scalars(select(StoragePool).where(StoragePool.pd_id == pd_id)).all()
    sds_nodes = db.scalars(select(SDSNode).where(SDSNode.protection_domain_id == pd_id)).all()
    return {
        "id": pd.id,
        "name": pd.name,
        "description": pd.description,
        "pool_count": len(pools),
        "sds_count": len(sds_nodes),
        "pools": [{"id": p.id, "name": p.name, "health": p.health} for p in pools],
        "sds_nodes": [{"id": s.id, "name": s.name, "state": s.state} for s in sds_nodes],
    }

@router.delete("/pd/{pd_id}")
def delete_pd(pd_id: int, db: Session = Depends(get_db)):
    pd = db.get(ProtectionDomain, pd_id)
    if not pd:
        return {"error": "PD not found"}
    db.delete(pd)
    db.commit()
    return {"status": "deleted"}
