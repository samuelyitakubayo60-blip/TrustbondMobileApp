from datetime import datetime, timezone, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, or_

from app.database import get_db
from app.core.report_review import needs_police_review_clause, resolve_display_trust_score
from app.core.village_lookup import get_village_location_info
from app.models.report import Report
from app.models.report_assignment import ReportAssignment
from app.models.device import Device
from app.models.audit_log import AuditLog
from app.models.station import Station
from app.models.location import Location
from app.models.police_user import PoliceUser
from app.api.v1.auth import get_current_user
from app.models.hotspot import Hotspot
from app.models.ml_prediction import MLPrediction
from app.models.case import Case

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/dashboard")
def get_dashboard_stats(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return counts and widgets for dashboard. Officers see only assigned reports."""
    current_role = getattr(current_user, "role", None)
    is_officer = current_role == "officer"
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)

    # 1) Build report_filter based on role
    if current_role == "officer":
        assigned_ids = db.query(ReportAssignment.report_id).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
        report_filter = Report.report_id.in_(assigned_ids)
    elif current_role == "supervisor":
        station_id = getattr(current_user, "station_id", None)
        
        if station_id is not None:
            # Get station to find its sector location
            station = db.query(Station).filter(Station.station_id == station_id).first()
            if station and station.location_id:
                # Get sector location (station should be at sector level)
                sector_location_id = station.location_id
                
                # Find all villages/cells in this sector
                sector_locations_query = db.query(Location.location_id).filter(
                    or_(
                        Location.location_id == sector_location_id,  # The sector itself
                        Location.parent_location_id == sector_location_id,  # Direct children (cells)
                        # Also get villages under cells in this sector
                        Location.location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id.in_(
                                    db.query(Location.location_id).filter(
                                        Location.parent_location_id == sector_location_id
                                    )
                                )
                            )
                        )
                    )
                )
                sector_location_ids = [loc[0] for loc in sector_locations_query.all()]
                
                # Filter reports by location hierarchy (village_location_id in sector)
                assigned_qs = (
                    db.query(Report.report_id)
                    .filter(
                        or_(
                            Report.handling_station_id == station_id,
                            Report.assignments.any(
                                ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
                            ),
                            Report.village_location_id.in_(sector_location_ids)
                        )
                    )
                ).distinct()
            else:
                # Fallback: only station-based filtering
                assigned_qs = (
                    db.query(Report.report_id)
                    .filter(
                        or_(
                            Report.handling_station_id == station_id,
                            Report.assignments.any(
                                ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
                            )
                        )
                    )
                ).distinct()
            report_filter = Report.report_id.in_(assigned_qs)
        else:
            report_filter = False
    else:
        # Admin
        report_filter = True

    total = db.query(Report).filter(report_filter).count()
    
    # Use DB status/verification_status for counters (rule_status may be null on older rows).
    by_status_rows = (
        db.query(Report.status, func.count(Report.report_id))
        .filter(report_filter)
        .group_by(Report.status)
        .all()
    )
    by_status = {str(r[0]) if r[0] is not None else None: int(r[1]) for r in by_status_rows}

    pending_review = (
        db.query(func.count(Report.report_id))
        .filter(report_filter, needs_police_review_clause())
        .scalar()
        or 0
    )
    pending = int(pending_review)
    verified = int(by_status.get("verified", 0))
    flagged = int(by_status.get("flagged", 0) + by_status.get("rejected", 0))
    recent_7d_count = db.query(func.count(Report.report_id)).filter(
        report_filter, Report.reported_at >= since_7d
    ).scalar() or 0

    open_cases = 0
    try:
        from app.models.case import Case
        case_q = db.query(func.count(Case.case_id)).filter(
            Case.status.in_(["open", "investigating"])
        )
        if current_role == "officer":
            case_q = case_q.filter(Case.assigned_to_id == current_user.police_user_id)
        elif current_role == "supervisor":
            station_id = getattr(current_user, "station_id", None)
            if station_id is not None:
                case_q = case_q.filter(Case.assigned_to.has(PoliceUser.station_id == station_id))
            else:
                case_q = case_q.filter(False)
        open_cases = case_q.scalar() or 0
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
        selectinload(Report.ml_predictions),
    ).filter(report_filter).order_by(Report.reported_at.desc()).limit(5)
    recent_reports = recent_reports_q.all()

    def _village_name_for_dashboard(r: Report):
        """Match reports list: FK village first, else reverse-geocode from coordinates."""
        if getattr(r, "village_location", None) and r.village_location:
            return r.village_location.location_name
        if r.latitude is not None and r.longitude is not None:
            try:
                info = get_village_location_info(db, float(r.latitude), float(r.longitude))
                if info:
                    return info.get("village_name")
            except Exception:
                return None
        return None

    def _report_row(r):
        ts = resolve_display_trust_score(r)
        return {
            "report_id": str(r.report_id),
            "report_number": getattr(r, "report_number", None),
            "incident_type_name": r.incident_type.type_name if r.incident_type else None,
            "village_name": _village_name_for_dashboard(r),
            "trust_score": ts,
            "status": getattr(r, "status", None),
            "verification_status": getattr(r, "verification_status", None),
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

    current_role = getattr(current_user, "role", None)
    visible_report_ids: set[str] = set()
    visible_case_ids: set[str] = set()
    if current_role == "officer":
        rep_rows = (
            db.query(ReportAssignment.report_id)
            .filter(ReportAssignment.police_user_id == current_user.police_user_id)
            .distinct()
            .all()
        )
        visible_report_ids = {str(rid) for (rid,) in rep_rows}
        case_rows = (
            db.query(Case.case_id)
            .filter(Case.assigned_to_id == current_user.police_user_id)
            .all()
        )
        visible_case_ids = {str(cid) for (cid,) in case_rows}
    elif current_role == "supervisor":
        station_id = getattr(current_user, "station_id", None)
        if station_id is not None:
            rep_rows = (
                db.query(Report.report_id)
                .filter(
                    (Report.handling_station_id == station_id)
                    | (Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == station_id)
                    ))
                )
                .all()
            )
            visible_report_ids = {str(rid) for (rid,) in rep_rows}
            case_rows = (
                db.query(Case.case_id)
                .filter(Case.assigned_to.has(PoliceUser.station_id == station_id))
                .all()
            )
            visible_case_ids = {str(cid) for (cid,) in case_rows}

    # Pull a slightly larger recent window then trim after role-scope filtering.
    recent_activity_raw = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(120)
        .all()
    )

    def _is_visible_activity(a: AuditLog) -> bool:
        if current_role == "admin":
            return True
        if a.actor_id == current_user.police_user_id:
            return True
        et = (a.entity_type or "").lower()
        eid = str(a.entity_id) if a.entity_id else ""
        if et == "report":
            return eid in visible_report_ids
        if et == "case":
            return eid in visible_case_ids
        # Non report/case entries are kept only if performed by current user.
        return False

    recent_activity = [a for a in recent_activity_raw if _is_visible_activity(a)][:5]

    report_ref: dict[str, str] = {}
    if recent_activity:
        report_ids_in_feed_raw = [
            a.entity_id for a in recent_activity
            if (a.entity_type or "").lower() == "report" and a.entity_id
        ]
        report_ids_in_feed = []
        for rid in report_ids_in_feed_raw:
            try:
                report_ids_in_feed.append(UUID(str(rid)))
            except Exception:
                continue
        if report_ids_in_feed:
            reps = db.query(Report.report_id, Report.report_number).filter(
                Report.report_id.in_(report_ids_in_feed)
            ).all()
            report_ref = {
                str(rid): (rnum or f"report {str(rid)[:8]}")
                for rid, rnum in reps
            }

    case_ref: dict[str, str] = {}
    if recent_activity:
        case_ids_in_feed_raw = [
            a.entity_id for a in recent_activity
            if (a.entity_type or "").lower() == "case" and a.entity_id
        ]
        case_ids_in_feed = []
        for cid in case_ids_in_feed_raw:
            try:
                case_ids_in_feed.append(UUID(str(cid)))
            except Exception:
                continue
        if case_ids_in_feed:
            cs = db.query(Case.case_id, Case.case_number).filter(
                Case.case_id.in_(case_ids_in_feed)
            ).all()
            case_ref = {
                str(cid): (cnum or f"case {str(cid)[:8]}")
                for cid, cnum in cs
            }

    def _activity_row(a: AuditLog):
        """Normalize recent activity into human‑readable text + severity."""
        base = a.action_type or "activity"
        # Very lightweight mapping – can be expanded as we add more actions.
        action_lower = (a.action_type or "").lower()
        if "verify" in action_lower:
            severity = "success"
        elif "flag" in action_lower or "blacklist" in action_lower:
            severity = "danger"
        elif "hotspot" in action_lower or "cluster" in action_lower:
            severity = "critical"
        elif "create" in action_lower or "add" in action_lower:
            severity = "info"
        else:
            severity = "neutral"

        parts = [base.replace("_", " ").capitalize()]
        entity_type = (a.entity_type or "").lower()
        if entity_type == "report" and a.entity_id:
            parts.append(f"for report {report_ref.get(str(a.entity_id), str(a.entity_id)[:8])}")
        elif entity_type == "case" and a.entity_id:
            parts.append(f"for case {case_ref.get(str(a.entity_id), str(a.entity_id)[:8])}")
        elif a.entity_type:
            parts.append(f"for {a.entity_type}")
        text = " ".join(parts)

        return {
            "action_type": a.action_type,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "text": text,
            "severity": severity,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    activity_list = [_activity_row(a) for a in recent_activity]

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

    # System / ML status – keep it database‑driven so the UI reflects reality,
    # without hard‑coding specific algorithms like Random Forest.
    now = datetime.now(timezone.utc)

    latest_pred = (
        db.query(MLPrediction)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if latest_pred and latest_pred.evaluated_at:
        eval_ts = latest_pred.evaluated_at
        # Normalise to timezone-aware UTC so subtraction is safe even if the column is naive.
        if eval_ts.tzinfo is None:
            eval_ts = eval_ts.replace(tzinfo=timezone.utc)
        age = now - eval_ts
        if age <= timedelta(hours=24):
            ml_status = "Online"
            ml_level = "ok"
        elif age <= timedelta(days=3):
            ml_status = "Stale"
            ml_level = "warn"
        else:
            ml_status = "Offline"
            ml_level = "error"
    else:
        ml_status = "Offline"
        ml_level = "error"

    last_hotspot_detected = (
        db.query(func.max(Hotspot.detected_at)).scalar()
        if hasattr(Hotspot, "detected_at")
        else None
    )
    if last_hotspot_detected:
        # Normalise to timezone-aware UTC so subtraction is safe even if the column is naive.
        if last_hotspot_detected.tzinfo is None:
            last_hotspot_detected = last_hotspot_detected.replace(tzinfo=timezone.utc)
        age_hs = now - last_hotspot_detected
        if age_hs <= timedelta(hours=24):
            hs_status = "Running"
            hs_level = "ok"
        elif age_hs <= timedelta(days=3):
            hs_status = "Idle"
            hs_level = "warn"
        else:
            hs_status = "Stale"
            hs_level = "warn"
    else:
        hs_status = "No data"
        hs_level = "neutral"

    system_status = [
        {
            "name": "ML Engine",
            "status": ml_status,
            "level": ml_level,
            "model_type": latest_pred.model_type if latest_pred else None,
            "model_version": latest_pred.model_version if latest_pred else None,
            "last_updated": latest_pred.evaluated_at.isoformat()
            if latest_pred and latest_pred.evaluated_at
            else None,
        },
        {
            "name": "Hotspot Detection (DBSCAN)",
            "status": hs_status,
            "level": hs_level,
            "last_detected": last_hotspot_detected.isoformat()
            if last_hotspot_detected
            else None,
        },
    ]

    return {
        "total_reports": total,
        "reports_last_7_days": recent_7d_count,
        "pending": pending,
        "pending_review": pending_review,
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
        "system_status": system_status,
    }
