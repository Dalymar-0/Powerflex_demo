from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from mdm.database import SessionLocal
from mdm.models import StoragePool, Volume, SDSNode, SDCClient, ProtectionDomain, ComponentRegistry

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/metrics/cluster")
def cluster_metrics(db: Session = Depends(get_db)):
    """
    Get cluster-wide aggregate metrics.
    Includes total capacity, volume count, node counts, etc.
    """
    # Storage metrics
    total_capacity = db.scalar(select(func.sum(SDSNode.total_capacity_gb))) or 0
    used_capacity = db.scalar(select(func.sum(SDSNode.used_capacity_gb))) or 0
    
    # Volume metrics
    volume_count = db.scalar(select(func.count(Volume.id))) or 0
    total_volume_capacity = db.scalar(select(func.sum(Volume.size_gb))) or 0
    
    # Node counts
    sds_count = db.scalar(select(func.count(SDSNode.id))) or 0
    sdc_count = db.scalar(select(func.count(SDCClient.id))) or 0
    pd_count = db.scalar(select(func.count(ProtectionDomain.id))) or 0
    pool_count = db.scalar(select(func.count(StoragePool.id))) or 0
    
    # Component health (from registry)
    components_total = db.scalar(select(func.count(ComponentRegistry.id))) or 0
    components_active = db.scalar(select(func.count(ComponentRegistry.id)).where(
        ComponentRegistry.status == "ACTIVE"
    )) or 0
    
    return {
        "storage": {
            "total_capacity_gb": float(total_capacity),
            "used_capacity_gb": float(used_capacity),
            "free_capacity_gb": float(total_capacity - used_capacity),
            "utilization_percent": round((used_capacity / total_capacity * 100) if total_capacity > 0 else 0, 2)
        },
        "volumes": {
            "count": volume_count,
            "total_capacity_gb": float(total_volume_capacity or 0)
        },
        "nodes": {
            "sds": sds_count,
            "sdc": sdc_count,
            "protection_domains": pd_count,
            "pools": pool_count
        },
        "health": {
            "components_total": components_total,
            "components_active": components_active,
            "components_inactive": components_total - components_active,
            "health_percentage": round((components_active / components_total * 100) if components_total > 0 else 100, 2)
        }
    }

@router.get("/metrics/pool/{pool_id}")
def pool_metrics(pool_id: int, db: Session = Depends(get_db)):
    pool = db.get(StoragePool, pool_id)
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
    vol = db.get(Volume, volume_id)
    if not vol:
        return {"error": "Volume not found"}
    return {
        "size_gb": vol.size_gb,
        "used_capacity_gb": vol.used_capacity_gb,
        "state": vol.state
    }

@router.get("/metrics/sds/{sds_id}")
def sds_metrics(sds_id: int, db: Session = Depends(get_db)):
    sds = db.get(SDSNode, sds_id)
    if not sds:
        return {"error": "SDS not found"}
    return {
        "total_capacity_gb": sds.total_capacity_gb,
        "used_capacity_gb": sds.used_capacity_gb,
        "state": sds.state,
        "devices": sds.devices
    }
