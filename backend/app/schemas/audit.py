from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any


class AuditLogResponse(BaseModel):
    log_id: int
    actor_type: str
    actor_id: Optional[int] = None
    action_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    action_details: Optional[dict[str, Any]] = None
    success: bool
    created_at: datetime

    class Config:
        from_attributes = True
