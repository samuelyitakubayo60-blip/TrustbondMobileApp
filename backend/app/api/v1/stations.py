from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.orm import Session, joinedload, selectinload
from app.core.websocket import manager
import asyncio
from sqlalchemy import func
from sqlalchemy.exc import ProgrammingError

from app.database import get_db
from app.models.station import Station
from app.models.station_coverage import StationCoverageCell
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_admin, get_current_admin_or_supervisor, get_current_user
from app.schemas.station import (
    StationCreate,
    StationUpdate,
    StationResponse,
    StationListResponse,
    StationCasesResponse,
    StationIncidentGroup,
)

router = APIRouter(prefix="/stations", tags=["stations"])


_ACTIVE_CASE_STATUSES = ("open", "investigating")


def _station_case_metrics(db: Session, station_id: int) -> tuple[int, int]:
    from app.models.case import Case

    active = (
        db.query(func.count(Case.case_id))
        .filter(
            Case.station_id == station_id,
            Case.status.in_(_ACTIVE_CASE_STATUSES),
        )
        .scalar()
        or 0
    )
    incidents = (
        db.query(func.coalesce(func.sum(Case.report_count), 0))
        .filter(
            Case.station_id == station_id,
            Case.status.in_(_ACTIVE_CASE_STATUSES),
        )
        .scalar()
        or 0
    )
    return int(active), int(incidents)


def _to_response(st: Station, *, metrics: tuple[int, int] | None = None) -> StationResponse:
    covered_cells = sorted(
        [
            cc
            # Avoid lazy-loading if DB migration hasn't created the table yet.
            for cc in (st.__dict__.get("coverage_cells") or [])
            if cc.cell_location is not None
        ],
        key=lambda cc: (cc.cell_location.location_name or "").lower(),
    )
    active_cases = metrics[0] if metrics else None
    total_incidents = metrics[1] if metrics else None
    return StationResponse(
        station_id=st.station_id,
        station_code=st.station_code,
        station_name=st.station_name,
        station_type=st.station_type,
        latitude=float(st.latitude) if st.latitude is not None else None,
        longitude=float(st.longitude) if st.longitude is not None else None,
        address_text=st.address_text,
        phone_number=st.phone_number,
        email=st.email,
        is_active=st.is_active,
        covered_cell_ids=[cc.cell_location_id for cc in covered_cells],
        covered_cell_names=[cc.cell_location.location_name for cc in covered_cells],
        active_case_count=active_cases,
        total_incident_count=total_incidents,
        created_at=st.created_at,
        updated_at=st.updated_at,
    )


def _resolve_valid_cell_ids(db: Session, covered_cell_ids: list[int]) -> list[int]:
    deduped_ids = sorted({int(x) for x in covered_cell_ids})
    if not deduped_ids:
        return []
    rows = (
        db.query(Location.location_id)
        .filter(
            Location.location_id.in_(deduped_ids),
            Location.location_type == "cell",
        )
        .all()
    )
    valid_ids = sorted({int(r[0]) for r in rows})
    if len(valid_ids) != len(deduped_ids):
        invalid_ids = sorted(set(deduped_ids) - set(valid_ids))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cell ids: {invalid_ids}. Coverage accepts cell-level locations only.",
        )
    return valid_ids


def _replace_station_coverage_cells(db: Session, station: Station, covered_cell_ids: list[int]) -> None:
    db.query(StationCoverageCell).filter(
        StationCoverageCell.station_id == station.station_id
    ).delete(synchronize_session=False)
    for cell_id in covered_cell_ids:
        db.add(
            StationCoverageCell(
                station_id=station.station_id,
                cell_location_id=cell_id,
            )
        )


