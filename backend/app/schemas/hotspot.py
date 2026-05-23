from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any
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
    evidence_files: Optional[List[Dict[str, Any]]] = []
    lifecycle_state: Optional[str] = None
    hotspot_score: Optional[float] = None
    classification: Optional[str] = None
    classification_confidence: Optional[float] = None
    classification_source: Optional[str] = None
    avg_trust_score: Optional[float] = None
    dominant_crime_type: Optional[str] = None
    cluster_kind: Optional[str] = None
    area_label: Optional[str] = None
    incident_mix: Optional[Dict[str, int]] = None
    prediction: Optional[Dict[str, Any]] = None
    boundary_points: Optional[List[List[float]]] = []
    incident_points: Optional[List[Dict[str, Any]]] = []
    assigned_unit_code: Optional[str] = None
    assigned_unit_name: Optional[str] = None
    deployed_at: Optional[datetime] = None
    deployment_note: Optional[str] = None
    controlled_by_user_id: Optional[int] = None
    controlled_by_name: Optional[str] = None

    class Config:
        from_attributes = True


class HotspotDeployRequest(BaseModel):
    unit_code: str
    note: Optional[str] = None


class HotspotIncidentResponse(BaseModel):
    report_id: str
    incident_type_name: Optional[str] = None
    description: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    reported_at: Optional[datetime] = None
    rule_status: Optional[str] = None
    verification_status: Optional[str] = None
    trust_score: Optional[float] = None
    village_name: Optional[str] = None
    cell_name: Optional[str] = None
    sector_name: Optional[str] = None
