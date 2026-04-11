from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class PoliceUserBase(BaseModel):
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    badge_number: Optional[str] = None
    role: str = Field(..., pattern="^(admin|supervisor|officer)$")
    assigned_location_id: Optional[int] = None
    station_id: Optional[int] = None
    is_active: bool = True


class PoliceUserCreate(BaseModel):
    """Create user: password and badge_number are auto-generated (password sent by email)."""
    first_name: str
    middle_name: Optional[str] = None
    last_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    role: str = Field(..., pattern="^(admin|supervisor|officer)$")
    assigned_location_id: Optional[int] = None
    station_id: Optional[int] = None
    is_active: bool = True


class PoliceUserUpdate(BaseModel):
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    badge_number: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|supervisor|officer)$")
    assigned_location_id: Optional[int] = None
    station_id: Optional[int] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6)


class PoliceUserResponse(BaseModel):
    police_user_id: int
    first_name: str
    middle_name: Optional[str]
    last_name: str
    email: EmailStr
    phone_number: Optional[str]
    badge_number: Optional[str]
    role: str
    assigned_location_id: Optional[int]
    station_id: Optional[int]
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True

