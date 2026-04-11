from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class StationBase(BaseModel):
  station_code: Optional[str] = None
  station_name: str
  station_type: str
  location_id: Optional[int] = None
  latitude: Optional[float] = None
  longitude: Optional[float] = None
  address_text: Optional[str] = None
  phone_number: Optional[str] = None
  email: Optional[str] = None
  is_active: bool = True

  @field_validator("phone_number")
  @classmethod
  def validate_rwanda_phone(cls, v: Optional[str]) -> Optional[str]:
    """
    Enforce optional Rwandan phone format:
    +250 7xx xxx xxx (spaces optional in input, normalized with spaces).
    """
    if not v:
      return v
    raw = "".join(ch for ch in v if ch.isdigit())
    if raw.startswith("250"):
      raw = raw  # already local with country code
    elif raw.startswith("07"):
      raw = "250" + raw[1:]
    elif raw.startswith("7"):
      raw = "250" + raw
    else:
      raise ValueError("Phone number must be a Rwandan mobile starting with +2507…")

    if len(raw) != 12 or not raw.startswith("2507"):
      raise ValueError("Phone number must be like +250 7xx xxx xxx")

    # Format as +250 7xx xxx xxx
    formatted = f"+{raw[0:3]} {raw[3:6]} {raw[6:9]} {raw[9:12]}"
    return formatted


class StationCreate(StationBase):
  pass


class StationUpdate(BaseModel):
  station_code: Optional[str] = None
  station_name: Optional[str] = None
  station_type: Optional[str] = None
  location_id: Optional[int] = None
  latitude: Optional[float] = None
  longitude: Optional[float] = None
  address_text: Optional[str] = None
  phone_number: Optional[str] = None
  email: Optional[str] = None
  is_active: Optional[bool] = None


class StationResponse(StationBase):
  station_id: int
  location_name: Optional[str] = None
  created_at: Optional[datetime] = None
  updated_at: Optional[datetime] = None

  class Config:
    from_attributes = True


class StationListResponse(BaseModel):
  items: list[StationResponse]
  total: int

