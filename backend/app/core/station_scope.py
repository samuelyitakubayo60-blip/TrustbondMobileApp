"""Station coverage helpers for officer / IO (supervisor) data scoping."""
from __future__ import annotations

from typing import Iterable, Optional, Set

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.station import Station
from app.models.station_coverage import StationCoverageCell


def role_uses_station_scope(role: Optional[str]) -> bool:
    return role in ("officer", "supervisor")


def user_station_id(user: PoliceUser) -> Optional[int]:
    sid = getattr(user, "station_id", None)
    return int(sid) if sid is not None else None


def require_station_id(user: PoliceUser) -> int:
    sid = user_station_id(user)
    if sid is None:
        raise HTTPException(
            status_code=403,
            detail="Your police station is not configured on your account. Contact an administrator.",
        )
    return sid


def get_station(db: Session, station_id: int) -> Optional[Station]:
    return db.query(Station).filter(Station.station_id == station_id).first()


def station_covered_cell_ids(db: Session, station_id: int) -> Set[int]:
    return {
        int(row[0])
        for row in db.query(StationCoverageCell.cell_location_id)
        .filter(StationCoverageCell.station_id == station_id)
        .all()
    }


def station_covered_village_ids(db: Session, station: Station) -> Set[int]:
    covered_cell_ids = station_covered_cell_ids(db, int(station.station_id))
    if covered_cell_ids:
        return {
            int(row[0])
            for row in db.query(Location.location_id)
            .filter(
                Location.location_type == "village",
                Location.parent_location_id.in_(covered_cell_ids),
            )
            .all()
        }
    return set()


def station_scope_location_ids(db: Session, station_id: int) -> Set[int]:
    """Village + cell location IDs covered by a station."""
    cells = station_covered_cell_ids(db, station_id)
    villages: Set[int] = set()
    if cells:
        villages = {
            int(row[0])
            for row in db.query(Location.location_id)
            .filter(
                Location.location_type == "village",
                Location.parent_location_id.in_(cells),
            )
            .all()
        }
    return cells | villages


def report_scope_filters_for_station(
    db: Session, station: Station, *, role: Optional[str] = None
) -> list:
    """
    SQLAlchemy OR filters for reports belonging to a station.

    Officers: geography-first (villages under station cells). Assignments/handling
    outside that geography are excluded so counts match the station area only.

    Supervisors / IO: broader OR (handling, assignments, village coverage).
    """
    station_id = int(station.station_id)
    covered_village_ids = station_covered_village_ids(db, station)

    if role == "officer":
        if covered_village_ids:
            return [
                Report.village_location_id.in_(list(covered_village_ids)),
                and_(
                    Report.village_location_id.is_(None),
                    or_(
                        Report.handling_station_id == station_id,
                        Report.assignments.any(
                            ReportAssignment.police_user.has(
                                PoliceUser.station_id == station_id
                            )
                        ),
                    ),
                ),
            ]
        return [
            Report.handling_station_id == station_id,
            Report.assignments.any(
                ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
            ),
        ]

    scope_filters = [
        Report.handling_station_id == station_id,
        Report.assignments.any(
            ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
        ),
    ]
    if covered_village_ids:
        scope_filters.append(Report.village_location_id.in_(list(covered_village_ids)))
    return scope_filters


def apply_report_list_scope(query: Query, db: Session, user: PoliceUser) -> Query:
    """Restrict a Report query to the current user's district or station scope."""
    role = getattr(user, "role", None)
    if role == "admin":
        return query
    if role not in ("officer", "supervisor"):
        return query

    station_id = user_station_id(user)
    if station_id is None:
        raise HTTPException(
            status_code=403,
            detail="Your police station is not configured on your account.",
        )

    station = get_station(db, int(station_id))
    if not station:
        return query.filter(False)

    filters = report_scope_filters_for_station(db, station, role=role)
    return query.filter(or_(*filters))


def station_covered_sector_ids(db: Session, station_id: int) -> Set[int]:
    """Sector location_ids touched by this station's covered cells."""
    cell_ids = station_covered_cell_ids(db, station_id)
    if not cell_ids:
        return set()
    rows = (
        db.query(Location.parent_location_id)
        .filter(
            Location.location_id.in_(list(cell_ids)),
            Location.location_type == "cell",
        )
        .all()
    )
    return {int(r[0]) for r in rows if r and r[0] is not None}


def station_visible_report_ids(
    db: Session, station_id: int, *, role: Optional[str] = "officer"
) -> Set[str]:
    station = get_station(db, station_id)
    if not station:
        return set()
    rows = (
        db.query(Report.report_id)
        .filter(or_(*report_scope_filters_for_station(db, station, role=role)))
        .distinct()
        .all()
    )
    return {str(rid) for (rid,) in rows}


def leader_ids_in_station_scope(db: Session, station_id: int) -> Set[int]:
    scope_ids = station_scope_location_ids(db, station_id)
    if not scope_ids:
        return set()
    rows = (
        db.query(LocalLeaderCoverageLocation.local_leader_id)
        .filter(LocalLeaderCoverageLocation.location_id.in_(list(scope_ids)))
        .distinct()
        .all()
    )
    return {int(r[0]) for r in rows if r and r[0] is not None}


def assert_leader_in_station_scope(db: Session, leader_id: int, station_id: int) -> None:
    allowed = leader_ids_in_station_scope(db, station_id)
    if int(leader_id) not in allowed:
        raise HTTPException(
            status_code=403,
            detail="This local leader is outside your station coverage.",
        )


def assert_locations_in_station_scope(
    db: Session, location_ids: Iterable[int], station_id: int
) -> None:
    scope_ids = station_scope_location_ids(db, station_id)
    for lid in location_ids:
        if int(lid) not in scope_ids:
            raise HTTPException(
                status_code=400,
                detail="Selected village or cell is outside your station coverage.",
            )


def filter_leaders_to_station(query, db: Session, station_id: int):
    leader_ids = leader_ids_in_station_scope(db, station_id)
    if not leader_ids:
        return query.filter(False)
    return query.filter(LocalLeader.local_leader_id.in_(list(leader_ids)))
