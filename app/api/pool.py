from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import StoragePool, ProtectionPolicy, PoolHealth
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
    pools = db.query(StoragePool).all()
    return [{"id": p.id, "name": p.name, "health": p.health} for p in pools]

@router.get("/pool/{pool_id}/health")
def pool_health(pool_id: int, db: Session = Depends(get_db)):
    pool = db.query(StoragePool).get(pool_id)
    if not pool:
        return {"error": "Pool not found"}
    return {"id": pool.id, "health": pool.health}
