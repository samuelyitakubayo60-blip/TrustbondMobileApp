from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from decimal import Decimal


class HotspotCreate(BaseModel):
    center_lat: Decimal
    center_long: Decimal
    radius_meters: Decimal
    incident_count: int
    risk_level: str  # low, medium, high
    time_window_hours: int = 24


class HotspotResponse(BaseModel):
    hotspot_id: int
    center_lat: Decimal
    center_long: Decimal
    radius_meters: Decimal
    incident_count: int
    risk_level: str
    time_window_hours: int
    detected_at: Optional[datetime] = None
    incident_type_id: Optional[int] = None
    incident_type_name: Optional[str] = None

    class Config:
        from_attributes = True
