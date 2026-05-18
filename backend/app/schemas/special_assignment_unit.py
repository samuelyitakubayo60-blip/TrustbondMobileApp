from pydantic import BaseModel, Field


class SpecialAssignmentUnitCreate(BaseModel):
    unit_code: str = Field(..., min_length=2, max_length=50)
    unit_name: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    requires_commander_approval: bool = True


class SpecialAssignmentUnitUpdate(BaseModel):
    unit_name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None
    requires_commander_approval: bool | None = None
