"""Local leader workflow: coverage helpers and DPU/auto-case gating."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.local_leader_coverage import LocalLeaderCoverageLocation
from app.models.report import Report


def leader_covered_village_ids(db: Session, leader_id: int) -> set[int]:
    """Normalize active leader coverage (village or cell) to village ids."""
    leader_active = (
        db.query(LocalLeader.local_leader_id)
        .filter(
            LocalLeader.local_leader_id == leader_id,
            LocalLeader.is_active.is_(True),
        )
        .first()
    )
    if not leader_active:
        return set()

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


def report_is_leader_submitted(report: Report) -> bool:
    """Incident filed by a logged-in local leader (not only community-confirmed later)."""
    return getattr(report, "submitted_by_local_leader_id", None) is not None


def apply_leader_submission_verification(
    report: Report,
    db: Session,
    *,
    evidence_count: int = 0,
) -> None:
    """
    Leader-submitted reports: trust mobile gates only (location, original evidence, no tampering).
    Skip unified ML / threshold scorecard; mark police verification as satisfied via attestation.
    """
    from app.core.report_priority import calculate_report_priority

    report.rule_status = "passed"
    report.is_flagged = False
    report.verification_status = "verified"
    report.flag_reason = None
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["verification_path"] = "local_leader_submission"
    fv["mobile_verification_only"] = True
    report.feature_vector = fv
    report.priority = calculate_report_priority(report, evidence_count, db, {})
    report.ai_verification_reason = (
        "Local leader submission: verified using mobile checks only "
        "(original evidence, location consistency, no tampering). "
        "Automated AI credibility scoring was not applied."
    )
    if evidence_count > 0:
        report.ai_evidence_description = (
            f"Leader-attested incident with {evidence_count} evidence file(s). "
            "Server-side AI evidence analysis skipped."
        )
    else:
        report.ai_evidence_description = (
            "Leader-attested text-only incident. Server-side AI analysis skipped."
        )


def report_meets_leader_confirmation(report: Report) -> bool:
    """Incident is cleared for DPU analytics / public-style clustering when community confirmed."""
    st = (getattr(report, "leader_verification_status", None) or "pending").strip().lower()
    if st == "rejected":
        return False
    if st == "confirmed":
        return True
    return False


def report_police_verified(report: Report) -> bool:
    """Police/AI pipeline accepted the report (verified), not merely under_review or rejected."""
    return (getattr(report, "verification_status", None) or "").strip().lower() == "verified"


def report_ready_for_cases_and_hotspots(report: Report) -> bool:
    """
    Operational eligibility for auto-cases and hotspot clustering.

    Citizen-submitted (when leader gate is on):
    1. Police/AI: verification_status == verified
    2. Community: leader_verification_status == confirmed

    Leader-submitted: mobile basic checks at submit + leader attestation (no AI threshold);
    both gates are satisfied when verification_status is verified and leader confirmed.
    """
    if report_is_leader_submitted(report):
        if not report_police_verified(report):
            return False
        if not leader_gate_enabled():
            return True
        return report_meets_leader_confirmation(report)
    if not report_police_verified(report):
        return False
    if not leader_gate_enabled():
        return True
    return report_meets_leader_confirmation(report)


def report_eligible_for_auto_case(report: Report) -> bool:
    """Alias for case linking; same rules as hotspot operational eligibility."""
    return report_ready_for_cases_and_hotspots(report)


def apply_leader_confirmed_filter_reports(query, report_model):
    """Narrow a SQLAlchemy query to leader-confirmed incidents (DPU / safety analytics)."""
    if not leader_gate_enabled():
        return query
    return query.filter(report_model.leader_verification_status == "confirmed")
