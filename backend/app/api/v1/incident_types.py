from decimal import Decimal
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.websocket import manager
import asyncio

from app.database import get_db
from app.models.incident_type import IncidentType
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.api.v1.auth import get_current_admin, get_optional_user
from app.schemas.incident_type import (
    IncidentTypeCreate,
    IncidentTypeResponse,
    IncidentTypeUpdate,
)

router = APIRouter(prefix="/incident-types", tags=["incident-types"])


@router.get("/distribution")
def get_incident_distribution(
    db: Session = Depends(get_db),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
):
    """
    Aggregated report counts by incident type, sector, and police station.
    Used by the dashboard chart — returns lightweight GROUP BY counts instead
    of fetching hundreds of full report objects.
    """
    # Counts by incident type
    by_type = (
        db.query(IncidentType.type_name, func.count(Report.report_id).label("cnt"))
        .join(Report, Report.incident_type_id == IncidentType.incident_type_id)
        .group_by(IncidentType.type_name)
        .order_by(func.count(Report.report_id).desc())
        .all()
    )

    # Counts by sector — resolve via village → cell → sector hierarchy (2 levels up)
    cell_alias = db.query(
        Location.location_id.label("village_id"),
        Location.parent_location_id.label("cell_id"),
    ).filter(Location.location_type == "village").subquery()

    sector_alias = db.query(
        Location.location_id.label("cell_id"),
        Location.parent_location_id.label("sector_id"),
    ).filter(Location.location_type == "cell").subquery()

    sector_names_sq = db.query(
        Location.location_id.label("sector_id"),
        Location.location_name.label("sector_name"),
    ).filter(Location.location_type == "sector").subquery()

    by_sector = (
        db.query(sector_names_sq.c.sector_name, func.count(Report.report_id).label("cnt"))
        .join(cell_alias, Report.village_location_id == cell_alias.c.village_id)
        .join(sector_alias, cell_alias.c.cell_id == sector_alias.c.cell_id)
        .join(sector_names_sq, sector_alias.c.sector_id == sector_names_sq.c.sector_id)
        .group_by(sector_names_sq.c.sector_name)
        .order_by(func.count(Report.report_id).desc())
        .all()
    )

    return {
        "incident_types": {row[0]: row[1] for row in by_type},
        "sectors": {row[0]: row[1] for row in by_sector},
    }


@router.get("/", response_model=List[IncidentTypeResponse])
def get_incident_types(
    include_inactive: bool = Query(False, description="Include inactive types (admin only)."),
    db: Session = Depends(get_db),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
):
    """
    List incident types. By default returns only active (for mobile app).
    If include_inactive=true, requires admin; returns all types.
    """
    if include_inactive:
        if not current_user or current_user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        types = db.query(IncidentType).order_by(IncidentType.type_name).all()
    else:
        types = db.query(IncidentType).filter(IncidentType.is_active == True).order_by(IncidentType.type_name).all()
    return types


@router.post("/", response_model=IncidentTypeResponse, status_code=status.HTTP_201_CREATED)
def create_incident_type(
    payload: IncidentTypeCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """Create a new incident type (admin only)."""
    existing = db.query(IncidentType).filter(IncidentType.type_name == payload.type_name.strip()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An incident type with this name already exists")
    obj = IncidentType(
        type_name=payload.type_name.strip(),
        description=payload.description.strip() if payload.description else None,
        semantic_definition=payload.semantic_definition.strip() if payload.semantic_definition else None,
        severity_weight=payload.severity_weight,
        is_active=payload.is_active,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
    background_tasks.add_task(notify)

    return obj


@router.get("/{incident_type_id}", response_model=IncidentTypeResponse)
def get_incident_type(
    incident_type_id: int,
    db: Session = Depends(get_db),
):
    """Get one incident type by ID (for editing)."""
    obj = db.query(IncidentType).filter(IncidentType.incident_type_id == incident_type_id).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident type not found")
    return obj


@router.put("/{incident_type_id}", response_model=IncidentTypeResponse)
def update_incident_type(
    incident_type_id: int,
    payload: IncidentTypeUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """Update an incident type (admin only)."""
    obj = db.query(IncidentType).filter(IncidentType.incident_type_id == incident_type_id).first()
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident type not found")
    if payload.type_name is not None:
        name = payload.type_name.strip()
        other = db.query(IncidentType).filter(IncidentType.type_name == name, IncidentType.incident_type_id != incident_type_id).first()
        if other:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="An incident type with this name already exists")
        obj.type_name = name
    if payload.description is not None:
        obj.description = payload.description.strip() or None
    if payload.semantic_definition is not None:
        obj.semantic_definition = payload.semantic_definition.strip() or None
    if payload.severity_weight is not None:
        obj.severity_weight = payload.severity_weight
    if payload.is_active is not None:
        obj.is_active = payload.is_active
    db.add(obj)
    db.commit()
    db.refresh(obj)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
    background_tasks.add_task(notify)

    return obj


@router.delete("/{incident_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_incident_type(
    incident_type_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin)] = None,
):
    """Hard-delete an incident type (admin only)."""
    obj = (
        db.query(IncidentType)
        .filter(IncidentType.incident_type_id == incident_type_id)
        .first()
    )
    if not obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident type not found",
        )
    db.delete(obj)
    db.commit()

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "incident_type"}))
    background_tasks.add_task(notify)

    return {}
