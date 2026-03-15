from typing import Annotated, Optional, List, Tuple, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query, status
from sqlalchemy.orm import Session, joinedload, selectinload
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
import io
import os

import cloudinary
import cloudinary.uploader
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.report import Report
from app.models.evidence_file import EvidenceFile
from app.models.hotspot import Hotspot
from app.models.device import Device
from app.models.incident_type import IncidentType
from app.schemas.report import (
    ReportCreate,
    ReportResponse,
    ReportDetailResponse,
    ReportListResponse,
    EvidenceFileResponse,
    EvidencePreview,
    AssignmentResponse,
    AssignCreate,
    ReviewResponse,
    ReviewCreate,
)
from app.models.police_user import PoliceUser
from app.models.report_assignment import ReportAssignment
from app.models.police_review import PoliceReview
from app.api.v1.auth import get_optional_user, get_current_user, get_current_admin_or_supervisor
from app.api.v1.notifications import create_notification
from app.core.report_rules import apply_rule_based_status, is_likely_screenshot_or_screen_recording
from app.core.credibility_model import score_report_credibility
from app.core.audit import log_action
from app.core.hotspot_auto import create_hotspots_from_reports
from app.core.village_lookup import get_village_location_id, get_village_location_info
from sqlalchemy import text

router = APIRouter(prefix="/reports", tags=["reports"])


def _generate_report_number(db: Session) -> str:
    """Generate next report number RPT-YYYY-NNNN."""
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"RPT-{year}-"
    row = db.execute(
        text("""
            SELECT COALESCE(MAX(
                NULLIF(SUBSTRING(report_number FROM 'RPT-[0-9]{4}-([0-9]+)'), '')::INT
            ), 0) + 1 AS next_num
            FROM reports WHERE report_number LIKE :prefix
        """),
        {"prefix": f"{prefix}%"},
    ).fetchone()
    next_num = row[0] if row else 1
    return f"{prefix}{next_num:04d}"

UPLOAD_DIR = "uploads/evidence"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# Configure Cloudinary using settings (Pydantic loads .env for us)
cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)

_CLOUDINARY_ENABLED = bool(settings.cloudinary_cloud_name)


