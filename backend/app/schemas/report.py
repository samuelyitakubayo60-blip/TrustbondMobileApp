from pydantic import BaseModel, model_validator
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
    device_id: Optional[UUID] = None
    device_hash: Optional[str] = None
    incident_type_id: int
    description: Optional[str] = None
    latitude: Decimal

    longitude: Decimal
    gps_accuracy: Optional[Decimal] = None
    motion_level: Optional[str] = None  # low, medium, high
    movement_speed: Optional[Decimal] = None
    was_stationary: Optional[bool] = None
    evidence_files: list[EvidenceFileCreate] = []
    # Contextual tags from reporter (e.g. Night-time, Weapons involved)
    context_tags: list[str] = []
    # Client metadata at submit (optional)
    app_version: Optional[str] = None
    network_type: Optional[str] = None
    battery_level: Optional[Decimal] = None

    @model_validator(mode="after")
    def require_device_identifier(self):
        if not self.device_id and not (self.device_hash and str(self.device_hash).strip()):
            raise ValueError("Either device_id or device_hash is required")
        return self


class ReportResponse(BaseModel):
    report_id: UUID
    report_number: Optional[str] = None  # RPT-YYYY-NNNN
    device_id: UUID
    incident_type_id: int
    description: Optional[str]
    latitude: Decimal
    longitude: Decimal
    reported_at: datetime
    rule_status: str
    status: Optional[str] = None  # report_status: pending, verified, flagged, rejected
    verification_status: Optional[str] = None  # pending, under_review, verified, rejected
    village_location_id: Optional[int] = None
    village_name: Optional[str] = None  # from locations table (village containing the point)
    incident_type_name: Optional[str] = None  # set when listing/loading with join
    evidence_count: int = 0
    evidence_preview: list["EvidencePreview"] = []
    trust_score: Optional[Decimal] = None  # from device or ML prediction
    hotspot_id: Optional[int] = None
    hotspot_risk_level: Optional[str] = None  # low | medium | high
    hotspot_incident_count: Optional[int] = None
    hotspot_label: Optional[str] = None
    is_flagged: Optional[bool] = None
    flag_reason: Optional[str] = None
    verified_at: Optional[datetime] = None
    context_tags: list[str] = []
    app_version: Optional[str] = None
    network_type: Optional[str] = None
    battery_level: Optional[Decimal] = None
    assignment_priority: Optional[str] = None
    assignment_status: Optional[str] = None

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
    blur_score: Optional[Decimal] = None
    tamper_score: Optional[Decimal] = None
    ai_quality_label: Optional[str] = None

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
