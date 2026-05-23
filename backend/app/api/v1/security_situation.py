"""District / station security overview — read-only incident counts (no drill-down)."""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased

from app.api.v1.auth import get_current_user
from app.database import get_db
from app.models.incident_type import IncidentType
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.station import Station
from app.models.station_coverage import StationCoverageCell
from pydantic import BaseModel

router = APIRouter(prefix="/security-situation", tags=["security-situation"])


class IncidentTypeCount(BaseModel):
    incident_type_id: Optional[int]
    type_name: str
    count: int


class SectorCount(BaseModel):
    sector_name: str
    count: int


class DistrictSecurityOverview(BaseModel):
    scope_label: str
    total_incidents: int
    by_incident_type: List[IncidentTypeCount]
    by_sector: List[SectorCount]


def _station_covered_village_ids(db: Session, station_id: int) -> List[int]:
    cell_rows = (
        db.query(StationCoverageCell.cell_location_id)
        .filter(StationCoverageCell.station_id == station_id)
        .all()
    )
    cell_ids = [int(r[0]) for r in cell_rows if r and r[0] is not None]
    if not cell_ids:
        return []
    village_rows = (
        db.query(Location.location_id)
        .filter(
            Location.location_type == "village",
            Location.parent_location_id.in_(cell_ids),
        )
        .all()
    )
    return sorted({int(r[0]) for r in village_rows if r and r[0] is not None})


def _verified_reports_query(db: Session):
    return db.query(Report).filter(
        Report.verification_status == "verified",
        Report.rule_status != "flagged",
    )


def _apply_officer_report_scope(query, db: Session, current_user: PoliceUser):
    """Only station officers are scoped; DPC and IO see the full district."""
    if getattr(current_user, "role", None) != "officer":
        return query
    station_id = getattr(current_user, "station_id", None)
    if station_id is None:
        raise HTTPException(status_code=403, detail="Officer station is not configured")
    covered = _station_covered_village_ids(db, station_id)
    filters = [
        Report.handling_station_id == station_id,
        Report.assignments.any(
            ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
        ),
    ]
    if covered:
        filters.append(Report.village_location_id.in_(covered))
    return query.filter(or_(*filters))


@router.get("/district-overview", response_model=DistrictSecurityOverview)
def district_security_overview(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """
    Read-only district (or station) incident totals by type and sector.
  No links — use Security Situation for case management.
    """
    role = getattr(current_user, "role", None)
    base = _apply_officer_report_scope(_verified_reports_query(db), db, current_user)

    if role == "officer":
        station = (
            db.query(Station)
            .filter(Station.station_id == current_user.station_id)
            .first()
        )
        scope_label = station.station_name if station else "Your station area"
    else:
        scope_label = "Musanze District"

    total_incidents = base.with_entities(func.count(Report.report_id)).scalar() or 0

    type_rows = (
        base.join(IncidentType, Report.incident_type_id == IncidentType.incident_type_id)
        .with_entities(
            IncidentType.incident_type_id,
            IncidentType.type_name,
            func.count(Report.report_id).label("cnt"),
        )
        .group_by(IncidentType.incident_type_id, IncidentType.type_name)
        .order_by(func.count(Report.report_id).desc())
        .all()
    )
    by_incident_type = [
        IncidentTypeCount(
            incident_type_id=int(r[0]) if r[0] is not None else None,
            type_name=(r[1] or "Unknown").strip() or "Unknown",
            count=int(r[2] or 0),
        )
        for r in type_rows
        if int(r[2] or 0) > 0
    ]

    Village = aliased(Location)
    Cell = aliased(Location)
    Sector = aliased(Location)
    sector_rows = (
        base.with_entities(
            Sector.location_name,
            func.count(Report.report_id).label("cnt"),
        )
        .outerjoin(Village, Report.village_location_id == Village.location_id)
        .outerjoin(Cell, Village.parent_location_id == Cell.location_id)
        .outerjoin(Sector, Cell.parent_location_id == Sector.location_id)
        .filter(Sector.location_id.isnot(None))
        .group_by(Sector.location_name)
        .order_by(func.count(Report.report_id).desc())
        .limit(20)
        .all()
    )
    by_sector = [
        SectorCount(sector_name=(r[0] or "Unknown").strip() or "Unknown", count=int(r[1] or 0))
        for r in sector_rows
        if int(r[1] or 0) > 0
    ]

    return DistrictSecurityOverview(
        scope_label=scope_label,
        total_incidents=int(total_incidents),
        by_incident_type=by_incident_type,
        by_sector=by_sector,
    )
