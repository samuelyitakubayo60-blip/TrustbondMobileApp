from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class NotificationResponse(BaseModel):
    notification_id: UUID
    police_user_id: int
    title: str
    message: Optional[str] = None
    type: str
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
