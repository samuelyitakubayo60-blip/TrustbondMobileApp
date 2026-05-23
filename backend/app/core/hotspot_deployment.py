"""Deploy special units to hotspots and notify unit commanders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.core.email import is_smtp_configured, send_unit_commander_hotspot_deployment_email
from app.models.deployment_decision import DeploymentDecision
from app.models.hotspot import Hotspot
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.models.special_assignment_unit import SpecialAssignmentUnit

_log = logging.getLogger(__name__)


def _commander_label(user: PoliceUser | None) -> str:
    if not user:
        return "Commander"
    parts = [user.first_name or "", user.last_name or ""]
    name = " ".join(p for p in parts if p).strip()
    return name or user.email or "Commander"


def deploy_hotspot_unit(
    db: Session,
    hotspot: Hotspot,
    *,
    unit_code: str,
    decided_by: PoliceUser,
    note: str | None = None,
) -> tuple[Hotspot, SpecialAssignmentUnit, dict]:
    """
    Assign unit to hotspot, record deployment on linked reports, email unit commander.
    Returns (hotspot, unit, result_meta).
    """
    code = (unit_code or "").strip().upper().replace(" ", "_")
    unit = (
        db.query(SpecialAssignmentUnit)
        .options(joinedload(SpecialAssignmentUnit.commander))
        .filter(
            SpecialAssignmentUnit.unit_code == code,
            SpecialAssignmentUnit.is_active.is_(True),
        )
        .first()
    )
    if not unit:
        raise ValueError(f"Unknown or inactive unit '{code}'")

    now = datetime.now(timezone.utc)
    hotspot.assigned_unit_code = code
    hotspot.deployed_at = now
    hotspot.deployment_note = (note or "").strip() or None
    if hotspot.controlled_by_user_id is None:
        hotspot.controlled_by_user_id = decided_by.police_user_id

    reports = list(getattr(hotspot, "reports", None) or [])
    decisions_created = 0
    for report in reports:
        if report.leader_verification_status != "confirmed":
            continue
        existing = (
            db.query(DeploymentDecision)
            .filter(DeploymentDecision.report_id == str(report.report_id))
            .first()
        )
        if existing:
            existing.deployment_status = "deployed"
            existing.assigned_unit = code
            existing.deployed_at = now
            if note:
                existing.decision_note = note
        else:
            db.add(
                DeploymentDecision(
                    report_id=str(report.report_id),
                    decided_by=decided_by.police_user_id,
                    deployment_status="deployed",
                    assigned_unit=code,
                    deployment_priority=report.priority or "medium",
                    decision_note=note,
                    deployed_at=now,
                )
            )
            decisions_created += 1

    email_sent = False
    email_error = None
    commander = getattr(unit, "commander", None)
    if commander and commander.email and is_smtp_configured():
        area = "cluster area"
        if reports and getattr(reports[0], "village_location", None):
            area = reports[0].village_location.location_name or area
        ok, err = send_unit_commander_hotspot_deployment_email(
            commander.email,
            commander_name=_commander_label(commander),
            unit_name=unit.unit_name,
            unit_code=code,
            hotspot_id=int(hotspot.hotspot_id),
            incident_count=len(reports),
            area_label=area,
            deployed_by_name=_commander_label(decided_by),
            note=note,
        )
        email_sent = ok
        email_error = err
    elif commander and not commander.email:
        email_error = "Unit commander has no email on file"
    elif not is_smtp_configured():
        email_error = "Email not configured on server"

    db.add(hotspot)
    db.commit()
    db.refresh(hotspot)

    return (
        hotspot,
        unit,
        {
            "decisions_created": decisions_created,
            "email_sent": email_sent,
            "email_error": email_error,
            "commander_email": getattr(commander, "email", None) if commander else None,
        },
    )


def take_hotspot_control(db: Session, hotspot: Hotspot, user: PoliceUser) -> Hotspot:
    hotspot.controlled_by_user_id = user.police_user_id
    db.add(hotspot)
    db.commit()
    db.refresh(hotspot)
    return hotspot