def _extract_exif_metadata(image_bytes: bytes) -> tuple[Optional[float], Optional[float], Optional[datetime]]:
    """Extract GPS latitude/longitude and capture time from image EXIF, if present."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        # Try modern getexif() API first, fall back to _getexif()
        exif_data = getattr(image, "getexif", lambda: None)()
        if not exif_data:
            exif_data = getattr(image, "_getexif", lambda: None)()

        if not exif_data:
            return None, None, None

        exif = {TAGS.get(k, k): v for k, v in exif_data.items()}
        # Debug: show that we actually saw EXIF keys
        print(f"[EXIF] Found EXIF keys: {list(exif.keys())[:10]}")

        # Try to get GPS info in a robust way
        gps_info = None

        # 1) Best effort: use get_ifd if available (Pillow Exif object)
        if hasattr(exif_data, "get_ifd"):
            try:
                gps_ifd = exif_data.get_ifd(34853)  # 34853 == GPSInfo tag
                if gps_ifd:
                    gps_info = gps_ifd
            except Exception:
                gps_info = None

        # 2) Fallback: raw tag value 34853 or "GPSInfo"
        if gps_info is None:
            raw_gps = exif_data.get(34853) or exif.get("GPSInfo")
            # Some cameras store an integer offset here; resolve via get_ifd
            if isinstance(raw_gps, dict):
                gps_info = raw_gps
            elif isinstance(raw_gps, int) and hasattr(exif_data, "get_ifd"):
                try:
                    gps_info = exif_data.get_ifd(raw_gps)
                except Exception:
                    gps_info = None

        dt_original = exif.get("DateTimeOriginal") or exif.get("DateTime")

        lat = lon = None
        print(f"[EXIF] raw GPSInfo: {gps_info!r}")
        if gps_info:
            gps_parsed = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            print(f"[EXIF] GPSInfo keys: {list(gps_parsed.keys())}")

            def _to_deg(value, ref):
                """
                Convert EXIF GPS coordinates to decimal degrees.

                Handles both:
                - Rational tuples: ((deg_num, deg_den), (min_num, min_den), (sec_num, sec_den))
                - Simple float triplets: (deg_float, min_float, sec_float)
                """
                try:
                    # Case 1: rational tuples
                    if isinstance(value[0], (tuple, list)):
                        d = value[0][0] / value[0][1]
                        m = value[1][0] / value[1][1]
                        s = value[2][0] / value[2][1]
                    else:
                        # Case 2: already simple floats (deg, min, sec)
                        d, m, s = value

                    result = d + (m / 60.0) + (s / 3600.0)
                    if ref in ["S", "W"]:
                        result = -result
                    return float(result)
                except Exception:
                    return None

            lat_val = gps_parsed.get("GPSLatitude")
            lat_ref = gps_parsed.get("GPSLatitudeRef")
            lon_val = gps_parsed.get("GPSLongitude")
            lon_ref = gps_parsed.get("GPSLongitudeRef")

            if lat_val and lat_ref:
                lat = _to_deg(lat_val, lat_ref)
            if lon_val and lon_ref:
                lon = _to_deg(lon_val, lon_ref)

        dt = None
        if dt_original:
            # EXIF datetime format: "YYYY:MM:DD HH:MM:SS"
            try:
                dt = datetime.strptime(dt_original, "%Y:%m:%d %H:%M:%S")
            except Exception:
                dt = None

        return lat, lon, dt
    except Exception:
        # If EXIF parsing fails, just return Nones
        return None, None, None


@router.post("/", response_model=ReportResponse)
def create_report(
    report_data: ReportCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Submit a new incident report"""
    # Verify device exists
    device = db.query(Device).filter(Device.device_id == report_data.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Verify incident type exists and is active
    incident_type = (
        db.query(IncidentType)
        .filter(
            IncidentType.incident_type_id == report_data.incident_type_id,
            IncidentType.is_active == True,
        )
        .first()
    )
    if not incident_type:
        raise HTTPException(status_code=400, detail="Invalid or inactive incident type")

    # Reports outside Musanze district are out of scope: reject (do not store)
    try:
        lat_f = float(report_data.latitude)
        lon_f = float(report_data.longitude)
        village_id = get_village_location_id(db, lat_f, lon_f)
        if village_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reports are only accepted within Musanze district. This location is outside the service area.",
            )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid coordinates")
    
    report_num = _generate_report_number(db) if hasattr(Report, "report_number") else None
    report = Report(
        report_id=uuid4(),
        report_number=report_num,
        device_id=report_data.device_id,
        incident_type_id=report_data.incident_type_id,
        description=report_data.description,
        latitude=report_data.latitude,
        longitude=report_data.longitude,
        gps_accuracy=report_data.gps_accuracy,
        motion_level=report_data.motion_level,
        movement_speed=report_data.movement_speed,
        was_stationary=report_data.was_stationary,
        rule_status="pending",  # Will be processed by verification engine
        status="pending",
        verification_status="pending",
        context_tags=report_data.context_tags or [],
        app_version=report_data.app_version,
        network_type=report_data.network_type,
        battery_level=report_data.battery_level,
    )

    # Wire location hierarchy: use the village row as both specific village_location_id
    # and generic location_id so downstream queries can work with a single FK.
    report.village_location_id = village_id  # already looked up above (required for in-scope)
    report.location_id = village_id
    db.add(report)
    db.flush()  # Get report_id

    # Add evidence files
    for evidence_data in report_data.evidence_files:
        evidence = EvidenceFile(
            evidence_id=uuid4(),
            report_id=report.report_id,
            file_url=evidence_data.file_url,
            file_type=evidence_data.file_type,
            media_latitude=evidence_data.media_latitude,
            media_longitude=evidence_data.media_longitude,
            captured_at=evidence_data.captured_at,
            is_live_capture=evidence_data.is_live_capture,
        )
        db.add(evidence)

    # Rule-based verification (no ML; ML will be added later)
    evidence_count = len(report_data.evidence_files)
    rule_status, is_flagged, flag_reason = apply_rule_based_status(report, evidence_count, db)
    report.rule_status = rule_status
    report.is_flagged = is_flagged
    if is_flagged and flag_reason:
        report.flag_reason = flag_reason
    if rule_status == "rejected":
        report.status = "rejected"
        report.verification_status = "rejected"

    # ML-based credibility scoring (best-effort; failures are ignored)
    score_report_credibility(db, report, device, evidence_count)

    # Update device stats
    device.total_reports += 1

    log_action(db, "report_created", entity_type="report", entity_id=str(report.report_id), actor_type="system", success=True)

    db.commit()
    db.refresh(report)

    # Run hotspot auto-creation in background when criteria are met (no user intervention)
    def run_hotspot_auto():
        session = SessionLocal()
        try:
            create_hotspots_from_reports(session, time_window_hours=24, min_incidents=2, radius_meters=500)
        except Exception:
            pass  # Don't fail the request; hotspots can be created on next report
        finally:
            session.close()

    background_tasks.add_task(run_hotspot_auto)
    return report


