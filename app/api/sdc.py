from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import SDCClient
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

@router.post("/sdc/add")
def add_sdc(sdc: SDCCreate, db: Session = Depends(get_db)):
    sdc_obj = SDCClient(name=sdc.name)
    db.add(sdc_obj)
    db.commit()
    db.refresh(sdc_obj)
    return {"id": sdc_obj.id, "name": sdc_obj.name}

@router.get("/sdc/list")
def list_sdcs(db: Session = Depends(get_db)):
    sdcs = db.query(SDCClient).all()
    return [{"id": s.id, "name": s.name} for s in sdcs]
