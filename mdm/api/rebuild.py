from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from mdm.database import SessionLocal
from mdm.models import StoragePool
from mdm.logic import start_rebuild, get_rebuild_status

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/rebuild/start/{pool_id}")
def start_rebuild(pool_id: int, db: Session = Depends(get_db)):
    pool = db.get(StoragePool, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    try:
        message = start_rebuild(pool_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    status = get_rebuild_status(pool_id, db)
    return {
        "status": "started",
        "message": message,
        "rebuild": status,
    }

@router.get("/rebuild/status/{pool_id}")
def rebuild_status(pool_id: int, db: Session = Depends(get_db)):
    pool = db.get(StoragePool, pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    status = get_rebuild_status(pool_id, db)
    if status is None:
        return {
            "pool_id": pool_id,
            "state": getattr(pool, "rebuild_state", None),
            "pool_health": getattr(pool, "health", None),
            "message": "No active rebuild job",
        }
    status["pool_health"] = getattr(pool, "health", None)
    return status
