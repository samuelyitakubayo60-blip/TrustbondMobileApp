from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

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
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)
    return query.limit(limit).all()
