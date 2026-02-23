"""
Audit logging: write actions to audit_logs table.
"""
from typing import Any, Optional
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    action_type: str,
    *,
    actor_type: str = "police_user",
    actor_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action_details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    success: bool = True,
) -> None:
    """Append one entry to the audit log."""
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        action_details=action_details,
        ip_address=ip_address,
        success=success,
    )
    db.add(entry)
