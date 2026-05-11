from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class DeploymentDecisionBase(BaseModel):
    deployment_status: str = Field(default="pending", description="pending, deployed, declined, monitoring")
    assigned_unit: Optional[str] = Field(None, description="quick_response, counter_terror, fire_rescue, general_patrol")
    deployment_priority: str = Field(default="medium", description="low, medium, high, urgent")
    decision_note: Optional[str] = None
    leader_confirmation_weight: int = Field(default=0, ge=0, le=5)


class DeploymentDecisionCreate(DeploymentDecisionBase):
    report_id: str
    case_id: Optional[str] = None


class DeploymentDecisionUpdate(BaseModel):
    deployment_status: Optional[str] = None
    assigned_unit: Optional[str] = None
    deployment_priority: Optional[str] = None
    decision_note: Optional[str] = None
    deployment_outcome: Optional[str] = None
    outcome_note: Optional[str] = None
    deployed_at: Optional[datetime] = None
    estimated_arrival: Optional[datetime] = None
    actual_arrival: Optional[datetime] = None


class DeploymentDecisionResponse(DeploymentDecisionBase):
    decision_id: int
    report_id: str
    case_id: Optional[str]
    decided_by: int
    decided_by_name: Optional[str]
    decided_by_role: Optional[str]
    deployed_at: Optional[datetime]
    estimated_arrival: Optional[datetime]
    actual_arrival: Optional[datetime]
    deployment_outcome: Optional[str]
    outcome_note: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SuspectVictimBase(BaseModel):
    person_type: str = Field(..., description="suspect, victim, witness")
    full_name: str
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    status: str = Field(default="identified", description="identified, detained, released, hospitalized, handed_to_rib")
    status_note: Optional[str] = None


class SuspectVictimCreate(SuspectVictimBase):
    case_id: str


class SuspectVictimUpdate(BaseModel):
    person_type: Optional[str] = None
    full_name: Optional[str] = None
    national_id: Optional[str] = None
    phone_number: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    status: Optional[str] = None
    status_note: Optional[str] = None
    rib_case_number: Optional[str] = None
    rib_handover_date: Optional[datetime] = None
    rib_officer_name: Optional[str] = None


class SuspectVictimResponse(SuspectVictimBase):
    tracking_id: int
    case_id: str
    rib_case_number: Optional[str]
    rib_handover_date: Optional[datetime]
    rib_officer_name: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommanderDashboardIncident(BaseModel):
    report_id: str
    report_number: Optional[str]
    incident_type: str
    location_description: str
    latitude: float
    longitude: float
    leader_verification_status: str
    leader_verified_at: Optional[datetime]
    leader_name: Optional[str]
    leader_role: Optional[str]
    priority: str
    submitted_at: datetime
    deployment_decision: Optional[DeploymentDecisionResponse] = None

    class Config:
        from_attributes = True


class LeaderMobileIncident(BaseModel):
    report_id: str
    report_number: Optional[str]
    incident_type: str
    location_description: str
    latitude: float
    longitude: float
    description: str
    priority: str
    submitted_at: datetime
    leader_verification_status: str
    needs_verification: bool = False

    class Config:
        from_attributes = True
