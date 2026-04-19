from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any


class AuditLogResponse(BaseModel):
    log_id: int
    actor_type: str
    actor_id: Optional[int] = None
    actor_badge: Optional[str] = None
    actor_name: Optional[str] = None
    actor_role: Optional[str] = None
    action_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    action_details: Optional[dict[str, Any]] = None
    sensitivity_level: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool
    created_at: datetime

    class Config:
        from_attributes = True
