from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal


class CaseReportLink(BaseModel):
    report_id: UUID
    report_number: Optional[str] = None


class CaseCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location_id: Optional[int] = None
    incident_type_id: Optional[int] = None
    priority: str = "medium"
    report_ids: list[UUID] = []
    assigned_to_id: Optional[int] = None


class CaseUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    outcome: Optional[str] = None


class CaseResponse(BaseModel):
    case_id: UUID
    case_number: Optional[str] = None
    status: str
    priority: str
    title: Optional[str] = None
    description: Optional[str] = None
    location_id: Optional[int] = None
    location_name: Optional[str] = None
    incident_type_id: Optional[int] = None
    incident_type_name: Optional[str] = None
    assigned_to_id: Optional[int] = None
    assigned_to_name: Optional[str] = None
    created_by: Optional[int] = None
    report_count: int = 0
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    created_at: Optional[datetime] = None
    average_trust_score: Optional[Decimal] = None

    class Config:
        from_attributes = True


class CaseListResponse(BaseModel):
    items: list[CaseResponse]
    total: int
    limit: int
    offset: int


class CaseAddReports(BaseModel):
    report_ids: list[UUID] = []
