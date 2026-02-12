from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Volume, ProvisioningType, VolumeState
from app.logic import create_volume, map_volume, unmap_volume, extend_volume, delete_volume
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class VolumeCreate(BaseModel):
    name: str
    size_gb: float
    provisioning: ProvisioningType
    pool_id: int

@router.post("/vol/create")
def create_vol(vol: VolumeCreate, db: Session = Depends(get_db)):
    try:
        volume = create_volume(vol.name, vol.size_gb, vol.provisioning, vol.pool_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": volume.id, "name": volume.name}

@router.post("/vol/map")
def map_vol(volume_id: int, sdc_id: int, access_mode: str, db: Session = Depends(get_db)):
    try:
        map_volume(volume_id, sdc_id, access_mode, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "mapped"}

@router.post("/vol/unmap")
def unmap_vol(volume_id: int, sdc_id: int, db: Session = Depends(get_db)):
    try:
        unmap_volume(volume_id, sdc_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "unmapped"}

@router.post("/vol/extend")
def extend_vol(volume_id: int, new_size_gb: float, db: Session = Depends(get_db)):
    try:
        extend_volume(volume_id, new_size_gb, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "extended"}

@router.delete("/vol/{volume_id}")
def delete_vol(volume_id: int, db: Session = Depends(get_db)):
    try:
        delete_volume(volume_id, db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "deleted"}

@router.get("/vol/list")
def list_vols(db: Session = Depends(get_db)):
    vols = db.query(Volume).all()
    return [{"id": v.id, "name": v.name, "state": v.state} for v in vols]
