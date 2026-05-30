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
    Villages/cells with no active covering leader.

    Uses 4 set-based queries instead of N+1 loops — one query per step:
      1. All location IDs covered by any active leader
      2. All location IDs covered by active cell executives
      3. All active villages + cells (with parent IDs)
      4. Batch fetch parent names for uncovered rows
    """
    # 1. Location IDs covered by any active leader (direct assignment)
    covered_any: set[int] = {
        int(r[0])
        for r in (
            db.query(LocalLeaderCoverageLocation.location_id)
            .join(LocalLeader, LocalLeader.local_leader_id == LocalLeaderCoverageLocation.local_leader_id)
            .filter(LocalLeader.is_active.is_(True))
            .all()
        )
    }

    # 2. Location IDs covered specifically by active cell executives
    covered_by_exec: set[int] = {
        int(r[0])
        for r in (
            db.query(LocalLeaderCoverageLocation.location_id)
            .join(LocalLeader, LocalLeader.local_leader_id == LocalLeaderCoverageLocation.local_leader_id)
            .filter(
                LocalLeader.is_active.is_(True),
                LocalLeader.role == LEADER_ROLE_EXECUTIVE_OF_CELL,
            )
            .all()
        )
    }

    # 3. All active villages and cells in one query
    all_locs = (
        db.query(
            Location.location_id,
            Location.location_name,
            Location.location_type,
            Location.parent_location_id,
        )
        .filter(
            Location.location_type.in_(["village", "cell"]),
            Location.is_active.is_(True),
        )
        .order_by(Location.location_name.asc())
        .all()
    )

    villages = [(int(r[0]), r[1], r[3]) for r in all_locs if r[2] == "village"]
    cells    = [(int(r[0]), r[1], r[3]) for r in all_locs if r[2] == "cell"]

    # Determine uncovered rows before fetching parent names
    # A village is uncovered when it has no direct leader AND its parent cell has no executive
    uncovered_villages = [
        (vid, vname, parent_id)
        for vid, vname, parent_id in villages
        if vid not in covered_any and (parent_id is None or int(parent_id) not in covered_by_exec)
    ]
    uncovered_cells = [
        (cid, cname, parent_id)
        for cid, cname, parent_id in cells
        if cid not in covered_by_exec
    ]

    # 4. Batch fetch all parent names needed (single query)
    parent_ids_needed: set[int] = set()
    for _, _, pid in uncovered_villages:
        if pid is not None:
            parent_ids_needed.add(int(pid))
    for _, _, pid in uncovered_cells:
        if pid is not None:
            parent_ids_needed.add(int(pid))

    parent_name_map: dict[int, str] = {}
    if parent_ids_needed:
        for row in (
            db.query(Location.location_id, Location.location_name)
            .filter(Location.location_id.in_(parent_ids_needed))
            .all()
        ):
            parent_name_map[int(row[0])] = row[1] or ""

    # Build gap list
    gaps: list[dict[str, Any]] = []

    for vid, vname, pid in uncovered_villages:
        gaps.append({
            "location_id": vid,
            "location_name": vname or f"Village {vid}",
            "location_type": "village",
            "parent_name": parent_name_map.get(int(pid)) if pid is not None else None,
            "missing_roles": ["village_chief_or_cell_executive"],
        })
        if len(gaps) >= limit:
            return gaps

    for cid, cname, pid in uncovered_cells:
        gaps.append({
            "location_id": cid,
            "location_name": cname or f"Cell {cid}",
            "location_type": "cell",
            "parent_name": parent_name_map.get(int(pid)) if pid is not None else None,
            "missing_roles": ["cell_executive"],
        })
        if len(gaps) >= limit:
            break

    return gaps
