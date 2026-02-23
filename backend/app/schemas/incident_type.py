from decimal import Decimal
from pydantic import BaseModel, Field


class IncidentTypeResponse(BaseModel):
    incident_type_id: int
    type_name: str
    description: str | None
    severity_weight: Decimal
    is_active: bool

    class Config:
        from_attributes = True


class IncidentTypeCreate(BaseModel):
    type_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    severity_weight: Decimal = Field(default=Decimal("1.00"), ge=0, le=10)
    is_active: bool = True


class IncidentTypeUpdate(BaseModel):
    type_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    severity_weight: Decimal | None = Field(None, ge=0, le=10)
    is_active: bool | None = None
