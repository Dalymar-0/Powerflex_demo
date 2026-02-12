from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import ProtectionDomain
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
    pds = db.query(ProtectionDomain).all()
    return [{"id": pd.id, "name": pd.name} for pd in pds]

@router.delete("/pd/{pd_id}")
def delete_pd(pd_id: int, db: Session = Depends(get_db)):
    pd = db.query(ProtectionDomain).get(pd_id)
    if not pd:
        return {"error": "PD not found"}
    db.delete(pd)
    db.commit()
    return {"status": "deleted"}
