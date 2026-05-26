"""
Audit logging: write actions to audit_logs table.
"""
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.police_user import PoliceUser
import logging

logger = logging.getLogger(__name__)


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
    # Normalize actor fields. If caller forgot actor_id, treat it as a system action;
    # otherwise role-based filtering can hide the row for officers/supervisors.
    if actor_type == "police_user" and actor_id is None:
        actor_type = "system"

    actor_role = None
    if actor_type == "police_user" and actor_id is not None:
        try:
            user = (
                db.query(PoliceUser)
                .filter(PoliceUser.police_user_id == actor_id)
                .first()
            )
            actor_role = user.role if user else None
        except Exception as exc:
            logger.warning("Audit log_action: failed to resolve actor role: %s", exc)

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
    # Flush so DB errors surface in the request logs (commit may happen later).
    try:
        db.flush()
        logger.info(
            "AUDIT write queued: action=%s actor=%s:%s entity=%s:%s success=%s",
            action_type,
            actor_type,
            actor_id,
            entity_type,
            entity_id,
            success,
        )
    except Exception as exc:
        logger.exception("AUDIT write failed (flush): %s", exc)
        # Keep behavior: caller decides whether to rollback/raise.


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