@router.get("/coverage/options")
def station_coverage_options(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    station_id: Optional[int] = Query(None),
):
    """Return sectors + cells for checkbox UI, plus selected cell ids for a station."""
    sectors = (
        db.query(Location)
        .filter(
            Location.location_type == "sector",
            Location.is_active == True,
        )
        .order_by(Location.location_name.asc())
        .all()
    )
    sector_ids = [s.location_id for s in sectors]
    cells = (
        db.query(Location)
        .filter(
            Location.location_type == "cell",
            Location.parent_location_id.in_(sector_ids) if sector_ids else False,
            Location.is_active == True,
        )
        .order_by(Location.location_name.asc())
        .all()
    )

    cells_by_sector: dict[int, list[dict]] = {}
    for c in cells:
        parent_id = int(c.parent_location_id) if c.parent_location_id is not None else None
        if parent_id is None:
            continue
        cells_by_sector.setdefault(parent_id, []).append(
            {
                "cell_id": c.location_id,
                "cell_name": c.location_name,
            }
        )

    selected_cell_ids: list[int] = []
    if station_id is not None:
        exists = db.query(Station.station_id).filter(Station.station_id == station_id).first()
        if exists:
            try:
                selected_cell_ids = [
                    int(row[0])
                    for row in db.query(StationCoverageCell.cell_location_id)
                    .filter(StationCoverageCell.station_id == station_id)
                    .all()
                ]
            except ProgrammingError as e:
                if "station_coverage_cells" in str(e).lower():
                    selected_cell_ids = []
                else:
                    raise

    items = [
        {
            "sector_id": s.location_id,
            "sector_name": s.location_name,
            "cells": cells_by_sector.get(s.location_id, []),
        }
        for s in sectors
    ]
    return {
        "items": items,
        "selected_cell_ids": sorted(selected_cell_ids),
    }


@router.get("/", response_model=StationListResponse)
def list_stations(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None),
    only_active: bool = Query(False),
    include_metrics: bool = Query(
        False,
        description="Include active case and incident counts per station (Security Situation cards).",
    ),
):
    """List police stations. Officers only see their own station."""
    q = db.query(Station)
    if getattr(current_user, "role", None) == "officer" and current_user.station_id:
        q = q.filter(Station.station_id == current_user.station_id)
    if only_active:
        q = q.filter(Station.is_active == True)
    if search:
        like = f"%{search}%"
        q = q.filter(
            (Station.station_name.ilike(like))
            | (Station.station_code.ilike(like))
        )
    try:
        q_cov = q.options(
            selectinload(Station.coverage_cells).joinedload(StationCoverageCell.cell_location),
        )
        total = q_cov.count()
        items = q_cov.order_by(Station.station_name.asc()).all()
    except ProgrammingError as e:
        if "station_coverage_cells" not in str(e).lower():
            raise
        # Table not migrated yet: still return stations without coverage details.
        total = q.count()
        items = q.order_by(Station.station_name.asc()).all()
    responses = []
    for s in items:
        metrics = _station_case_metrics(db, s.station_id) if include_metrics else None
        responses.append(_to_response(s, metrics=metrics))
    return StationListResponse(items=responses, total=total)


