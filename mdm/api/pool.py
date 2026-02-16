from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from mdm.database import SessionLocal
from mdm.models import StoragePool, ProtectionPolicy, PoolHealth
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class PoolCreate(BaseModel):
    name: str
    pd_id: int
    protection_policy: ProtectionPolicy
    total_capacity_gb: float

@router.post("/pool/create")
def create_pool(pool: PoolCreate, db: Session = Depends(get_db)):
    pool_obj = StoragePool(
        name=pool.name,
        pd_id=pool.pd_id,
        protection_policy=pool.protection_policy,
        total_capacity_gb=pool.total_capacity_gb,
        used_capacity_gb=0,
        health=PoolHealth.OK
    )
    try:
        db.add(pool_obj)
        db.commit()
        db.refresh(pool_obj)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Pool '{pool.name}' already exists or references invalid PD")
    return {"id": pool_obj.id, "name": pool_obj.name}

@router.get("/pool/list")
def list_pools(db: Session = Depends(get_db)):
    pools = db.scalars(select(StoragePool)).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "pd_id": p.pd_id,
            "health": p.health,
            "total_capacity_gb": p.total_capacity_gb,
            "used_capacity_gb": p.used_capacity_gb,
            "reserved_capacity_gb": p.reserved_capacity_gb,
            "protection_policy": p.protection_policy,
        }
        for p in pools
    ]


@router.get("/pool/{pool_id}")
def get_pool(pool_id: int, db: Session = Depends(get_db)):
    pool = db.get(StoragePool, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    return {
        "id": pool.id,
        "name": pool.name,
        "pd_id": pool.pd_id,
        "health": pool.health,
        "protection_policy": pool.protection_policy,
        "total_capacity_gb": pool.total_capacity_gb,
        "used_capacity_gb": pool.used_capacity_gb,
        "reserved_capacity_gb": pool.reserved_capacity_gb,
        "rebuild_state": pool.rebuild_state,
        "rebuild_progress_percent": pool.rebuild_progress_percent,
    }

@router.get("/pool/{pool_id}/health")
def pool_health(pool_id: int, db: Session = Depends(get_db)):
    pool = db.get(StoragePool, pool_id)
    if not pool:
        return {"error": "Pool not found"}
    return {"id": pool.id, "health": pool.health}
