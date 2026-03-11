from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.hotspot import Hotspot
from app.schemas.hotspot import HotspotResponse

router = APIRouter(prefix="/public/hotspots", tags=["public"])


@router.get("/", response_model=List[HotspotResponse])
def list_public_hotspots(
    db: Session = Depends(get_db),
    risk_level: Optional[str] = Query(
        None, description="Filter by risk_level: low, medium, high"
    ),
    limit: int = Query(30, ge=1, le=200),
):
    """
    Public (no-auth) hotspot list for the mobile Safety Map.

    Returns recent hotspots with center coordinates, radius, incident count,
    risk level, and incident_type_name for labeling.
    """
    query = db.query(Hotspot).options(joinedload(Hotspot.incident_type))
    query = query.order_by(Hotspot.detected_at.desc())
    if risk_level:
        query = query.filter(Hotspot.risk_level == risk_level)
    hotspots = query.limit(limit).all()
    return [
        HotspotResponse(
            hotspot_id=h.hotspot_id,
            center_lat=h.center_lat,
            center_long=h.center_long,
            radius_meters=h.radius_meters,
            incident_count=h.incident_count,
            risk_level=h.risk_level,
            time_window_hours=h.time_window_hours,
            detected_at=h.detected_at,
            incident_type_id=h.incident_type_id,
            incident_type_name=h.incident_type.type_name if h.incident_type else None,
        )
        for h in hotspots
    ]

