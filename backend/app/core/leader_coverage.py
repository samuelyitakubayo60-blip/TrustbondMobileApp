"""Local leader geographic coverage: gaps and active-leader checks."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.schemas.local_leader import LEADER_ROLE_EXECUTIVE_OF_CELL


def active_leader_ids_covering_village(db: Session, village_id: int | None) -> list[int]:
    """Active leaders covering a village (village chief and/or parent cell executive)."""
    if village_id is None:
        return []
    vid = int(village_id)
    ids: set[int] = set()
    for row in (
        db.query(LocalLeaderCoverageLocation.local_leader_id)
        .join(LocalLeader, LocalLeader.local_leader_id == LocalLeaderCoverageLocation.local_leader_id)
        .filter(
            LocalLeaderCoverageLocation.location_id == vid,
            LocalLeader.is_active.is_(True),
        )
        .all()
    ):
        ids.add(int(row[0]))
    parent_cell_id = (
        db.query(Location.parent_location_id)
        .filter(Location.location_id == vid, Location.location_type == "village")
        .scalar()
    )
    if parent_cell_id:
        for row in (
            db.query(LocalLeaderCoverageLocation.local_leader_id)
            .join(LocalLeader, LocalLeader.local_leader_id == LocalLeaderCoverageLocation.local_leader_id)
            .filter(
                LocalLeaderCoverageLocation.location_id == int(parent_cell_id),
                LocalLeader.is_active.is_(True),
            )
            .all()
        ):
            ids.add(int(row[0]))
    return sorted(ids)


def cell_has_active_executive(db: Session, cell_id: int) -> bool:
    row = (
        db.query(LocalLeader.local_leader_id)
        .join(
            LocalLeaderCoverageLocation,
            LocalLeaderCoverageLocation.local_leader_id == LocalLeader.local_leader_id,
        )
        .filter(
            LocalLeader.is_active.is_(True),
            LocalLeader.role == LEADER_ROLE_EXECUTIVE_OF_CELL,
            LocalLeaderCoverageLocation.location_id == int(cell_id),
        )
        .first()
    )
    return row is not None


def find_leader_coverage_gaps(db: Session, *, limit: int = 500) -> list[dict[str, Any]]:
    """
    Villages with no active covering leader; cells with no active cell executive.
    """
    gaps: list[dict[str, Any]] = []

    villages = (
        db.query(Location)
        .filter(Location.location_type == "village", Location.is_active.is_(True))
        .order_by(Location.location_name.asc())
        .limit(max(limit, 1))
        .all()
    )
    for v in villages:
        if active_leader_ids_covering_village(db, int(v.location_id)):
            continue
        parent_name = None
        if v.parent_location_id:
            parent = db.query(Location).filter(Location.location_id == v.parent_location_id).first()
            parent_name = getattr(parent, "location_name", None) if parent else None
        gaps.append(
            {
                "location_id": int(v.location_id),
                "location_name": v.location_name or f"Village {v.location_id}",
                "location_type": "village",
                "parent_name": parent_name,
                "missing_roles": ["village_chief_or_cell_executive"],
            }
        )
        if len(gaps) >= limit:
            return gaps

    cells = (
        db.query(Location)
        .filter(Location.location_type == "cell", Location.is_active.is_(True))
        .order_by(Location.location_name.asc())
        .limit(max(limit, 1))
        .all()
    )
    for c in cells:
        if cell_has_active_executive(db, int(c.location_id)):
            continue
        parent_name = None
        if c.parent_location_id:
            parent = db.query(Location).filter(Location.location_id == c.parent_location_id).first()
            parent_name = getattr(parent, "location_name", None) if parent else None
        gaps.append(
            {
                "location_id": int(c.location_id),
                "location_name": c.location_name or f"Cell {c.location_id}",
                "location_type": "cell",
                "parent_name": parent_name,
                "missing_roles": ["cell_executive"],
            }
        )
        if len(gaps) >= limit:
            break

    return gaps
