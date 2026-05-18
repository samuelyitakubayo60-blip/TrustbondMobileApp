"""
Mobile push notifications (Firebase FCM) — NOT the police web dashboard.

Channels:
- Citizen reporters: devices.mobile_token (report status updates)
- Local leaders: local_leaders.fcm_device_token (new reports in coverage area)

Police users use app.models.notification + /api/v1/notifications/ (web only).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.core.fcm import fcm_is_configured, send_fcm_notification
from app.database import SessionLocal
from app.models.device import Device
from app.models.report import Report

logger = logging.getLogger(__name__)


def _device_fcm_token(db: Session, device_id) -> str | None:
    if device_id is None:
        return None
    row = db.query(Device.mobile_token).filter(Device.device_id == device_id).first()
    if not row or not row[0]:
        return None
    tok = str(row[0]).strip()
    return tok if len(tok) >= 10 else None


def notify_citizen_leader_decision_task(report_id: str, decision: str) -> None:
    """FCM to the citizen who submitted the report (mobile app), not police dashboard."""
    if not getattr(settings, "notify_citizen_report_status_fcm", True):
        return
    if not fcm_is_configured():
        return

    db = SessionLocal()
    try:
        report = (
            db.query(Report)
            .options(joinedload(Report.incident_type))
            .filter(Report.report_id == report_id)
            .first()
        )
        if not report or report.submitted_by_local_leader_id is not None:
            return

        token = _device_fcm_token(db, report.device_id)
        if not token:
            return

        ref = str(report.report_number) if getattr(report, "report_number", None) else str(report.report_id)[:8]
        incident = (
            getattr(report.incident_type, "type_name", None) if report.incident_type else None
        ) or "Your report"
        decision_norm = (decision or "").strip().lower()
        if decision_norm == "confirmed":
            title = "Community leader confirmed"
            body = f"{incident} ({ref}) was confirmed by your local leader."
        elif decision_norm == "rejected":
            title = "Community leader declined"
            body = f"{incident} ({ref}) was not confirmed by your local leader."
        else:
            return

        send_fcm_notification(
            token,
            title,
            body,
            {
                "type": "report_status_update",
                "report_id": str(report.report_id),
                "leader_decision": decision_norm,
            },
        )
    except Exception as exc:
        logger.warning("Citizen FCM leader decision notify failed: %s", exc)
    finally:
        db.close()
