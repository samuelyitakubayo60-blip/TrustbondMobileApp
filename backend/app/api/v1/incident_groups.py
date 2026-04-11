from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.models.incident_group import IncidentGroup
from app.models.incident_type import IncidentType
from app.models.police_user import PoliceUser
from app.schemas.incident_group import IncidentGroupResponse

router = APIRouter(prefix="/incident-groups", tags=["incident-groups"])


@router.get("/", response_model=List[IncidentGroupResponse])
def list_incident_groups(
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_user)] = None,
    incident_type_id: Optional[int] = Query(None, description="Filter by incident type"),
    limit: int = Query(50, ge=1, le=200),
):
    """List incident groups (spatial-temporal clusters). Auth required."""
    query = db.query(IncidentGroup).order_by(IncidentGroup.created_at.desc())
    if incident_type_id is not None:
        query = query.filter(IncidentGroup.incident_type_id == incident_type_id)
    return query.limit(limit).all()
