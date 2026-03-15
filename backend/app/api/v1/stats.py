from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.device import Device
from app.models.audit_log import AuditLog
from app.api.v1.auth import get_current_user
from app.models.police_user import PoliceUser
from app.models.hotspot import Hotspot

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard")
def get_dashboard_stats(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return counts and widgets for dashboard. Officers see only assigned reports."""
    is_officer = getattr(current_user, "role", None) == "officer"
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)

    if is_officer:
        assigned_ids = db.query(ReportAssignment.report_id).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
        report_filter = Report.report_id.in_(assigned_ids)
    else:
        report_filter = True

    total = db.query(Report).filter(report_filter).count()
    by_status_rows = db.query(Report.rule_status, func.count(Report.report_id)).filter(
        report_filter
    ).group_by(Report.rule_status).all()
    by_status = {r[0]: r[1] for r in by_status_rows}

    pending = by_status.get("pending", 0)
    verified = by_status.get("passed", 0)
    flagged = by_status.get("flagged", 0) + by_status.get("rejected", 0)
    recent_7d_count = db.query(func.count(Report.report_id)).filter(
        report_filter, Report.reported_at >= since_7d
    ).scalar() or 0

    open_cases = 0
    try:
        from app.models.case import Case
        open_cases = db.query(func.count(Case.case_id)).filter(
            Case.status.in_(["open", "investigating"])
        ).scalar() or 0
    except Exception:
        pass

    # Active devices in last 30 days, prefer last_seen_at when available
    if hasattr(Device, "last_seen_at"):
        active_q = db.query(func.count(Device.device_id)).filter(
            Device.last_seen_at >= since_30d
        )
        if hasattr(Device, "is_banned"):
            active_q = active_q.filter(Device.is_banned == False)
        active_devices = active_q.scalar() or 0
    else:
        active_devices = db.query(func.count(Device.device_id)).filter(
            Device.first_seen_at >= since_30d
        ).scalar() or 0
        if hasattr(Device, "is_banned"):
            active_devices = db.query(func.count(Device.device_id)).filter(
                Device.first_seen_at >= since_30d,
                Device.is_banned == False,
            ).scalar() or 0

    recent_reports_q = db.query(Report).options(
        joinedload(Report.device),
        joinedload(Report.incident_type),
        joinedload(Report.village_location),
    ).filter(report_filter).order_by(Report.reported_at.desc()).limit(5)
    recent_reports = recent_reports_q.all()

    def _report_row(r):
        ts = float(r.device.device_trust_score) if r.device and r.device.device_trust_score else None
        return {
            "report_id": str(r.report_id),
            "report_number": getattr(r, "report_number", None),
            "incident_type_name": r.incident_type.type_name if r.incident_type else None,
            "village_name": r.village_location.location_name if r.village_location else None,
            "trust_score": ts,
            "rule_status": r.rule_status,
            "reported_at": r.reported_at.isoformat() if r.reported_at else None,
        }
    recent_reports_data = [_report_row(r) for r in recent_reports]

    top_hotspots = db.query(Hotspot).options(
        joinedload(Hotspot.incident_type)
    ).order_by(Hotspot.incident_count.desc()).limit(5).all()

    hotspot_list = []
    for h in top_hotspots:
        try:
            from app.core.village_lookup import get_village_location_info
            info = get_village_location_info(db, float(h.center_lat), float(h.center_long))
            area = (info.get("sector_name") or info.get("cell_name") or info.get("village_name") or "Area") if info else "Area"
        except Exception:
            area = "Area"
        hotspot_list.append({
            "hotspot_id": h.hotspot_id,
            "area_name": area,
            "incident_count": h.incident_count,
            "incident_type_name": h.incident_type.type_name if h.incident_type else None,
            "risk_level": h.risk_level,
        })

    recent_activity = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(5).all()
    activity_list = [
        {
            "action_type": a.action_type,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "action_details": a.action_details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent_activity
    ]

    # Weekly volume over the last 4 weeks (oldest W1 to newest W4)
    weekly_volume = []
    now = datetime.now(timezone.utc)
    for i in range(4, 0, -1):
        start = now - timedelta(days=7 * i)
        end = now - timedelta(days=7 * (i - 1))
        count = (
            db.query(func.count(Report.report_id))
            .filter(report_filter, Report.reported_at >= start, Report.reported_at < end)
            .scalar()
            or 0
        )
        weekly_volume.append(
            {
                "label": f"W{5 - i}",  # W1, W2, W3, W4
                "count": int(count),
            }
        )

    # Average trust score from recent reports (device/ML trust)
    trust_values = [
        float(r["trust_score"])
        for r in recent_reports_data
        if r.get("trust_score") is not None
    ]
    avg_trust_score = sum(trust_values) / len(trust_values) if trust_values else None

    return {
        "total_reports": total,
        "reports_last_7_days": recent_7d_count,
        "pending": pending,
        "verified": verified,
        "flagged": flagged,
        "open_cases": open_cases,
        "active_devices": active_devices,
        "by_status": by_status,
        "scope": "assigned_to_me" if is_officer else "all",
        "recent_reports": recent_reports_data,
        "top_hotspots": hotspot_list,
        "recent_activity": activity_list,
        "weekly_volume": weekly_volume,
        "avg_trust_score": avg_trust_score,
    }
