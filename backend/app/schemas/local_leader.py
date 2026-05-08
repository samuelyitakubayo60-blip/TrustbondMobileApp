from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LocalLeaderCreate(BaseModel):
    full_name: str
    phone_number: str
    email: Optional[str] = None
    covered_location_ids: list[int] = Field(default_factory=list)


class LocalLeaderUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6)
    covered_location_ids: Optional[list[int]] = None


class LocalLeaderResponse(BaseModel):
    local_leader_id: int
    full_name: str
    phone_number: str
    email: Optional[str] = None
    is_active: bool
    covered_location_ids: list[int] = Field(default_factory=list)
    covered_location_names: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocalLeaderLoginRequest(BaseModel):
    phone_number: str
    password: str


class LocalLeaderMeResponse(BaseModel):
    local_leader_id: int
    full_name: str
    phone_number: str
    email: Optional[str] = None
    covered_location_ids: list[int] = Field(default_factory=list)

    class Config:
        from_attributes = True


class LocalLeaderToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LocalLeaderRequestCodeRequest(BaseModel):
    phone_number: str


class LocalLeaderSetPasswordRequest(BaseModel):
    phone_number: str
    code: str
    new_password: str = Field(..., min_length=6)


class LocalLeaderVerifyLoginCodeRequest(BaseModel):
    phone_number: str
    code: str

