from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.schemas.location import LocationResponse

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/", response_model=List[LocationResponse])
def list_locations(
    db: Session = Depends(get_db),
    _: Annotated[PoliceUser, Depends(get_current_user)] = None,
    location_type: Optional[str] = Query(None, description="Filter by type: sector, cell, village"),
    parent_id: Optional[int] = Query(None, description="Filter by parent_location_id (e.g. sectors for parent_id=null)"),
    limit: int = Query(500, ge=1, le=2000),
):
    """List locations (sectors, cells, villages). Auth required."""
    query = db.query(Location).filter(Location.is_active == True)
    if location_type:
        query = query.filter(Location.location_type == location_type)
    if parent_id is not None:
        query = query.filter(Location.parent_location_id == parent_id)
    query = query.order_by(Location.location_type, Location.location_name)
    return query.limit(limit).all()
