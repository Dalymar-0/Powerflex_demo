from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from mdm.database import SessionLocal
from mdm.models import SDCClient, VolumeMapping, Volume
from mdm.services.capability_guard import validate_node_capability
from mdm.services.real_storage import RealStorageBackend
from pydantic import BaseModel

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SDCCreate(BaseModel):
    name: str
    cluster_node_id: str

@router.post("/sdc/add")
def add_sdc(sdc: SDCCreate, db: Session = Depends(get_db)):
    ok, msg, _ = validate_node_capability(db, sdc.cluster_node_id, "SDC", require_active=True)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    sdc_obj = SDCClient(name=sdc.name, cluster_node_id=sdc.cluster_node_id)
    db.add(sdc_obj)
    db.commit()
    db.refresh(sdc_obj)
    return {"id": sdc_obj.id, "name": sdc_obj.name, "cluster_node_id": sdc_obj.cluster_node_id}

@router.get("/sdc/list")
def list_sdcs(db: Session = Depends(get_db)):
    sdcs = db.scalars(select(SDCClient)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "cluster_node_id": s.cluster_node_id,
            "mapped_volume_count": db.scalar(select(func.count()).select_from(VolumeMapping).where(VolumeMapping.sdc_id == s.id)),
        }
        for s in sdcs
    ]


@router.get("/sdc/{sdc_id}")
def get_sdc(sdc_id: int, db: Session = Depends(get_db)):
    sdc = db.get(SDCClient, sdc_id)
    if not sdc:
        raise HTTPException(status_code=404, detail="SDC not found")

    mappings = db.scalars(select(VolumeMapping).where(VolumeMapping.sdc_id == sdc_id)).all()
    return {
        "id": sdc.id,
        "name": sdc.name,
        "cluster_node_id": sdc.cluster_node_id,
        "mapped_volume_count": len(mappings),
        "mapped_volumes": [
            {"volume_id": m.volume_id, "access_mode": m.access_mode, "mapped_at": m.mapped_at}
            for m in mappings
        ],
    }


@router.get("/sdc/{sdc_id}/datastores")
def get_sdc_datastores(sdc_id: int, db: Session = Depends(get_db)):
    sdc = db.get(SDCClient, sdc_id)
    if not sdc:
        raise HTTPException(status_code=404, detail="SDC not found")

    backend = RealStorageBackend()
    mappings = db.scalars(select(VolumeMapping).where(VolumeMapping.sdc_id == sdc_id)).all()
    datastores = []
    for mapping in mappings:
        volume = db.scalars(select(Volume).where(Volume.id == mapping.volume_id)).first()
        if volume is None:
            continue
        device_path = backend._sdc_device_path(int(volume.id), sdc)
        mapping_path = backend._sdc_mapping_path(int(volume.id), sdc)
        datastores.append(
            {
                "volume_id": int(volume.id),
                "volume_name": volume.name,
                "size_gb": float(getattr(volume, "size_gb", 0.0) or 0.0),
                "access_mode": mapping.access_mode,
                "device_path": str(device_path.resolve()),
                "mapping_path": str(mapping_path.resolve()),
            }
        )

    return {
        "sdc_id": int(sdc.id),
        "sdc_name": sdc.name,
        "datastore_count": len(datastores),
        "datastores": datastores,
    }
