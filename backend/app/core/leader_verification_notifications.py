"""
Police web dashboard notifications only (notifications table + WebSocket).

Do NOT use FCM here — mobile users (citizens, local leaders) are notified via
app.core.mobile_push_notifications and app.core.leader_notifications.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models.location import Location
from app.models.local_leader import LocalLeader
from app.models.notification import Notification
from app.models.police_user import PoliceUser
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.station_coverage import StationCoverageCell

logger = logging.getLogger(__name__)


def _station_ids_for_village(db: Session, village_id: int | None) -> list[int]:
    if village_id is None:
        return []
    cell_id = (
        db.query(Location.parent_location_id)
        .filter(Location.location_id == int(village_id), Location.location_type == "village")
        .scalar()
    )
    if not cell_id:
        return []
    rows = (
        db.query(StationCoverageCell.station_id)
        .filter(StationCoverageCell.cell_location_id == int(cell_id))
        .all()
    )
    return sorted({int(r[0]) for r in rows if r and r[0] is not None})


def _notify_police_users(
    db: Session,
    users: list[PoliceUser],
    *,
    title: str,
    message: str,
    report_id: str,
) -> None:
    if not users:
        return
    from app.api.v1.notifications import notification_manager
    from app.api.v1.notifications import _run_async_now_or_schedule

    for user in users:
        db.add(
            Notification(
                notification_id=uuid4(),
                police_user_id=user.police_user_id,
                title=title,
                message=message,
                type="report",
                related_entity_type="report",
                related_entity_id=report_id,
            )
        )
    db.commit()
    for user in users:
        _run_async_now_or_schedule(
            notification_manager.increment_notification_count(str(user.police_user_id))
        )


def notify_police_leader_submitted_report_task(report_id: str, leader_id: int) -> None:
    """Background task: alert station police when a local leader files an incident."""
    db = SessionLocal()
    try:
        report = (
            db.query(Report)
            .options(joinedload(Report.village_location))
            .filter(Report.report_id == report_id)
            .first()
        )
        if not report or getattr(report, "submitted_by_local_leader_id", None) is None:
            return

        leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == leader_id).first()
        leader_name = (leader.full_name if leader else None) or "Local leader"
        ref = str(report.report_number) if getattr(report, "report_number", None) else str(report.report_id)[:8]
        village_name = None
        if report.village_location:
            village_name = report.village_location.location_name
        loc_bit = f" ({village_name})" if village_name else ""
        title = "Leader-submitted incident"
        message = (
            f"{leader_name} filed report {ref}{loc_bit} via the local leader app. "
            f"Mobile verification only — review in Reports."
        )

        station_ids = _station_ids_for_village(db, report.village_location_id)
        q = db.query(PoliceUser).filter(PoliceUser.is_active.is_(True))
        if station_ids:
            q = q.filter(
                PoliceUser.station_id.in_(station_ids),
                PoliceUser.role.in_(["admin", "supervisor", "officer"]),
            )
        else:
            q = q.filter(PoliceUser.role.in_(["admin", "supervisor"]))

        station_users = q.all()
        if station_users:
            _notify_police_users(
                db,
                station_users,
                title=title,
                message=message,
                report_id=str(report.report_id),
            )
    except Exception as exc:
        logger.warning("Police leader submission notify failed: %s", exc)
    finally:
        db.close()


def notify_police_leader_verification_task(
    report_id: str,
    decision: str,
    leader_id: int,
) -> None:
    """Background task: in-app notification for station police when leader verifies."""
    db = SessionLocal()
    try:
        report = (
            db.query(Report)
            .options(joinedload(Report.village_location))
            .filter(Report.report_id == report_id)
            .first()
        )
        if not report:
            return

        leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == leader_id).first()
        leader_name = (leader.full_name if leader else None) or "Local leader"
        decision_norm = (decision or "").strip().lower()
        if decision_norm not in {"confirmed", "rejected"}:
            return

        ref = str(report.report_number) if getattr(report, "report_number", None) else str(report.report_id)[:8]
        village_name = None
        if report.village_location:
            village_name = report.village_location.location_name

        decision_label = "confirmed" if decision_norm == "confirmed" else "rejected"
        title = f"Leader {decision_label} report"
        loc_bit = f" ({village_name})" if village_name else ""
        message = (
            f"{leader_name} {decision_label} community report {ref}{loc_bit}. "
            f"Open the report to review police workflow."
        )

        station_ids = _station_ids_for_village(db, report.village_location_id)
        q = db.query(PoliceUser).filter(PoliceUser.is_active.is_(True))
        if station_ids:
            q = q.filter(
                PoliceUser.station_id.in_(station_ids),
                PoliceUser.role.in_(["admin", "supervisor", "officer"]),
            )
        else:
            q = q.filter(PoliceUser.role.in_(["admin", "supervisor"]))

        notified_ids: set[int] = set()
        station_users = q.all()
        if station_users:
            _notify_police_users(
                db,
                station_users,
                title=title,
                message=message,
                report_id=str(report.report_id),
            )
            notified_ids = {u.police_user_id for u in station_users}

        assignment_rows = (
            db.query(ReportAssignment.police_user_id)
            .filter(ReportAssignment.report_id == report.report_id)
            .all()
        )
        extra_ids = [
            int(r[0])
            for r in assignment_rows
            if r and r[0] is not None and int(r[0]) not in notified_ids
        ]
        if extra_ids:
            assignees = (
                db.query(PoliceUser)
                .filter(PoliceUser.police_user_id.in_(extra_ids), PoliceUser.is_active.is_(True))
                .all()
            )
            if assignees:
                _notify_police_users(
                    db,
                    assignees,
                    title=f"Assigned report {decision_label}",
                    message=f"Report {ref} you are assigned to was {decision_label} by {leader_name}.",
                    report_id=str(report.report_id),
                )
    except Exception as exc:
        logger.warning("Police leader verification notify failed: %s", exc)
    finally:
        db.close()