def _build_report_response(r: Report, db: Optional[Session] = None) -> ReportResponse:
    village_name = None
    if getattr(r, "village_location", None) and r.village_location:
        village_name = r.village_location.location_name
    # Fallback: look up village from coordinates (e.g. for older reports or when village_location_id was null)
    if village_name is None and db is not None and r.latitude is not None and r.longitude is not None:
        try:
            info = get_village_location_info(db, float(r.latitude), float(r.longitude))
            if info:
                village_name = info.get("village_name")
        except Exception:
            pass

    evidence_files = list(getattr(r, "evidence_files", None) or [])
    evidence_files.sort(key=lambda x: (x.uploaded_at is None, x.uploaded_at), reverse=False)
    evidence_preview = [
        EvidencePreview(evidence_id=ef.evidence_id, file_url=ef.file_url, file_type=ef.file_type)
        for ef in evidence_files[:3]
    ]

    hotspot_id = None
    hotspot_risk_level = None
    hotspot_incident_count = None
    hotspot_label = None

    hotspots = list(getattr(r, "hotspots", None) or [])
    if hotspots:
        risk_rank = {"low": 0, "medium": 1, "high": 2}
        hotspots.sort(
            key=lambda h: (risk_rank.get((h.risk_level or "").lower(), 0), h.incident_count, h.detected_at),
            reverse=True,
        )
        h: Hotspot = hotspots[0]
        hotspot_id = h.hotspot_id
        hotspot_risk_level = h.risk_level
        hotspot_incident_count = h.incident_count
        type_name = h.incident_type.type_name if h.incident_type else (r.incident_type.type_name if r.incident_type else f"Type {r.incident_type_id}")
        area_name = village_name or "this area"
        hotspot_label = f"{type_name} hotspot in {area_name}"

    trust_score = None
    if getattr(r, "device", None) and r.device:
        trust_score = r.device.device_trust_score
    if trust_score is None and getattr(r, "ml_predictions", None):
        preds = [p for p in r.ml_predictions if p.is_final or p.trust_score is not None]
        if preds:
            preds.sort(
                key=lambda p: (p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc)),
                reverse=True,
            )
            trust_score = preds[0].trust_score

    # Aggregate assignment priority/status for list views
    assignment_priority = None
    assignment_status = None
    assignments = list(getattr(r, "assignments", None) or [])
    if assignments:
        pr_rank = {"urgent": 3, "high": 2, "medium": 1, "low": 0}
        assignments.sort(
            key=lambda a: pr_rank.get((a.priority or "").lower(), 0),
            reverse=True,
        )
        top = assignments[0]
        assignment_priority = top.priority
        assignment_status = top.status

    context_tags = getattr(r, "context_tags", None) or []
    if context_tags is None:
        context_tags = []

    return ReportResponse(
        report_id=r.report_id,
        report_number=getattr(r, "report_number", None),
        device_id=r.device_id,
        incident_type_id=r.incident_type_id,
        description=r.description,
        latitude=r.latitude,
        longitude=r.longitude,
        reported_at=r.reported_at,
        rule_status=r.rule_status,
        status=getattr(r, "status", None),
        verification_status=getattr(r, "verification_status", None),
        village_location_id=r.village_location_id,
        village_name=village_name,
        incident_type_name=r.incident_type.type_name if r.incident_type else None,
        evidence_count=len(evidence_files),
        evidence_preview=evidence_preview,
        trust_score=float(trust_score) if trust_score is not None else None,
        hotspot_id=hotspot_id,
        hotspot_risk_level=hotspot_risk_level,
        hotspot_incident_count=hotspot_incident_count,
        hotspot_label=hotspot_label,
        is_flagged=getattr(r, "is_flagged", None),
        flag_reason=getattr(r, "flag_reason", None),
        verified_at=getattr(r, "verified_at", None),
        context_tags=context_tags,
        app_version=getattr(r, "app_version", None),
        network_type=getattr(r, "network_type", None),
        battery_level=float(r.battery_level) if getattr(r, "battery_level", None) is not None else None,
        assignment_priority=assignment_priority,
        assignment_status=assignment_status,
    )


