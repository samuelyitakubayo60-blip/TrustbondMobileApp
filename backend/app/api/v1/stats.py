from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.api.v1.auth import get_current_user
from app.models.police_user import PoliceUser

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard")
def get_dashboard_stats(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return counts for dashboard. Officers see only reports assigned to them; supervisors/admins see all."""
    is_officer = getattr(current_user, "role", None) == "officer"
    since = datetime.now(timezone.utc) - timedelta(days=7)

    if is_officer:
        assigned_report_ids = (
            db.query(ReportAssignment.report_id)
            .filter(ReportAssignment.police_user_id == current_user.police_user_id)
            .distinct()
        )
        total = db.query(Report).filter(Report.report_id.in_(assigned_report_ids)).count()
        by_status = (
            db.query(Report.rule_status, func.count(Report.report_id))
            .filter(Report.report_id.in_(assigned_report_ids))
            .group_by(Report.rule_status)
            .all()
        )
        status_counts = {row[0]: row[1] for row in by_status}
        recent = (
            db.query(Report)
            .filter(Report.report_id.in_(assigned_report_ids), Report.reported_at >= since)
            .count()
        )
    else:
        total = db.query(func.count(Report.report_id)).scalar() or 0
        by_status = (
            db.query(Report.rule_status, func.count(Report.report_id))
            .group_by(Report.rule_status)
            .all()
        )
        status_counts = {row[0]: row[1] for row in by_status}
        recent = (
            db.query(func.count(Report.report_id))
            .filter(Report.reported_at >= since)
            .scalar()
            or 0
        )

    return {
        "total_reports": total,
        "by_status": status_counts,
        "reports_last_7_days": recent,
        "scope": "assigned_to_me" if is_officer else "all",
    }
