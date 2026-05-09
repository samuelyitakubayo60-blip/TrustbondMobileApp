"""Notify local leaders when a new public report appears in their village (email + FCM)."""

from __future__ import annotations

from app.config import settings
from app.core.email import is_smtp_configured, send_leader_new_incident_email
from app.core.fcm import fcm_is_configured, send_leader_new_report_notification
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models.local_leader import LocalLeader
from app.models.report import Report
from app.core.leader_workflow import local_leader_ids_covering_village


def notify_local_leaders_new_report_task(report_id: str) -> None:
    email_on = getattr(settings, "notify_local_leaders_new_report_email", True)
    fcm_on = getattr(settings, "notify_local_leaders_new_report_fcm", True)
    if not email_on and not fcm_on:
        return

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

        leader_ids = local_leader_ids_covering_village(db, int(village_id))
        if not leader_ids:
            return

        vname = None
        if report.village_location:
            vname = report.village_location.location_name

        rnum = getattr(report, "report_number", None)
        ref = str(rnum) if rnum else str(report.report_id)[:8]
        rid = str(report.report_id)

        for lid in leader_ids:
            leader = db.query(LocalLeader).filter(LocalLeader.local_leader_id == lid).first()
            if not leader or not leader.is_active:
                continue
            if email_on and is_smtp_configured() and leader.email:
                send_leader_new_incident_email(
                    leader.email,
                    leader.full_name or "Local leader",
                    ref,
                    vname,
                )
            if fcm_on and fcm_is_configured():
                fcm_tok = getattr(leader, "fcm_device_token", None) or ""
                fcm_tok = fcm_tok.strip()
                if fcm_tok:
                    send_leader_new_report_notification(fcm_tok, ref, vname, rid)
    finally:
        db.close()
