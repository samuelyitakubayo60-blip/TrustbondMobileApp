from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.audit_log import AuditLog
from app.api.v1.auth import get_current_user
from app.models.police_user import PoliceUser
from app.schemas.audit import AuditLogResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("/", response_model=List[AuditLogResponse])
def list_audit_logs(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    entity_type: Optional[str] = Query(None, description="Filter by entity_type (e.g. report)."),
    entity_id: Optional[str] = Query(None, description="Filter by entity_id."),
    action_type: Optional[str] = Query(None, description="Filter by action_type."),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List audit log entries with role-based access control."""
    # Use enhanced audit service with role-based access and data masking
    logs = AuditService.get_audit_logs(
        db=db,
        current_user=current_user,
        skip=skip,
        limit=limit,
        entity_type=entity_type,
        action_type=action_type
    )

    # Preload badge/name map for police users referenced in logs
    actor_ids = {int(l["actor_id"]) for l in logs if l["actor_type"] == "police_user" and l["actor_id"]}
    badge_by_id = {}
    name_by_id = {}
    if actor_ids:
        users = db.query(PoliceUser).filter(PoliceUser.police_user_id.in_(actor_ids)).all()
        for u in users:
            badge_by_id[u.police_user_id] = u.badge_number
            name_by_id[u.police_user_id] = f"{u.first_name} {u.last_name}"

    out: List[AuditLogResponse] = []
    for log_data in logs:
        badge = None
        name = None
        if log_data["actor_type"] == "police_user" and log_data["actor_id"]:
            badge = badge_by_id.get(int(log_data["actor_id"]))
            name = name_by_id.get(int(log_data["actor_id"]))
        out.append(
            AuditLogResponse(
                log_id=log_data["log_id"],
                actor_type=log_data["actor_type"],
                actor_id=log_data["actor_id"],
                actor_badge=badge,
                actor_name=name,
                actor_role=log_data.get("actor_role"),
                action_type=log_data["action_type"],
                entity_type=log_data["entity_type"],
                entity_id=log_data["entity_id"],
                action_details=log_data["details"],
                sensitivity_level=log_data.get("sensitivity_level"),
                ip_address=log_data["ip_address"],
                user_agent=log_data.get("user_agent"),
                success=log_data["success"],
                created_at=log_data["created_at"],
            )
        )
    return out
