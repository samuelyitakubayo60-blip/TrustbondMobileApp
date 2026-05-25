"""
Audit logging: write actions to audit_logs table.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.police_user import PoliceUser


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
    user_agent: Optional[str] = None,
    success: bool = True,
) -> None:
    """Append one entry to the audit log (caller must commit the session)."""
    actor_role = None
    if actor_type == "police_user" and actor_id is not None:
        user = db.query(PoliceUser).filter(PoliceUser.police_user_id == actor_id).first()
        actor_role = user.role if user else None

    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        actor_role=actor_role,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        action_details=action_details or {},
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
    )
    db.add(entry)


def record_audit(
    db: Session,
    action_type: str,
    *,
    actor_type: str = "police_user",
    actor_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action_details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    commit: bool = True,
) -> None:
    """Log an action and commit immediately (safe for endpoints that only audit)."""
    log_action(
        db,
        action_type,
        actor_type=actor_type,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action_details=action_details,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
    )
    if commit:
        db.commit()
