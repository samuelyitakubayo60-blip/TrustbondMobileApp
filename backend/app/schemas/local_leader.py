from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# Only these roles are valid for local leaders.
LEADER_ROLE_CHIEF_OF_VILLAGE = "chief_of_village"
LEADER_ROLE_EXECUTIVE_OF_CELL = "executive_of_cell"
VALID_LEADER_ROLES = frozenset({LEADER_ROLE_CHIEF_OF_VILLAGE, LEADER_ROLE_EXECUTIVE_OF_CELL})


class LocalLeaderCreate(BaseModel):
    full_name: str
    role: str = Field(..., description="chief_of_village | executive_of_cell")
    email: str
    phone_number: Optional[str] = None
    covered_location_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=1,
        description="Exactly one location: a village (chief) or cell (executive)",
    )


class LocalLeaderUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6)
    covered_location_ids: Optional[list[int]] = Field(
        None,
        description="If set, must contain exactly one village or cell matching role",
    )


class LocalLeaderResponse(BaseModel):
    local_leader_id: int
    full_name: str
    role: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_active: bool
    covered_location_ids: list[int] = Field(default_factory=list)
    covered_location_names: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocalLeaderLoginRequest(BaseModel):
    email: str
    password: str


class LocalLeaderMeResponse(BaseModel):
    local_leader_id: int
    full_name: str
    role: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    covered_location_ids: list[int] = Field(default_factory=list)

    class Config:
        from_attributes = True


class LocalLeaderToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LocalLeaderRequestCodeRequest(BaseModel):
    email: str


class LocalLeaderSetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str = Field(..., min_length=6)


class LocalLeaderVerifyLoginCodeRequest(BaseModel):
    email: str
    code: str


class LocalLeaderFcmTokenRequest(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=512)
