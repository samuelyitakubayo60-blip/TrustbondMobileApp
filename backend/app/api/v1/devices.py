from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import uuid4
from app.database import get_db
from app.models.device import Device
from app.schemas.device import DeviceCreate, DeviceResponse

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("/register", response_model=DeviceResponse)
def register_device(device_data: DeviceCreate, db: Session = Depends(get_db)):
    """Register or get existing device by hash (anonymous)"""
    device = db.query(Device).filter(Device.device_hash == device_data.device_hash).first()
    
    if device:
        return device
    
    new_device = Device(
        device_id=uuid4(),
        device_hash=device_data.device_hash,
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    return new_device
