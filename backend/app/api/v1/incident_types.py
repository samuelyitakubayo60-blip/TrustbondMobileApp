from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.incident_type import IncidentType
from pydantic import BaseModel
from typing import List

router = APIRouter(prefix="/incident-types", tags=["incident-types"])


class IncidentTypeResponse(BaseModel):
    incident_type_id: int
    type_name: str
    description: str | None
    severity_weight: float
    is_active: bool

    class Config:
        from_attributes = True


@router.get("/", response_model=List[IncidentTypeResponse])
def get_incident_types(db: Session = Depends(get_db)):
    """Get all active incident types"""
    types = db.query(IncidentType).filter(IncidentType.is_active == True).all()
    return types
