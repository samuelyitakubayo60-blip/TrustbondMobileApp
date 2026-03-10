from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import uuid4
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models.device import Device
from app.schemas.device import DeviceCreate, DeviceResponse
from app.api.v1.auth import get_current_admin_or_supervisor
from app.models.police_user import PoliceUser

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


@router.get("/", response_model=dict)
def list_devices(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    trust_level: Optional[str] = Query(None, description="high (>=70), medium (40-69), low (<40)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List devices with trust stats for police dashboard. Admin/supervisor only."""
    query = db.query(Device)
    if hasattr(Device, "is_banned"):
        query = query.filter(Device.is_banned == False)
    if trust_level == "high":
        query = query.filter(Device.device_trust_score >= 70)
    elif trust_level == "medium":
        query = query.filter(Device.device_trust_score >= 40, Device.device_trust_score < 70)
    elif trust_level == "low":
        query = query.filter(Device.device_trust_score < 40)
    total = query.count()
    devices = query.order_by(Device.first_seen_at.desc()).offset(offset).limit(limit).all()
    items = [
        {
            "device_id": str(d.device_id),
            "device_hash_short": d.device_hash[:8] + "..." + d.device_hash[-4:] if len(d.device_hash) >= 12 else d.device_hash,
            "device_hash": d.device_hash,
            "device_trust_score": float(d.device_trust_score) if d.device_trust_score else 0,
            "total_reports": d.total_reports or 0,
            "trusted_reports": d.trusted_reports or 0,
            "flagged_reports": d.flagged_reports or 0,
            "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
        }
        for d in devices
    ]
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)
    high = db.query(func.count(Device.device_id)).filter(Device.device_trust_score >= 70).scalar() or 0
    medium = db.query(func.count(Device.device_id)).filter(Device.device_trust_score >= 40, Device.device_trust_score < 70).scalar() or 0
    low = db.query(func.count(Device.device_id)).filter(Device.device_trust_score < 40).scalar() or 0
    if hasattr(Device, "is_banned"):
        banned = db.query(func.count(Device.device_id)).filter(Device.is_banned == True).scalar() or 0
    else:
        banned = 0
    active_30d = db.query(func.count(Device.device_id)).filter(Device.first_seen_at >= since_30d).scalar() or 0
    if hasattr(Device, "is_banned"):
        active_30d = db.query(func.count(Device.device_id)).filter(Device.first_seen_at >= since_30d, Device.is_banned == False).scalar() or 0
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_30d": active_30d,
            "high_trust": high,
            "medium_trust": medium,
            "low_trust": low,
            "banned": banned,
        },
    }
