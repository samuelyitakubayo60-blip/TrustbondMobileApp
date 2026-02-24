from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal


class EvidenceFileCreate(BaseModel):
    file_url: str
    file_type: str  # photo or video
    media_latitude: Optional[Decimal] = None
    media_longitude: Optional[Decimal] = None
    captured_at: Optional[datetime] = None
    is_live_capture: bool = False


class ReportCreate(BaseModel):
    device_id: UUID
    incident_type_id: int
    description: Optional[str] = None
    latitude: Decimal
    longitude: Decimal
    gps_accuracy: Optional[Decimal] = None
    motion_level: Optional[str] = None  # low, medium, high
    movement_speed: Optional[Decimal] = None
    was_stationary: Optional[bool] = None
    evidence_files: list[EvidenceFileCreate] = []


class ReportResponse(BaseModel):
    report_id: UUID
    device_id: UUID
    incident_type_id: int
    description: Optional[str]
    latitude: Decimal
    longitude: Decimal
    reported_at: datetime
    rule_status: str
    village_location_id: Optional[int] = None
    village_name: Optional[str] = None  # from locations table (village containing the point)
    incident_type_name: Optional[str] = None  # set when listing/loading with join
    evidence_count: int = 0
    evidence_preview: list["EvidencePreview"] = []
     # Hotspot summary (if this report is part of an active hotspot)
    hotspot_id: Optional[int] = None
    hotspot_risk_level: Optional[str] = None  # low | medium | high
    hotspot_incident_count: Optional[int] = None
    hotspot_label: Optional[str] = None

    class Config:
        from_attributes = True


class EvidencePreview(BaseModel):
    evidence_id: UUID
    file_url: str
    file_type: str  # photo | video

    class Config:
        from_attributes = True


class EvidenceFileResponse(BaseModel):
    evidence_id: UUID
    report_id: UUID
    file_url: str
    file_type: str
    uploaded_at: Optional[datetime] = None
    media_latitude: Optional[Decimal] = None
    media_longitude: Optional[Decimal] = None

    class Config:
        from_attributes = True


class AssignmentResponse(BaseModel):
    assignment_id: UUID
    report_id: UUID
    police_user_id: int
    status: str
    priority: str
    assigned_at: datetime
    completed_at: Optional[datetime] = None
    officer_name: Optional[str] = None

    class Config:
        from_attributes = True


class AssignCreate(BaseModel):
    police_user_id: int
    priority: str = "medium"  # low, medium, high, urgent


class ReviewResponse(BaseModel):
    review_id: UUID
    report_id: UUID
    police_user_id: int
    decision: str
    review_note: Optional[str] = None
    reviewed_at: datetime
    reviewer_name: Optional[str] = None

    class Config:
        from_attributes = True


class ReviewCreate(BaseModel):
    decision: str  # confirmed, rejected, investigation
    review_note: Optional[str] = None


class ReportDetailResponse(ReportResponse):
    """Report with evidence files, assignments, and reviews (for police dashboard)."""
    incident_latitude: Optional[Decimal] = None
    incident_longitude: Optional[Decimal] = None
    incident_location_source: Optional[str] = None  # reporter_only | evidence_only | combined
    incident_village_name: Optional[str] = None
    incident_cell_name: Optional[str] = None
    incident_sector_name: Optional[str] = None
    evidence_files: list[EvidenceFileResponse] = []
    assignments: list[AssignmentResponse] = []
    reviews: list[ReviewResponse] = []


class ReportListResponse(BaseModel):
    """Paginated list of reports (police dashboard)."""
    items: list[ReportResponse]
    total: int
    limit: int
    offset: int
