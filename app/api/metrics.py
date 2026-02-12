from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import StoragePool, Volume, SDSNode

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/metrics/pool/{pool_id}")
def pool_metrics(pool_id: int, db: Session = Depends(get_db)):
    pool = db.query(StoragePool).get(pool_id)
    if not pool:
        return {"error": "Pool not found"}
    return {
        "total_capacity_gb": pool.total_capacity_gb,
        "used_capacity_gb": pool.used_capacity_gb,
        "free_capacity_gb": pool.total_capacity_gb - pool.used_capacity_gb,
        "health": pool.health
    }

@router.get("/metrics/volume/{volume_id}")
def volume_metrics(volume_id: int, db: Session = Depends(get_db)):
    vol = db.query(Volume).get(volume_id)
    if not vol:
        return {"error": "Volume not found"}
    return {
        "size_gb": vol.size_gb,
        "used_capacity_gb": vol.used_capacity_gb,
        "state": vol.state
    }

@router.get("/metrics/sds/{sds_id}")
def sds_metrics(sds_id: int, db: Session = Depends(get_db)):
    sds = db.query(SDSNode).get(sds_id)
    if not sds:
        return {"error": "SDS not found"}
    return {
        "total_capacity_gb": sds.total_capacity_gb,
        "used_capacity_gb": sds.used_capacity_gb,
        "state": sds.state,
        "devices": sds.devices
    }
