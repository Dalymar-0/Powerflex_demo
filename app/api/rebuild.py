from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import SDSNode, Chunk, Replica, StoragePool, PoolHealth
import time

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/rebuild/start/{pool_id}")
def start_rebuild(pool_id: int, db: Session = Depends(get_db)):
    pool = db.query(StoragePool).get(pool_id)
    if not pool:
        return {"error": "Pool not found"}
    # Find under-protected chunks
    chunks = db.query(Chunk).join(Replica).filter(Chunk.volume_id.in_([v.id for v in pool.volumes])).all()
    under_protected = []
    for chunk in chunks:
        replicas = db.query(Replica).filter_by(chunk_id=chunk.id).all()
        available = []
        for r in replicas:
            sds = db.query(SDSNode).get(r.sds_id)
            if sds is not None and getattr(sds, "state", None) == "UP":
                available.append(r)
        if len(available) < 2:
            under_protected.append(chunk)
    # Simulate rebuild
    rebuilt = 0
    for chunk in under_protected:
        # Find new SDS for missing replica
        sds_nodes = db.query(SDSNode).filter_by(state="UP").all()
        for sds in sds_nodes:
            if not db.query(Replica).filter_by(chunk_id=chunk.id, sds_id=sds.id).first():
                # Simulate delay
                time.sleep(0.1)
                replica = Replica(chunk_id=chunk.id, sds_id=sds.id, is_available=True)
                db.add(replica)
                rebuilt += 1
                break
    setattr(pool, "health", "OK" if rebuilt == len(under_protected) else "DEGRADED")
    db.commit()
    return {"rebuild_progress": f"{rebuilt}/{len(under_protected)} chunks rebuilt", "pool_health": pool.health}

@router.get("/rebuild/status/{pool_id}")
def rebuild_status(pool_id: int, db: Session = Depends(get_db)):
    pool = db.query(StoragePool).get(pool_id)
    if not pool:
        return {"error": "Pool not found"}
    chunks = db.query(Chunk).join(Replica).filter(Chunk.volume_id.in_([v.id for v in pool.volumes])).all()
    under_protected = 0
    for chunk in chunks:
        replicas = db.query(Replica).filter_by(chunk_id=chunk.id).all()
        available = []
        for r in replicas:
            sds = db.query(SDSNode).get(r.sds_id)
            if sds is not None and getattr(sds, "state", None) == "UP":
                available.append(r)
        if len(available) < 2:
            under_protected += 1
    return {"under_protected_chunks": under_protected, "pool_health": pool.health}
