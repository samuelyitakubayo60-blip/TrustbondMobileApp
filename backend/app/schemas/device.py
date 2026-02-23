from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class DeviceCreate(BaseModel):
    device_hash: str


class DeviceResponse(BaseModel):
    device_id: UUID
    device_hash: str
    first_seen_at: datetime
    total_reports: int
    device_trust_score: float

    class Config:
        from_attributes = True