@router.get("/{report_id}/related", response_model=List[ReportResponse])
def list_related_reports(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(5, ge=1, le=20),
):
    """
    Return reports related to this one:
    - Same incident_type_id
    - Same village (when known)
    - Reported within a 3 day window around this report
    """
    base: Report | None = (
        db.query(Report)
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.device),
            joinedload(Report.ml_predictions),
            joinedload(Report.hotspots).joinedload(Hotspot.incident_type),
        )
        .filter(Report.report_id == report_id)
        .first()
    )
    if not base:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    # Time window +/- 3 days
    window = timedelta(days=3)
    from_time = (base.reported_at or datetime.now(timezone.utc)) - window
    to_time = (base.reported_at or datetime.now(timezone.utc)) + window

    q = db.query(Report).options(
        joinedload(Report.incident_type),
        joinedload(Report.village_location),
        joinedload(Report.device),
        joinedload(Report.ml_predictions),
        joinedload(Report.hotspots).joinedload(Hotspot.incident_type),
    )

    q = q.filter(
        Report.report_id != base.report_id,
        Report.incident_type_id == base.incident_type_id,
        Report.reported_at >= from_time,
        Report.reported_at <= to_time,
    )

    if base.village_location_id is not None:
        q = q.filter(Report.village_location_id == base.village_location_id)

    related = (
        q.order_by(Report.reported_at.desc())
        .limit(limit)
        .all()
    )

    return [_build_report_response(r, db) for r in related]


