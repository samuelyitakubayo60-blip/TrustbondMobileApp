"""Police web dashboard alerts (notifications table). Not mobile FCM."""

from __future__ import annotations

import logging

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models.report import Report
from app.core.leader_coverage import active_leader_ids_covering_village

logger = logging.getLogger(__name__)


def notify_admins_leader_coverage_gap_task(report_id: str) -> None:
    """Warn police admins/supervisors that a citizen report has no covering local leader."""
    db = SessionLocal()
    try:
        report = (
            db.query(Report)
            .options(joinedload(Report.village_location))
            .filter(Report.report_id == report_id)
            .first()
        )
        if not report or report.submitted_by_local_leader_id is not None:
            return
        village_id = report.village_location_id
        if village_id is None:
            return
        if active_leader_ids_covering_village(db, int(village_id)):
            return

        vname = report.village_location.location_name if report.village_location else None
        ref = str(report.report_number) if getattr(report, "report_number", None) else str(report.report_id)[:8]
        loc = f" in {vname}" if vname else ""
        from app.api.v1.notifications import create_role_notifications

        create_role_notifications(
            db,
            title="No local leader for report area",
            message=(
                f"Report {ref}{loc} was submitted but no active village chief or cell executive "
                f"is registered for that area. Assign a local leader in Admin → Local Leaders."
            ),
            notif_type="system",
            related_entity_type="report",
            related_entity_id=str(report.report_id),
            target_roles=["admin", "supervisor"],
        )
    except Exception as exc:
        logger.warning("Leader coverage gap admin notify failed: %s", exc)
    finally:
        db.close()