@router.get("/{station_id}/cases", response_model=StationCasesResponse)
def get_station_cases(
    station_id: int,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter cases by status"),
):
    """Cases auto-assigned to this station, grouped by incident type."""
    from app.models.case import Case
    from app.api.v1.cases import _case_to_response

    station = db.query(Station).filter(Station.station_id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    if current_user.role == "officer":
        if current_user.station_id != station_id:
            raise HTTPException(status_code=403, detail="Not your station")

    q = (
        db.query(Case)
        .options(
            joinedload(Case.location),
            joinedload(Case.incident_type),
            joinedload(Case.assigned_to),
            joinedload(Case.station),
        )
        .filter(Case.station_id == station_id)
    )
    if status:
        q = q.filter(Case.status == status)
    else:
        q = q.filter(Case.status.in_(_ACTIVE_CASE_STATUSES))

    cases = q.order_by(Case.opened_at.desc()).all()
    active_count, incident_count = _station_case_metrics(db, station_id)

    grouped: dict[int | None, dict] = {}
    for c in cases:
        key = c.incident_type_id
        if key not in grouped:
            grouped[key] = {
                "incident_type_id": c.incident_type_id,
                "incident_type_name": c.incident_type.type_name if c.incident_type else "Other",
                "case_count": 0,
                "incident_count": 0,
                "cases": [],
            }
        grouped[key]["case_count"] += 1
        grouped[key]["incident_count"] += int(c.report_count or 0)
        grouped[key]["cases"].append(_case_to_response(c).model_dump())

    groups = [
        StationIncidentGroup(**g)
        for g in sorted(
            grouped.values(),
            key=lambda x: (-x["incident_count"], x["incident_type_name"]),
        )
    ]
    return StationCasesResponse(
        station_id=station.station_id,
        station_name=station.station_name,
        active_case_count=active_count,
        total_incident_count=incident_count,
        groups=groups,
    )


@router.post("/", response_model=StationResponse, status_code=status.HTTP_201_CREATED)
def create_station(
    payload: StationCreate,
    current_user: Annotated[PoliceUser, Depends(get_current_admin)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a new station."""
    # If code provided, enforce uniqueness; otherwise auto-generate.
    code = (payload.station_code or "").strip() or None
    if code:
        existing = (
            db.query(Station)
            .filter(Station.station_code == code)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A station with this code already exists",
            )

    covered_cell_ids = _resolve_valid_cell_ids(db, payload.covered_cell_ids or [])
    st = Station(
        station_code=code,
        station_name=payload.station_name.strip(),
        station_type=payload.station_type.strip(),
        latitude=payload.latitude,
        longitude=payload.longitude,
        address_text=payload.address_text,
        phone_number=payload.phone_number,
        email=payload.email,
        is_active=payload.is_active,
    )
    db.add(st)
    db.flush()
    _replace_station_coverage_cells(db, st, covered_cell_ids)

    # Auto-generate code if missing, now that we have station_id
    if not st.station_code:
        st.station_code = f"ST-{st.station_id:03d}"
        db.add(st)

    db.commit()
    db.refresh(st)
    
    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "station"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "station"}))
    background_tasks.add_task(notify)

    st = (
        db.query(Station)
        .options(selectinload(Station.coverage_cells).joinedload(StationCoverageCell.cell_location))
        .get(st.station_id)
    )
    return _to_response(st)


@router.get("/{station_id}", response_model=StationResponse)
def get_station(
    station_id: int,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
):
    """Get one station by id."""
    q = db.query(Station)
    try:
        q = q.options(selectinload(Station.coverage_cells).joinedload(StationCoverageCell.cell_location))
        st = q.get(station_id)
    except ProgrammingError as e:
        if "station_coverage_cells" not in str(e).lower():
            raise
        st = q.get(station_id)
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    return _to_response(st)


@router.put("/{station_id}", response_model=StationResponse)
def update_station(
    station_id: int,
    payload: StationUpdate,
    current_user: Annotated[PoliceUser, Depends(get_current_admin)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Update a station."""
    st = db.query(Station).get(station_id)
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")

    if payload.station_code is not None:
        code = payload.station_code.strip()
        other = (
            db.query(Station)
            .filter(Station.station_code == code, Station.station_id != station_id)
            .first()
        )
        if other:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A station with this code already exists",
            )
        st.station_code = code
    if payload.station_name is not None:
        st.station_name = payload.station_name.strip()
    if payload.station_type is not None:
        st.station_type = payload.station_type.strip()
    if payload.latitude is not None:
        st.latitude = payload.latitude
    if payload.longitude is not None:
        st.longitude = payload.longitude
    if payload.address_text is not None:
        st.address_text = payload.address_text
    if payload.phone_number is not None:
        st.phone_number = payload.phone_number
    if payload.email is not None:
        st.email = payload.email
    if payload.is_active is not None:
        st.is_active = payload.is_active
    if payload.covered_cell_ids is not None:
        covered_cell_ids = _resolve_valid_cell_ids(db, payload.covered_cell_ids)
        _replace_station_coverage_cells(db, st, covered_cell_ids)

    db.add(st)
    db.commit()
    db.refresh(st)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "station"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "station"}))
    background_tasks.add_task(notify)

    st = (
        db.query(Station)
        .options(selectinload(Station.coverage_cells).joinedload(StationCoverageCell.cell_location))
        .get(st.station_id)
    )
    return _to_response(st)


@router.delete("/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_station(
    station_id: int,
    current_user: Annotated[PoliceUser, Depends(get_current_admin)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Delete (hard-delete) a station."""
    st = db.query(Station).get(station_id)
    if not st:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Station not found")
    db.delete(st)
    db.commit()

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "station"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "station"}))
    background_tasks.add_task(notify)

    return {}

