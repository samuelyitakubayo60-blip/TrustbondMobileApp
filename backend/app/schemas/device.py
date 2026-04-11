from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class DeviceCreate(BaseModel):
    device_hash: str


class DeviceResponse(BaseModel):
    device_id: UUID
    device_hash: str
    first_seen_at: datetime
    last_seen_at: datetime | None = None
    total_reports: int
    trusted_reports: int
    flagged_reports: int
    device_trust_score: float
    spam_flags: int | None = 0
    is_blacklisted: bool | None = False
    blacklist_reason: str | None = None

    class Config:
        from_attributes = True
