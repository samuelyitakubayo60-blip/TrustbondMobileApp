from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.audit_log import AuditLog
from app.api.v1.auth import get_current_admin
from app.models.police_user import PoliceUser
from app.schemas.audit import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("/", response_model=List[AuditLogResponse])
def list_audit_logs(
    current_user: Annotated[PoliceUser, Depends(get_current_admin)],
    db: Session = Depends(get_db),
    entity_type: Optional[str] = Query(None, description="Filter by entity_type (e.g. report)."),
    entity_id: Optional[str] = Query(None, description="Filter by entity_id."),
    action_type: Optional[str] = Query(None, description="Filter by action_type."),
    limit: int = Query(100, ge=1, le=500),
):
    """List audit log entries. Admin only."""
    query = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .options()
    )
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)

    logs = query.limit(limit).all()

    # Preload badge/name map for police users referenced in logs
    actor_ids = {l.actor_id for l in logs if l.actor_type == "police_user" and l.actor_id}
    badge_by_id = {}
    name_by_id = {}
    if actor_ids:
        users = db.query(PoliceUser).filter(PoliceUser.police_user_id.in_(actor_ids)).all()
        for u in users:
            badge_by_id[u.police_user_id] = u.badge_number
            name_by_id[u.police_user_id] = f"{u.first_name} {u.last_name}"

    out: List[AuditLogResponse] = []
    for l in logs:
        badge = None
        name = None
        if l.actor_type == "police_user" and l.actor_id:
            badge = badge_by_id.get(l.actor_id)
            name = name_by_id.get(l.actor_id)
        out.append(
            AuditLogResponse(
                log_id=l.log_id,
                actor_type=l.actor_type,
                actor_id=l.actor_id,
                actor_badge=badge,
                actor_name=name,
                action_type=l.action_type,
                entity_type=l.entity_type,
                entity_id=l.entity_id,
                action_details=l.action_details,
                ip_address=l.ip_address,
                user_agent=getattr(l, "user_agent", None),
                success=l.success,
                created_at=l.created_at,
            )
        )
    return out
