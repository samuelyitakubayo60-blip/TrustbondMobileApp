from pydantic import BaseModel, model_validator, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal


class EvidenceFileCreate(BaseModel):
    file_url: str
    file_type: str  # photo or video
    media_latitude: Optional[Decimal] = None
    media_longitude: Optional[Decimal] = None
    captured_at: Optional[datetime] = None
    is_live_capture: bool = False


class ReportCreate(BaseModel):
    report_id: Optional[UUID] = None
    device_id: Optional[UUID] = None
    device_hash: Optional[str] = None
    incident_type_id: int
    description: str
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
    
    # Mobile rule-based verification results
    mobile_rule_status: Optional[str] = None  # "passed", "failed", "warning"
    mobile_rule_details: Optional[Dict[str, Any]] = None  # Details of mobile rule checks
    location_consistency_check: Optional[bool] = None  # Location consistency between report and evidence
    evidence_source_valid: Optional[bool] = None  # Evidence not downloaded/screenshotted
    evidence_tampering_detected: Optional[bool] = None  # Screenshot/screen recording detection

    @model_validator(mode="after")
    def require_device_identifier(self):
        if not self.device_id and not (self.device_hash and str(self.device_hash).strip()):
            raise ValueError("Either device_id or device_hash is required")
        return self

    @field_validator("description")
    @classmethod
    def require_description(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("Description is required")
        return text


class CommunityVoteRequest(BaseModel):
    device_id: str
    vote: str  # "real", "false", "unknown"


class ReportResponse(BaseModel):
    report_id: UUID
    report_number: Optional[str] = None  # RPT-YYYY-NNNN
    # When set (e.g. list_reports with join), clients can filter reports by case without a dedicated endpoint.
    case_id: Optional[UUID] = None
    device_id: UUID
    incident_type_id: int
    description: Optional[str]
    latitude: Decimal
    longitude: Decimal
    reported_at: datetime
    rule_status: str
    priority: str = "medium"  # low, medium, high, urgent
    status: Optional[str] = None  # report_status: pending, verified, flagged, rejected
    verification_status: Optional[str] = None  # pending, under_review, verified, rejected
    village_location_id: Optional[int] = None
    village_name: Optional[str] = None  # from locations table (village containing the point)
    cell_name: Optional[str] = None  # from locations hierarchy (cell containing the village)
    sector_name: Optional[str] = None  # from locations hierarchy (sector containing the cell)
    incident_type_name: Optional[str] = None  # set when listing/loading with join
    evidence_count: int = 0
    evidence_preview: list["EvidencePreview"] = []
    trust_score: Optional[Decimal] = None  # from device or ML prediction
    trust_factors: Optional[Dict[str, Any]] = None  # explainable factor breakdown
    ml_prediction_label: Optional[str] = None  # likely_real, suspicious, fake, uncertain
    ml_predictions: Optional[List[Dict[str, Any]]] = []  # array of ML predictions for frontend
    hotspot_id: Optional[int] = None
    hotspot_risk_level: Optional[str] = None  # low | medium | high
    hotspot_incident_count: Optional[int] = None
    hotspot_label: Optional[str] = None
    is_flagged: Optional[bool] = None
    flag_reason: Optional[str] = None
    ai_evidence_description: Optional[str] = None
    ai_verification_reason: Optional[str] = None
    # Description length / semantic match adjustments (from feature_vector after scoring).
    description_credibility: Optional[Dict[str, Any]] = None
    credibility_summary: Optional[str] = None
    credibility_detail_lines: List[str] = []
    decision_patterns: List[str] = []
    decision_pattern_explanations: Dict[str, str] = {}
    verified_at: Optional[datetime] = None
    # Police officer who recorded the final review (null if never officer-verified).
    verified_by: Optional[int] = None
    # Human-readable verifier information for police portal (never returned to mobile device listing).
    verified_by_name: Optional[str] = None
    verified_by_role: Optional[str] = None
    # Local leader community confirmation (separate from police / AI verification pipeline).
    leader_verification_status: Optional[str] = None  # pending | confirmed | rejected
    leader_verified_at: Optional[datetime] = None
    submitted_by_local_leader_id: Optional[int] = None
    context_tags: list[str] = []
    app_version: Optional[str] = None
    network_type: Optional[str] = None
    battery_level: Optional[Decimal] = None
    gps_accuracy: Optional[Decimal] = None
    motion_level: Optional[str] = None
    movement_speed: Optional[Decimal] = None
    was_stationary: Optional[bool] = None
    assignment_priority: Optional[str] = None
    assignment_status: Optional[str] = None
    community_votes: Optional[Dict[str, int]] = None
    user_vote: Optional[str] = None
    # Device metadata fields
    metadata_json: Optional[Dict[str, Any]] = {}
    device_trust_score: Optional[float] = None
    total_reports: Optional[int] = None
    trusted_reports: Optional[int] = None
    # Location hierarchy and station assignment data
    assigned_station: Optional[Dict[str, Any]] = None  # station info from assigned officer
    assigned_officers: Optional[List[Dict[str, Any]]] = None  # list of assigned officers with their stations

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
    quality_label: Optional[str] = None

    class Config:
        from_attributes = True


class AssignmentResponse(BaseModel):
    assignment_id: UUID
    report_id: UUID
    police_user_id: int
    status: str
    priority: str
    assignment_note: Optional[str] = None
    assigned_at: datetime
    completed_at: Optional[datetime] = None
    officer_name: Optional[str] = None

    class Config:
        from_attributes = True


class AssignCreate(BaseModel):
    police_user_id: int
    priority: str = "medium"  # low, medium, high, urgent
    assignment_note: Optional[str] = None  # Notes explaining why this assignment is needed


class ReportDetailResponse(ReportResponse):
    """Report with evidence files and assignments (for police dashboard)."""
    trust_score_note: Optional[str] = None
    """Explains how headline trust relates to the scorecard (e.g. flagged but mid-range score)."""
    incident_latitude: Optional[Decimal] = None
    incident_longitude: Optional[Decimal] = None
    incident_location_source: Optional[str] = None  # reporter_only | evidence_only | combined
    incident_village_name: Optional[str] = None
    incident_cell_name: Optional[str] = None
    incident_sector_name: Optional[str] = None
    evidence_files: list[EvidenceFileResponse] = []
    assignments: list[AssignmentResponse] = []


class ReportListResponse(BaseModel):
    """Paginated list of reports (police dashboard)."""
    items: list[ReportResponse]
    total: int
    limit: int
    offset: int
