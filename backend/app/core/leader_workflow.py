"""Local leader workflow: coverage helpers and DPU/auto-case gating."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.location import Location
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.report import Report


def leader_covered_village_ids(db: Session, leader_id: int) -> set[int]:
    """Normalize leader coverage (village or cell) to village ids."""
    covered_ids = {
        int(r[0])
        for r in db.query(LocalLeaderCoverageLocation.location_id)
        .filter(LocalLeaderCoverageLocation.local_leader_id == leader_id)
        .all()
    }
    if not covered_ids:
        return set()

    rows = (
        db.query(Location.location_id, Location.location_type, Location.parent_location_id)
        .filter(Location.location_id.in_(covered_ids))
        .all()
    )
    village_ids: set[int] = set()
    cell_ids: set[int] = set()
    for loc_id, loc_type, _parent_id in rows:
        if loc_type == "village":
            village_ids.add(int(loc_id))
        elif loc_type == "cell":
            cell_ids.add(int(loc_id))

    if cell_ids:
        vrows = (
            db.query(Location.location_id)
            .filter(
                Location.location_type == "village",
                Location.parent_location_id.in_(cell_ids),
            )
            .all()
        )
        village_ids.update(int(r[0]) for r in vrows)

    return village_ids


def local_leader_ids_covering_village(db: Session, village_id: Optional[int]) -> list[int]:
    """Leaders whose coverage includes this village (direct village or parent cell)."""
    if village_id is None:
        return []
    vid = int(village_id)
    ids: set[int] = set()
    for row in (
        db.query(LocalLeaderCoverageLocation.local_leader_id)
        .filter(LocalLeaderCoverageLocation.location_id == vid)
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
            .filter(LocalLeaderCoverageLocation.location_id == int(parent_cell_id))
            .all()
        ):
            ids.add(int(row[0]))
    return sorted(ids)


def leader_gate_enabled() -> bool:
    return bool(getattr(settings, "require_leader_confirmation_for_workflow", True))


def report_meets_leader_confirmation(report: Report) -> bool:
    """Incident is cleared for DPU analytics / public-style clustering when community confirmed."""
    st = (getattr(report, "leader_verification_status", None) or "pending").strip().lower()
    if st == "rejected":
        return False
    if st == "confirmed":
        return True
    return False


def report_eligible_for_auto_case(report: Report) -> bool:
    """Auto-case linking/creation requires police verification and (if enabled) leader confirmation."""
    if not leader_gate_enabled():
        return True
    return report_meets_leader_confirmation(report)


def apply_leader_confirmed_filter_reports(query, report_model):
    """Narrow a SQLAlchemy query to leader-confirmed incidents (DPU / safety analytics)."""
    if not getattr(settings, "dpu_analytics_require_leader_confirmation", True):
        return query
    return query.filter(report_model.leader_verification_status == "confirmed")
