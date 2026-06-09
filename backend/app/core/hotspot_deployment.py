"""Deploy special units to hotspots and notify unit commanders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.core.email import (
    is_email_configured,
    send_unit_commander_hotspot_deployment_email,
)
from app.models.deployment_decision import DeploymentDecision
from app.models.hotspot import Hotspot
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.models.special_assignment_unit import SpecialAssignmentUnit
from app.models.station_coverage import StationCoverageCell

_log = logging.getLogger(__name__)


def _station_ids_for_reports(db: Session, reports: list) -> set[int]:
    """Stations whose coverage cells include villages from cluster reports."""
    village_ids = {
        int(r.village_location_id)
        for r in reports
        if getattr(r, "village_location_id", None) is not None
    }
    if not village_ids:
        return set()
    cell_rows = (
        db.query(Location.parent_location_id)
        .filter(
            Location.location_id.in_(list(village_ids)),
            Location.location_type == "village",
        )
        .all()
    )
    cell_ids = {int(row[0]) for row in cell_rows if row and row[0] is not None}
    if not cell_ids:
        return set()
    station_rows = (
        db.query(StationCoverageCell.station_id)
        .filter(StationCoverageCell.cell_location_id.in_(list(cell_ids)))
        .distinct()
        .all()
    )
    return {int(row[0]) for row in station_rows if row and row[0] is not None}


def _notify_deployment_stakeholders(
    db: Session,
    *,
    hotspot: Hotspot,
    unit: SpecialAssignmentUnit,
    decided_by: PoliceUser,
    area_label: str,
    reports: list,
    email_meta: dict,
) -> dict:
    """
    In-app notifications (+ optional email) for unit commander and station commanders.
    Returns counts for API response.
    """
    from app.api.v1.notifications import create_notification, create_role_notifications

    commander = getattr(unit, "commander", None)
    hotspot_id = int(hotspot.hotspot_id)
    incident_count = len(reports)
    deployer = _commander_label(decided_by)
    title = f"Unit deployed — {unit.unit_name}"
    message = (
        f"{deployer} deployed {unit.unit_name} ({unit.unit_code}) to hotspot "
        f"#{hotspot_id} in {area_label}. {incident_count} incident(s) in cluster."
    )
    in_app_commander = 0
    in_app_stations = 0

    if commander and commander.police_user_id:
        try:
            create_notification(
                db,
                int(commander.police_user_id),
                title=title,
                message=message,
                notif_type="deployment",
                related_entity_type="hotspot",
                related_entity_id=str(hotspot_id),
                send_email=bool(email_meta.get("email_sent")),
            )
            in_app_commander = 1
        except Exception as exc:
            db.rollback()
            _log.warning("Commander in-app notification failed: %s", exc)

    station_ids = _station_ids_for_reports(db, reports)
    if getattr(hotspot, "controlled_by_user_id", None):
        ctrl = (
            db.query(PoliceUser)
            .filter(PoliceUser.police_user_id == hotspot.controlled_by_user_id)
            .first()
        )
        if ctrl and ctrl.station_id:
            station_ids.add(int(ctrl.station_id))

    for station_id in sorted(station_ids):
        try:
            notes = create_role_notifications(
                db,
                title=title,
                message=message,
                notif_type="deployment",
                related_entity_type="hotspot",
                related_entity_id=str(hotspot_id),
                target_roles=["supervisor", "officer"],
                target_station_id=int(station_id),
                exclude_user_id=decided_by.police_user_id,
                send_email=True,
            )
            in_app_stations += len(notes)
        except Exception as exc:
            db.rollback()
            _log.warning(
                "Station deployment notification failed station_id=%s: %s",
                station_id,
                exc,
            )

    try:
        create_role_notifications(
            db,
            title=title,
            message=message,
            notif_type="deployment",
            related_entity_type="hotspot",
            related_entity_id=str(hotspot_id),
            target_roles=["admin"],
            exclude_user_id=decided_by.police_user_id,
            send_email=False,
        )
    except Exception as exc:
        db.rollback()
        _log.warning("Admin deployment notification failed: %s", exc)

    return {
        "in_app_commander": in_app_commander,
        "in_app_station_users": in_app_stations,
        "stations_notified": sorted(station_ids),
    }


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
    area_label: str | None = None,
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
    decision_errors: list[str] = []
    for report in reports:
        if report.leader_verification_status != "confirmed":
            continue
        report_id_str = str(report.report_id)
        try:
            with db.begin_nested():
                existing = (
                    db.query(DeploymentDecision)
                    .filter(DeploymentDecision.report_id == report_id_str)
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
                            report_id=report_id_str,
                            decided_by=decided_by.police_user_id,
                            deployment_status="deployed",
                            assigned_unit=code,
                            deployment_priority=report.priority or "medium",
                            decision_note=note,
                            deployed_at=now,
                        )
                    )
                    decisions_created += 1
        except Exception as exc:
            decision_errors.append(f"report {report_id_str}: {exc}")
            _log.warning(
                "Deployment decision skipped for report %s: %s",
                report_id_str,
                exc,
            )

    email_sent = False
    email_error = None
    commander = getattr(unit, "commander", None)
    area = (area_label or "").strip()
    if not area:
        if reports and getattr(reports[0], "village_location", None):
            area = reports[0].village_location.location_name or "cluster area"
        else:
            area = "cluster area"
    if commander and commander.email and is_email_configured():
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
    elif not is_email_configured():
        email_error = "Email not configured on server"

    db.add(hotspot)
    try:
        db.commit()
        db.refresh(hotspot)
    except Exception as exc:
        db.rollback()
        _log.exception("Hotspot deploy commit failed hotspot_id=%s", hotspot.hotspot_id)
        raise ValueError(f"Could not save deployment: {exc}") from exc

    notify_meta = _notify_deployment_stakeholders(
        db,
        hotspot=hotspot,
        unit=unit,
        decided_by=decided_by,
        area_label=area or "cluster area",
        reports=reports,
        email_meta={
            "email_sent": email_sent,
            "email_error": email_error,
        },
    )

    return (
        hotspot,
        unit,
        {
            "decisions_created": decisions_created,
            "decision_errors": decision_errors,
            "email_sent": email_sent,
            "email_error": email_error,
            "commander_email": getattr(commander, "email", None) if commander else None,
            **notify_meta,
        },
    )


def take_hotspot_control(db: Session, hotspot: Hotspot, user: PoliceUser) -> Hotspot:
    hotspot.controlled_by_user_id = user.police_user_id
    db.add(hotspot)
    db.commit()
    db.refresh(hotspot)
    return hotspot