def _float_or_none(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compute_incident_location_with_villages(
    report: Report,
    db: Session,
) -> Tuple[Optional[float], Optional[float], str, Optional[Dict[str, Any]]]:
    """
    Decide incident location by comparing reporter village vs evidence villages.

    Preference order:
    - If reporter + all evidence are in the same village -> use that village ("same_village_all").
    - Else if reporter village exists -> use reporter village ("reporter_only" or "village_conflict").
    - Else if evidence villages exist -> use dominant evidence village ("evidence_only" or "evidence_conflict").
    - Else fall back to raw reporter/evidence coordinates.
    """
    rep_lat = _float_or_none(report.latitude)
    rep_lon = _float_or_none(report.longitude)

    report_info: Optional[Dict[str, Any]] = None
    report_village: Optional[str] = None
    if rep_lat is not None and rep_lon is not None:
        try:
            report_info = get_village_location_info(db, rep_lat, rep_lon)
            if report_info:
                report_village = report_info.get("village_name")
        except Exception:
            report_info = None

    evidence_points: list[Dict[str, Any]] = []
    evidence_villages: list[str] = []

    for ef in report.evidence_files or []:
        lat = _float_or_none(ef.media_latitude)
        lon = _float_or_none(ef.media_longitude)
        if lat is None or lon is None:
            continue
        info = None
        village_name = None
        try:
            info = get_village_location_info(db, lat, lon)
            if info:
                village_name = info.get("village_name")
        except Exception:
            info = None
        evidence_points.append({"lat": lat, "lon": lon, "info": info, "village": village_name})
        if village_name:
            evidence_villages.append(village_name)

    unique_evidence_villages = set(ev for ev in evidence_villages if ev)

    # Case 1: reporter + all evidence in same village
    if report_village and unique_evidence_villages and len(unique_evidence_villages) == 1 and report_village in unique_evidence_villages:
        chosen_info = report_info
        chosen_lat, chosen_lon = rep_lat, rep_lon
        if chosen_lat is None or chosen_lon is None:
            same_village_points = [p for p in evidence_points if p.get("village") == report_village]
            if same_village_points:
                chosen_lat = same_village_points[0]["lat"]
                chosen_lon = same_village_points[0]["lon"]
                chosen_info = same_village_points[0]["info"] or chosen_info
        return chosen_lat, chosen_lon, "same_village_all", chosen_info

    # Case 2: reporter village exists (with or without evidence)
    if report_village:
        chosen_lat, chosen_lon, chosen_info = rep_lat, rep_lon, report_info
        if unique_evidence_villages and (len(unique_evidence_villages) > 1 or report_village not in unique_evidence_villages):
            source = "village_conflict"
        else:
            source = "reporter_only"
        return chosen_lat, chosen_lon, source, chosen_info

    # Case 3: no reporter village, but evidence villages exist
    if unique_evidence_villages:
        from collections import Counter

        counts = Counter(ev for ev in evidence_villages if ev)
        dominant_village, _ = counts.most_common(1)[0]
        dominant_points = [p for p in evidence_points if p.get("village") == dominant_village]
        chosen = dominant_points[0] if dominant_points else evidence_points[0]
        source = "evidence_only" if len(unique_evidence_villages) == 1 else "evidence_conflict"
        return chosen["lat"], chosen["lon"], source, chosen["info"]

    # Case 4: no villages at all – fall back to raw coordinates
    if rep_lat is not None and rep_lon is not None:
        return rep_lat, rep_lon, "reporter_only_no_village", None
    if evidence_points:
        p = evidence_points[0]
        return p["lat"], p["lon"], "evidence_only_no_village", p["info"]

    return None, None, "unknown", None


@router.get("/", response_model=ReportListResponse | List[ReportResponse])
def list_reports(
    device_id: Optional[UUID] = Query(None, description="Device ID for 'my reports' (mobile). If omitted, auth required for all reports."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    rule_status: Optional[str] = Query(None, description="Filter by rule_status: pending, passed, flagged, rejected."),
    incident_type_id: Optional[int] = Query(None, description="Filter by incident type."),
    village_location_id: Optional[int] = Query(None, description="Filter by village/location."),
    from_date: Optional[datetime] = Query(None, description="Reports reported on or after this date (ISO)."),
    to_date: Optional[datetime] = Query(None, description="Reports reported on or before this date (ISO)."),
    limit: int = Query(20, ge=1, le=100, description="Page size (police list only)."),
    offset: int = Query(0, ge=0, description="Skip N items (police list only)."),
):
    """List reports.

    - With device_id: list for that device (mobile).
    - Without device_id: auth required.
      * Officers: only reports assigned to them.
      * Supervisors: reports in their assigned location (if set).
      * Admins: all reports.
    """
    if device_id is not None:
        reports = (
            db.query(Report)
            .options(
                joinedload(Report.device),
                joinedload(Report.incident_type),
                joinedload(Report.village_location),
                selectinload(Report.evidence_files),
                selectinload(Report.hotspots),
                selectinload(Report.assignments),
                selectinload(Report.ml_predictions),
            )
            .filter(Report.device_id == device_id)
            .order_by(Report.reported_at.desc())
            .all()
        )
        return [_build_report_response(r, db) for r in reports]
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    query = db.query(Report).options(
        joinedload(Report.device),
        joinedload(Report.incident_type),
        joinedload(Report.village_location),
        selectinload(Report.evidence_files),
        selectinload(Report.hotspots),
        selectinload(Report.assignments),
        selectinload(Report.ml_predictions),
    )
    role = getattr(current_user, "role", None)

    # Officers see only reports assigned to them
    if role == "officer":
        query = query.join(Report.assignments).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
    # Supervisors see reports in their assigned location (if configured)
    elif role == "supervisor" and getattr(current_user, "assigned_location_id", None):
        query = query.filter(Report.village_location_id == current_user.assigned_location_id)
    if rule_status:
        query = query.filter(Report.rule_status == rule_status)
    if incident_type_id is not None:
        query = query.filter(Report.incident_type_id == incident_type_id)
    if village_location_id is not None:
        query = query.filter(Report.village_location_id == village_location_id)
    if from_date is not None:
        query = query.filter(Report.reported_at >= from_date)
    if to_date is not None:
        query = query.filter(Report.reported_at <= to_date)
    total = query.count()
    reports = (
        query.order_by(Report.reported_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ReportListResponse(
        items=[_build_report_response(r, db) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: UUID,
    device_id: Optional[UUID] = Query(None, description="Device ID (mobile owner). If omitted, auth required."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
):
    """Get one report. With device_id: only if device owns it. Without: require auth (police). Returns report with evidence_files."""
    if device_id is not None:
        report = (
            db.query(Report)
            .options(joinedload(Report.incident_type), joinedload(Report.evidence_files))
            .filter(Report.report_id == report_id, Report.device_id == device_id)
            .first()
        )
    else:
        if current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        report = (
            db.query(Report)
            .options(
                joinedload(Report.incident_type),
                joinedload(Report.evidence_files),
                joinedload(Report.assignments).joinedload(ReportAssignment.police_user),
                joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
            )
            .filter(Report.report_id == report_id)
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    # Officers may only view reports assigned to them
    if device_id is None and current_user and getattr(current_user, "role", None) == "officer":
        assigned_to_me = any(
            a.police_user_id == current_user.police_user_id
            for a in (report.assignments or [])
        )
        if not assigned_to_me:
            raise HTTPException(status_code=403, detail="You can only view reports assigned to you")

    assignment_list = []
    if device_id is None and getattr(report, "assignments", None):
        for a in report.assignments:
            officer_name = None
            if a.police_user:
                officer_name = f"{a.police_user.first_name or ''} {a.police_user.last_name or ''}".strip() or a.police_user.email
            assignment_list.append(
                AssignmentResponse(
                    assignment_id=a.assignment_id,
                    report_id=a.report_id,
                    police_user_id=a.police_user_id,
                    status=a.status,
                    priority=a.priority,
                    assigned_at=a.assigned_at,
                    completed_at=a.completed_at,
                    officer_name=officer_name,
                )
            )
        assignment_list.sort(key=lambda x: x.assigned_at, reverse=True)

    review_list = []
    if device_id is None and getattr(report, "police_reviews", None):
        for r in report.police_reviews:
            reviewer_name = None
            if r.police_user:
                reviewer_name = f"{r.police_user.first_name or ''} {r.police_user.last_name or ''}".strip() or r.police_user.email
            review_list.append(
                ReviewResponse(
                    review_id=r.review_id,
                    report_id=r.report_id,
                    police_user_id=r.police_user_id,
                    decision=r.decision,
                    review_note=r.review_note,
                    reviewed_at=r.reviewed_at,
                    reviewer_name=reviewer_name,
                )
            )
        review_list.sort(key=lambda x: x.reviewed_at, reverse=True)

    incident_lat, incident_lon, incident_source, incident_location_info = _compute_incident_location_with_villages(report, db)

    return ReportDetailResponse(
        report_id=report.report_id,
        device_id=report.device_id,
        incident_type_id=report.incident_type_id,
        description=report.description,
        latitude=report.latitude,
        longitude=report.longitude,
        reported_at=report.reported_at,
        rule_status=report.rule_status,
        village_location_id=report.village_location_id,
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        incident_latitude=float(incident_lat) if incident_lat is not None else None,
        incident_longitude=float(incident_lon) if incident_lon is not None else None,
        incident_location_source=incident_source,
        incident_village_name=incident_location_info["village_name"] if incident_location_info else None,
        incident_cell_name=incident_location_info.get("cell_name") if incident_location_info else None,
        incident_sector_name=incident_location_info.get("sector_name") if incident_location_info else None,
        evidence_files=[
            EvidenceFileResponse(
                evidence_id=ef.evidence_id,
                report_id=ef.report_id,
                file_url=ef.file_url,
                file_type=ef.file_type,
                uploaded_at=ef.uploaded_at,
                media_latitude=float(ef.media_latitude) if ef.media_latitude is not None else None,
                media_longitude=float(ef.media_longitude) if ef.media_longitude is not None else None,
            )
            for ef in report.evidence_files
        ],
        assignments=assignment_list,
        reviews=review_list,
    )


@router.post("/{report_id}/reviews", response_model=ReviewResponse, status_code=201)
def add_review(
    report_id: UUID,
    body: ReviewCreate,
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """
    Add a police review (decision + note).

    - Admin / Supervisor: any report they can see.
    - Officer: only for reports assigned to them.
    """
    if body.decision not in ("confirmed", "rejected", "investigation"):
        raise HTTPException(status_code=400, detail="decision must be confirmed, rejected, or investigation")

    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    role = getattr(current_user, "role", None)
    if role == "officer":
        assigned = (
            db.query(ReportAssignment)
            .filter(
                ReportAssignment.report_id == report_id,
                ReportAssignment.police_user_id == current_user.police_user_id,
            )
            .first()
        )
        if not assigned:
            raise HTTPException(
                status_code=403,
                detail="You can only review reports assigned to you",
            )

    # Update report verification and status when police confirms or rejects
    now_utc = datetime.now(timezone.utc)
    if body.decision == "confirmed":
        report.verification_status = "verified"
        report.verified_by = current_user.police_user_id
        report.verified_at = now_utc
        report.status = "verified"
        report.is_flagged = False
        report.flag_reason = None
    elif body.decision == "rejected":
        report.verification_status = "rejected"
        report.verified_by = current_user.police_user_id
        report.verified_at = now_utc
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = body.review_note or "rejected_by_reviewer"
    else:
        # investigation
        report.verification_status = "under_review"
        if body.review_note:
            report.flag_reason = body.review_note

    review = PoliceReview(
        review_id=uuid4(),
        report_id=report_id,
        police_user_id=current_user.police_user_id,
        decision=body.decision,
        review_note=body.review_note,
    )
    db.add(review)
    log_action(
        db,
        "report_reviewed",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id=str(report_id),
        action_details={"decision": body.decision},
        success=True,
    )
    db.commit()
    db.refresh(review)
    reviewer_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email
    return ReviewResponse(
        review_id=review.review_id,
        report_id=review.report_id,
        police_user_id=review.police_user_id,
        decision=review.decision,
        review_note=review.review_note,
        reviewed_at=review.reviewed_at,
        reviewer_name=reviewer_name,
    )


@router.post("/{report_id}/assign", response_model=AssignmentResponse, status_code=201)
def assign_report(
    report_id: UUID,
    body: AssignCreate,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    db: Session = Depends(get_db),
):
    """Assign this report to an officer. Admin or supervisor only.

    - Admin: can assign to any active officer.
    - Supervisor: can assign only to officers in their own station (if they have one).
    """
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    officer = (
        db.query(PoliceUser)
        .filter(
            PoliceUser.police_user_id == body.police_user_id,
            PoliceUser.is_active == True,
        )
        .first()
    )
    if not officer:
        raise HTTPException(status_code=400, detail="Officer not found or inactive")

    # Supervisors can only assign to officers in their station.
    if current_user.role == "supervisor" and current_user.station_id is not None:
        if officer.station_id != current_user.station_id:
            raise HTTPException(
                status_code=403,
                detail="You can only assign reports to officers in your station",
            )
    if body.priority not in ("low", "medium", "high", "urgent"):
        raise HTTPException(status_code=400, detail="priority must be low, medium, high, or urgent")

    # Set handling_station_id when assigning to an officer with a station
    if officer.station_id is not None:
        report.handling_station_id = officer.station_id

    assignment = ReportAssignment(
        assignment_id=uuid4(),
        report_id=report_id,
        police_user_id=body.police_user_id,
        status="assigned",
        priority=body.priority,
    )
    db.add(assignment)
    create_notification(
        db,
        police_user_id=body.police_user_id,
        title="Report assigned",
        message=f"Report has been assigned to you (priority: {body.priority}).",
        notif_type="assignment",
        related_entity_type="report",
        related_entity_id=str(report_id),
    )
    log_action(
        db,
        "report_assigned",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id=str(report_id),
        action_details={"assigned_to": body.police_user_id, "priority": body.priority},
        success=True,
    )
    db.commit()
    db.refresh(assignment)
    officer_name = f"{officer.first_name or ''} {officer.last_name or ''}".strip() or officer.email
    return AssignmentResponse(
        assignment_id=assignment.assignment_id,
        report_id=assignment.report_id,
        police_user_id=assignment.police_user_id,
        status=assignment.status,
        priority=assignment.priority,
        assigned_at=assignment.assigned_at,
        completed_at=assignment.completed_at,
        officer_name=officer_name,
    )


@router.post("/{report_id}/evidence")
async def upload_evidence(
    report_id: str,
    file: UploadFile = File(...),
    device_id: Optional[str] = Form(None, description="Device ID UUID (mobile: required to add evidence to own report)."),
    media_latitude: Optional[float] = Form(None),
    media_longitude: Optional[float] = Form(None),
    captured_at: Optional[datetime] = Form(None),
    is_live_capture: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
):
    """Upload evidence file (photo/video) for a report.

    Mobile: pass device_id to add evidence to your own report (only within evidence_add_window_hours after submit).
    Police dashboard: no device_id; requires auth (future use).
    """
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    device_id_uuid: Optional[UUID] = None
    if device_id is not None and device_id.strip():
        try:
            device_id_uuid = UUID(device_id.strip())
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid device_id format")

    if device_id_uuid is not None:
        if str(report.device_id) != str(device_id_uuid):
            raise HTTPException(status_code=403, detail="You can only add evidence to your own report")
        window_hours = getattr(settings, "evidence_add_window_hours", 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
        if reported_at < cutoff:
            raise HTTPException(
                status_code=400,
                detail=f"You can add evidence only within {window_hours} hours of submitting the report",
            )
    elif current_user is None:
        raise HTTPException(status_code=400, detail="device_id required to add evidence (mobile)")

    # Read file content once
    content = await file.read()

    file_ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else ""
    # Basic extension-based type detection (content_type first, then extension)
    image_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
    video_exts = {"mp4", "mov", "m4v", "avi", "mkv", "webm"}
    audio_exts = {"mp3", "wav", "aac", "m4a", "ogg", "flac"}

    is_image = False
    is_audio = False

    # 1) Try to classify by content_type
    if file.content_type:
        ct = file.content_type.lower()
        if ct.startswith("image/"):
            is_image = True
        elif ct.startswith("audio/"):
            is_audio = True
        # if it's "application/octet-stream" or something else, we'll fall back to extension

    # 2) If still unknown, fall back to extension
    if not (is_image or is_audio):
        if file_ext in image_exts:
            is_image = True
        elif file_ext in audio_exts:
            is_audio = True
        # otherwise we'll treat it as video by default

    if is_image:
        file_type = "photo"
    elif is_audio:
        file_type = "audio"
    else:
        file_type = "video"

    # Rule-based: no screenshots or screen recordings (image, audio, or video)
    if is_likely_screenshot_or_screen_recording(
        filename=file.filename,
        image_bytes=content if is_image else None,
    ):
        raise HTTPException(
            status_code=400,
            detail="Screenshots and screen recordings are not allowed. Please upload a photo, audio, or video taken with your camera or recorder.",
        )

    # Cloudinary upload if configured, otherwise save locally
    if _CLOUDINARY_ENABLED:
        upload_opts = {"folder": "trustbond/evidence"}
        # Cloudinary uses resource_type="video" for both video and audio
        if not is_image:
            upload_opts["resource_type"] = "video"

        try:
            # Wrap bytes in a file-like object so Cloudinary treats it as an uploaded file
            file_obj = io.BytesIO(content)
            # Give Cloudinary a sensible name (helps with type detection / extensions)
            file_obj.name = file.filename or f"{uuid4()}.{file_ext or 'bin'}"

            upload_result = cloudinary.uploader.upload(file_obj, **upload_opts)
            file_url = upload_result.get("secure_url") or upload_result.get("url")
        except Exception as e:
            # In production mode with Cloudinary configured, we do NOT write to local disk.
            # The client (mobile app) should handle offline/low-network by queuing uploads locally.
            print(f"[Cloudinary] upload error for report {report_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Cloudinary upload failed: {e}")
    else:
        # Dev mode without Cloudinary configured: save to local disk
        safe_ext = file_ext or "bin"
        file_name = f"{uuid4()}.{safe_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as f:
            f.write(content)
        file_url = f"/uploads/evidence/{file_name}"

    # EXIF-based metadata extraction for images
    exif_lat = exif_lon = None
    exif_dt = None
    if is_image:
        exif_lat, exif_lon, exif_dt = _extract_exif_metadata(content)

    final_lat = exif_lat if exif_lat is not None else media_latitude
    final_lon = exif_lon if exif_lon is not None else media_longitude

    # captured_at priority:
    # 1) EXIF DateTimeOriginal / DateTime (true capture time if present)
    # 2) Client-provided captured_at (from mobile app)
    # 3) Optional fallback to report.reported_at for live captures only
    final_captured_at = exif_dt if exif_dt is not None else captured_at
    if final_captured_at is None and is_live_capture:
        # For true live captures (camera in app), if we somehow didn't get
        # EXIF or client timestamp, approximate with report time.
        final_captured_at = report.reported_at
    
    evidence = EvidenceFile(
        evidence_id=uuid4(),
        report_id=report.report_id,
        file_url=file_url,
        file_type=file_type,
        media_latitude=final_lat,
        media_longitude=final_lon,
        captured_at=final_captured_at,
        is_live_capture=is_live_capture,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    # Re-run rule-based verification (evidence count changed; no ML)
    report_after = db.query(Report).filter(Report.report_id == report.report_id).first()
    if report_after:
        evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_after.report_id).count()
        rule_status, is_flagged, flag_reason = apply_rule_based_status(report_after, evidence_count, db)
        report_after.rule_status = rule_status
        report_after.is_flagged = is_flagged
        if is_flagged and flag_reason:
            report_after.flag_reason = flag_reason
        db.commit()
    
    return {"evidence_id": str(evidence.evidence_id), "file_url": file_url}
