from typing import Annotated, Optional, List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query, status
from sqlalchemy.orm import Session, joinedload
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
from app.models.device import Device
from app.models.incident_type import IncidentType
from app.schemas.report import (
    ReportCreate,
    ReportResponse,
    ReportDetailResponse,
    ReportListResponse,
    EvidenceFileResponse,
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
from app.core.audit import log_action
from app.core.hotspot_auto import create_hotspots_from_reports
from app.core.village_lookup import get_village_location_id, get_village_location_info
from app.core.report_location import compute_incident_location

router = APIRouter(prefix="/reports", tags=["reports"])

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
    
    # Create report
    report = Report(
        report_id=uuid4(),
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
    )
    
    report.village_location_id = village_id  # already looked up above (required for in-scope)
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
    rule_status, is_flagged = apply_rule_based_status(report, evidence_count, db)
    report.rule_status = rule_status
    report.is_flagged = is_flagged
    
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
    return ReportResponse(
        report_id=r.report_id,
        device_id=r.device_id,
        incident_type_id=r.incident_type_id,
        description=r.description,
        latitude=r.latitude,
        longitude=r.longitude,
        reported_at=r.reported_at,
        rule_status=r.rule_status,
        village_location_id=r.village_location_id,
        village_name=village_name,
        incident_type_name=r.incident_type.type_name if r.incident_type else None,
    )


@router.get("/", response_model=ReportListResponse | List[ReportResponse])
def list_reports(
    device_id: Optional[UUID] = Query(None, description="Device ID for 'my reports' (mobile). If omitted, auth required for all reports."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    rule_status: Optional[str] = Query(None, description="Filter by rule_status: pending, passed, flagged (suspicious/needs review), rejected."),
    from_date: Optional[datetime] = Query(None, description="Reports reported on or after this date (ISO)."),
    to_date: Optional[datetime] = Query(None, description="Reports reported on or before this date (ISO)."),
    limit: int = Query(20, ge=1, le=100, description="Page size (police list only)."),
    offset: int = Query(0, ge=0, description="Skip N items (police list only)."),
):
    """List reports. With device_id: list for that device (mobile). Without: auth required. Officers see only reports assigned to them; supervisors/admins see all."""
    if device_id is not None:
        reports = (
            db.query(Report)
            .options(joinedload(Report.incident_type), joinedload(Report.village_location))
            .filter(Report.device_id == device_id)
            .order_by(Report.reported_at.desc())
            .all()
        )
        return [_build_report_response(r, db) for r in reports]
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    query = db.query(Report).options(joinedload(Report.incident_type), joinedload(Report.village_location))
    # Officers see only reports assigned to them
    if getattr(current_user, "role", None) == "officer":
        query = query.join(Report.assignments).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
    if rule_status:
        query = query.filter(Report.rule_status == rule_status)
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

    incident_lat, incident_lon, incident_source = compute_incident_location(report, report.evidence_files)

    incident_location_info = None
    if incident_lat is not None and incident_lon is not None:
        incident_location_info = get_village_location_info(db, incident_lat, incident_lon)

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
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    db: Session = Depends(get_db),
):
    """Add a police review (decision + note). Admin or supervisor only."""
    if body.decision not in ("confirmed", "rejected", "investigation"):
        raise HTTPException(status_code=400, detail="decision must be confirmed, rejected, or investigation")
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
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
    """Assign this report to an officer. Admin or supervisor only."""
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    officer = db.query(PoliceUser).filter(
        PoliceUser.police_user_id == body.police_user_id,
        PoliceUser.is_active == True,
    ).first()
    if not officer:
        raise HTTPException(status_code=400, detail="Officer not found or inactive")
    if body.priority not in ("low", "medium", "high", "urgent"):
        raise HTTPException(status_code=400, detail="priority must be low, medium, high, or urgent")
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
        rule_status, is_flagged = apply_rule_based_status(report_after, evidence_count, db)
        report_after.rule_status = rule_status
        report_after.is_flagged = is_flagged
        db.commit()
    
    return {"evidence_id": str(evidence.evidence_id), "file_url": file_url}
