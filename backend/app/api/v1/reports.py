import logging
from typing import Annotated, Optional, List, Tuple, Dict, Any
from decimal import Decimal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query, status, Request
from sqlalchemy.orm import Session, joinedload, selectinload
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
import io
import os
import math
import hashlib

import cloudinary
import cloudinary.uploader
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.report import Report
from app.models.evidence_file import EvidenceFile
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.device import Device
from app.models.incident_type import IncidentType
from app.models.location import Location
from app.models.station import Station
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
from app.core.security import verify_password
from app.core.websocket import manager
from app.api.v1.auth import get_optional_user, get_current_user, get_current_admin_or_supervisor
from app.api.v1.notifications import create_notification
from app.core.report_rules import apply_rule_based_status, is_likely_screenshot_or_screen_recording
from app.core.report_review import (
    needs_police_review_clause,
    resolve_display_trust_score,
    resolve_ml_prediction_for_report,
    resolve_ml_prediction_label_for_display,
)
from app.core.credibility_model import score_report_credibility, update_device_ml_aggregates, _json_safe
from app.core.audit import log_action
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from app.core.village_lookup import get_village_location_id, get_village_location_info
from app.schemas.report import CommunityVoteRequest
from sqlalchemy import text, or_, func, cast, String

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _log_blocked_attempt(
    db: Session,
    *,
    action_type: str,
    request: Optional[Request],
    device: Optional[Device],
    report_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit logging for blocked device actions."""
    try:
        client_ip = request.client.host if request and request.client else None
        user_agent = request.headers.get("user-agent") if request else None
        payload = dict(details or {})
        if device is not None:
            payload["device_id"] = str(device.device_id)
            payload["device_hash"] = getattr(device, "device_hash", None)
        log_action(
            db,
            action_type,
            actor_type="system",
            entity_type="report",
            entity_id=report_id,
            action_details=payload,
            ip_address=client_ip,
            user_agent=user_agent,
            success=False,
        )
        db.commit()
    except Exception:
        db.rollback()


def _enforce_device_submission_guards(
    db: Session,
    device: Device,
    report_data: ReportCreate,
    request: Optional[Request] = None,
) -> None:
    """
    Anti-abuse controls:
    1) Block same device submitting duplicate incident repeatedly in a short window.
    2) Block impossible movement patterns (e.g. 20km in 5 minutes).
    """
    now_utc = datetime.now(timezone.utc)
    current_lat = float(report_data.latitude)
    current_lon = float(report_data.longitude)

    window_start = now_utc - timedelta(minutes=settings.device_activity_window_minutes)
    recent_reports = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= window_start,
        )
        .order_by(Report.reported_at.desc())
        .limit(25)
        .all()
    )

    duplicate_window = int(settings.duplicate_report_time_window_seconds)
    duplicate_radius_km = float(settings.duplicate_report_radius_meters) / 1000.0

    for prev in recent_reports:
        prev_time = _to_utc(prev.reported_at)
        if prev_time is None:
            continue
        delta_seconds = max(0.0, (now_utc - prev_time).total_seconds())
        if delta_seconds > duplicate_window:
            continue

        if int(prev.incident_type_id) != int(report_data.incident_type_id):
            continue

        prev_lat = float(prev.latitude)
        prev_lon = float(prev.longitude)
        distance_km = _haversine_km(current_lat, current_lon, prev_lat, prev_lon)
        if distance_km <= duplicate_radius_km:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_duplicate",
                request=request,
                device=device,
                details={
                    "incident_type_id": int(report_data.incident_type_id),
                    "distance_km": round(distance_km, 4),
                    "time_delta_seconds": int(delta_seconds),
                    "duplicate_window_seconds": duplicate_window,
                    "duplicate_radius_meters": int(settings.duplicate_report_radius_meters),
                },
            )
            raise HTTPException(
                status_code=409,
                detail="Duplicate incident detected from this device in a short time window. Please wait before submitting the same incident again.",
            )

    impossible_window = int(settings.impossible_travel_window_seconds)
    impossible_distance_km = float(settings.impossible_travel_min_distance_km)
    max_speed_kmh = float(settings.max_plausible_speed_kmh)

    for prev in recent_reports:
        prev_time = _to_utc(prev.reported_at)
        if prev_time is None:
            continue
        delta_seconds = max(0.0, (now_utc - prev_time).total_seconds())
        if delta_seconds <= 0 or delta_seconds > impossible_window:
            continue

        prev_lat = float(prev.latitude)
        prev_lon = float(prev.longitude)
        distance_km = _haversine_km(current_lat, current_lon, prev_lat, prev_lon)
        if distance_km < impossible_distance_km:
            continue

        speed_kmh = distance_km / (delta_seconds / 3600.0)
        if speed_kmh >= max_speed_kmh:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_impossible_travel",
                request=request,
                device=device,
                details={
                    "incident_type_id": int(report_data.incident_type_id),
                    "distance_km": round(distance_km, 3),
                    "time_delta_seconds": int(delta_seconds),
                    "speed_kmh": round(speed_kmh, 2),
                    "threshold_speed_kmh": max_speed_kmh,
                    "impossible_window_seconds": impossible_window,
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Impossible movement pattern detected for this device (large distance in short time). Report blocked for integrity checks.",
            )


def _ensure_fallback_ml_prediction_if_missing(db: Session, report: Report) -> None:
    """
    XGBoost scoring may skip inserting a row (no model, bad meta, errors).
    Persist a heuristic evaluation so list/detail APIs always have ml_predictions
    (prediction_label, trust_score, etc.) when possible.

    Called on every new report (`create_report`) and after community re-score so the
    Reports page can read real DB rows — ongoing operation does not require manual backfill.
    """
    from app.models.ml_prediction import MLPrediction

    exists = (
        db.query(MLPrediction.prediction_id)
        .filter(MLPrediction.report_id == report.report_id)
        .limit(1)
        .first()
    )
    if exists is not None:
        return
    try:
        from app.utils.ml_evaluator import ml_evaluator

        ml_result = ml_evaluator.evaluate_report(report)
        db.add(
            MLPrediction(
                prediction_id=uuid4(),
                report_id=report.report_id,
                trust_score=ml_result["trust_score"],
                prediction_label=ml_result["prediction_label"],
                confidence=ml_result["confidence"],
                model_type="auto_evaluation",
                is_final=False,
                evaluated_at=datetime.now(timezone.utc),
            )
        )
        logger.info(
            "Fallback ML row for report %s: %s (%.1f%%)",
            report.report_id,
            ml_result.get("prediction_label"),
            float(ml_result.get("trust_score") or 0),
        )
    except Exception as exc:
        logger.warning(
            "Could not create fallback ml_prediction for report %s: %s",
            report.report_id,
            exc,
            exc_info=True,
        )


#this marks the biggining of changes I did to implement AI-enhanced rules and ML-based auto-verification in the create_report endpoint. The improvements include:
#1) AI-enhanced rules: Implemented a new function apply_ai_enhanced_rules
def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _auto_reject_report_for_invalid_evidence(
    db: Session,
    report: Report,
    reason: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an automatic rejection and attach AI-readable reason metadata."""
    report.rule_status = "rejected"
    report.status = "rejected"
    report.verification_status = "rejected"
    report.is_flagged = True
    report.flag_reason = reason

    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        fv = {}
    fv["ai_rejected"] = True
    fv["ai_rejection_reason"] = reason
    fv["ai_rejected_at"] = datetime.now(timezone.utc).isoformat()
    if details:
        fv["ai_rejection_details"] = details
    report.feature_vector = _json_safe(fv)

    # Best-effort: re-run scoring so the ML explanation can include the rejected rule status.
    try:
        device = db.query(Device).filter(Device.device_id == report.device_id).first()
        evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).count()
        if device is not None:
            score_report_credibility(db, report, device, evidence_count)
    except Exception:
        pass

    db.commit()
    db.refresh(report)
 
 #this marks the end of improvement I did

def run_hotspot_auto():
    """Background task to fully recompute DBSCAN hotspots from all reports."""
    db = SessionLocal()
    try:
        tw, mi, rm = get_hotspot_params_from_db(db)
        trust_min = get_hotspot_trust_min_from_db(db)

        # Full refresh so every new incident re-analyzes entire DB history.
        from app.models.hotspot import hotspot_reports_table
        db.execute(hotspot_reports_table.delete())
        db.query(Hotspot).delete()
        db.commit()

        created = create_hotspots_from_reports(
            db,
            time_window_hours=tw,
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=True,
        )
        if created > 0:
            print(f"Background hotspot creation: {created} new hotspots created")
            
            # Broadcast hotspot update to all connected clients for real-time Safety Map updates
            try:
                import asyncio
                from app.core.websocket import manager
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "hotspot", "action": "auto_created"}))
                except RuntimeError:
                    asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "hotspot", "action": "auto_created"}))
            except Exception as e:
                print(f"Failed to broadcast hotspot update: {e}")
            
            # Create notifications for admins and supervisors about new hotspots
            from app.api.v1.notifications import create_role_notifications
            create_role_notifications(
                db,
                title="New Hotspots Detected",
                message=f"{created} new safety hotspots have been automatically detected based on recent reports.",
                notif_type="hotspot",
                target_roles=["admin", "supervisor"],
            )
        db.commit()
    except Exception as e:
        print(f"Error in background hotspot creation: {e}")
        db.rollback()
    finally:
        db.close()


def _purge_outside_musanze_reports(db: Session, recompute_hotspots: bool = True) -> tuple[int, int]:
    """Delete reports outside covered village polygons and optionally recompute hotspots.

    Returns:
        (deleted_reports, recomputed_hotspots)
    """
    rows = db.execute(
        text(
            """
            SELECT
                r.report_id,
                v.location_id AS resolved_village_id
            FROM reports r
            LEFT JOIN LATERAL (
                SELECT l.location_id
                FROM locations l
                WHERE l.location_type = 'village'
                  AND l.is_active = true
                  AND l.geometry IS NOT NULL
                  AND ST_Contains(
                      l.geometry,
                      ST_SetSRID(
                          ST_MakePoint(
                              CAST(r.longitude AS DOUBLE PRECISION),
                              CAST(r.latitude AS DOUBLE PRECISION)
                          ),
                          4326
                      )
                  )
                LIMIT 1
            ) v ON TRUE
            """
        )
    ).fetchall()

    in_area_updates = []
    outside_ids = []
    for row in rows:
        report_id = row[0]
        resolved_village_id = row[1]
        if resolved_village_id is None:
            outside_ids.append(report_id)
        else:
            in_area_updates.append(
                {
                    "report_id": report_id,
                    "village_location_id": int(resolved_village_id),
                    "location_id": int(resolved_village_id),
                }
            )

    if in_area_updates:
        db.execute(
            text(
                """
                UPDATE reports
                SET village_location_id = :village_location_id,
                    location_id = :location_id
                WHERE report_id = :report_id
                """
            ),
            in_area_updates,
        )

    deleted_reports = 0
    if outside_ids:
        db.execute(
            text("DELETE FROM ml_predictions WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM evidence_files WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM police_reviews WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM report_assignments WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM case_reports WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )

        db.execute(
            hotspot_reports_table.delete().where(
                hotspot_reports_table.c.report_id.in_(outside_ids)
            )
        )
        deleted_reports = (
            db.query(Report)
            .filter(Report.report_id.in_(outside_ids))
            .delete(synchronize_session=False)
        )

    recomputed = 0
    if recompute_hotspots:
        db.execute(hotspot_reports_table.delete())
        db.query(Hotspot).delete()
        db.commit()

        tw, mi, rm = get_hotspot_params_from_db(db)
        trust_min = get_hotspot_trust_min_from_db(db)
        recomputed = create_hotspots_from_reports(
            db,
            time_window_hours=tw,
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=True,
        )

    db.commit()
    return deleted_reports, recomputed


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
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new report."""
    """Submit a new incident report. Device can be identified by device_id or device_hash (find-or-create)."""
    device = None
    if report_data.device_id:
        device = db.query(Device).filter(Device.device_id == report_data.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
    if device is None and report_data.device_hash and str(report_data.device_hash).strip():
        device = (
            db.query(Device)
            .filter(Device.device_hash == report_data.device_hash.strip())
            .first()
        )
        if not device:
            device = Device(
                device_id=uuid4(),
                device_hash=report_data.device_hash.strip(),
            )
            db.add(device)
            db.flush()
    if not device:
        raise HTTPException(status_code=400, detail="Either device_id or device_hash is required")
    # Block reporting from banned devices (admin action)
    if getattr(device, "is_banned", False):
        raise HTTPException(status_code=403, detail="This device is banned from submitting reports")

    _enforce_device_submission_guards(db, device, report_data, request)

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

    # Boundary validation: reports outside Musanze are persisted but explicitly
    # marked as rejected so they never contribute to clustering.
    village_id = None
    village_info = None
    out_of_boundary = False
    out_of_boundary_reason: Optional[str] = None
    try:
        lat_f = float(report_data.latitude)
        lon_f = float(report_data.longitude)

        village_id = get_village_location_id(db, lat_f, lon_f)
        village_info = get_village_location_info(db, lat_f, lon_f)

        if not village_id or not village_info:
            out_of_boundary = True
            out_of_boundary_reason = (
                f"out_of_musanze_boundary: ({lat_f:.4f}, {lon_f:.4f})"
            )

        district_name = (village_info.get("district_name") or "").strip().lower()
        if district_name and district_name != "musanze":
            out_of_boundary = True
            out_of_boundary_reason = f"out_of_musanze_boundary: district={district_name}"
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid coordinates: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Location validation failed: {e}")
    
    report_num = _generate_report_number(db) if hasattr(Report, "report_number") else None
    report = Report(
        report_id=uuid4(),
        report_number=report_num,
        device_id=device.device_id,
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
    if not out_of_boundary and village_id is not None:
        report.village_location_id = village_id
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

    if out_of_boundary:
        report.rule_status = "rejected"
        report.status = "rejected"
        report.verification_status = "rejected"
        report.is_flagged = True
        report.flag_reason = out_of_boundary_reason or "out_of_musanze_boundary"

        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        fv["boundary_status"] = "out_of_musanze"
        fv["excluded_from_clustering"] = True
        fv["boundary_reason"] = report.flag_reason
        report.feature_vector = _json_safe(fv)

        now_utc = datetime.now(timezone.utc)
        device.total_reports += 1
        if hasattr(device, "last_seen_at"):
            device.last_seen_at = now_utc
        if hasattr(device, "flagged_reports"):
            device.flagged_reports = (device.flagged_reports or 0) + 1
        if hasattr(device, "spam_flags"):
            device.spam_flags = (device.spam_flags or 0) + 1

        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        log_action(
            db,
            "report_created_out_of_boundary",
            entity_type="report",
            entity_id=str(report.report_id),
            actor_type="system",
            action_details={"reason": report.flag_reason},
            ip_address=client_ip,
            user_agent=user_agent,
            success=True,
        )

        db.commit()
        db.refresh(report)
        background_tasks.add_task(
            manager.broadcast,
            {"type": "refresh_data", "entity": "report", "action": "created"},
        )
        return report

    # AI-enhanced rule-based verification
    evidence_count = len(report_data.evidence_files)
    
    # ML-based credibility scoring (best-effort; failures are ignored)
    print("Running ML credibility scoring...")  # Debug log
    score_report_credibility(db, report, device, evidence_count)
    _ensure_fallback_ml_prediction_if_missing(db, report)
    # Update device aggregates derived from recent ML predictions + behavior
    update_device_ml_aggregates(db, device, window=30)
    print("ML scoring completed")  # Debug log
    
    # FIXED: Commit ML prediction to ensure it's available for verification
    db.commit()
    db.refresh(report)  # Ensure we have the latest data including ML predictions

    # Apply AI-enhanced rules
    print(f"Applying AI-enhanced rules - evidence_count: {evidence_count}, description_length: {len(report_data.description or '')}")  # Debug log
    
    # Get ML prediction if available (now available after ML scoring)
    from app.models.ml_prediction import MLPrediction
    ml_prediction = db.query(MLPrediction).filter(MLPrediction.report_id == report.report_id).order_by(MLPrediction.evaluated_at.desc()).first()
    if ml_prediction:
        print(f"Using ML prediction: {ml_prediction.prediction_label}, trust_score: {ml_prediction.trust_score}")  # Debug log
    
    # Apply AI-enhanced rules
    from app.core.report_priority import apply_ai_enhanced_rules, calculate_report_priority
    rule_status, is_flagged, flag_reason = apply_ai_enhanced_rules(
        report, evidence_count, ml_prediction, db
    )
    print(f"AI-enhanced rule result - rule_status: {rule_status}, is_flagged: {is_flagged}, flag_reason: {flag_reason}")  # Debug log
    
    # Calculate automatic priority
    priority = calculate_report_priority(report, ml_prediction, evidence_count, db)
    print(f"Calculated report priority: {priority}")  # Debug log
    
    # Apply results to report
    report.rule_status = rule_status
    report.is_flagged = is_flagged
    report.priority = priority  # Save calculated priority
    if is_flagged and flag_reason:
        report.flag_reason = flag_reason
    if rule_status == "rejected":
        report.status = "rejected"
        report.verification_status = "rejected"
    
    # Set ai_ready = true to indicate AI processing complete
    report.ai_ready = True
    report.features_extracted_at = datetime.now(timezone.utc)
    
    # Automated verification based on AI results
    if rule_status == "passed" and not is_flagged:
        # Auto-verify reports that pass AI rules
        report.verification_status = "verified"
        report.status = "verified"
        print(f"Auto-verifying report {report.report_id} - AI rules passed")
    elif rule_status == "rejected":
        # Auto-reject reports that fail AI rules
        report.verification_status = "rejected"
        report.status = "rejected"
        print(f"Auto-rejecting report {report.report_id} - AI rules rejected")
    else:
        # Only mark for review if there are specific concerns
        review_reasons = {
            "ai_suspicious_review",
            "ai_uncertain_review",
            "incident_description_mismatch",
            "gibberish_description",
            "evidence_time_mismatch",
            "stale_live_capture_timestamp",
            "device_burst_reporting",
            "duplicate_description_recent",
        }
        if flag_reason in review_reasons:
            report.verification_status = "under_review"
            print(f"Rule/AI review reason ({flag_reason}) - setting verification_status to under_review")
        else:
            # Default to verified if no specific concerns
            report.verification_status = "verified"
            report.status = "verified"
            print(f"Auto-verifying report {report.report_id} - no specific concerns found")

    # Update device stats
    now_utc = datetime.now(timezone.utc)
    device.total_reports += 1
    if hasattr(device, "last_seen_at"):
        device.last_seen_at = now_utc
    
    # Update device sector_location_id if report has valid location
    if village_info and village_info.get("sector_location_id"):
        device.sector_location_id = village_info["sector_location_id"]
    
    # Merge non-identifying runtime details into device.metadata_json for debugging/analytics.
    # (Keep it anonymous: app/network/battery/sensor signals, not personal identifiers.)
    if hasattr(device, "metadata_json"):
        meta = getattr(device, "metadata_json", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        meta["last_seen_at"] = now_utc.isoformat()
        
        # Add location hierarchy information to device metadata
        if village_info:
            if village_info.get("sector_name"):
                meta["last_sector_name"] = village_info["sector_name"]
            if village_info.get("sector_location_id"):
                meta["last_sector_location_id"] = village_info["sector_location_id"]
            if village_info.get("cell_name"):
                meta["last_cell_name"] = village_info["cell_name"]
            if village_info.get("cell_location_id"):
                meta["last_cell_location_id"] = village_info["cell_location_id"]
            if village_info.get("village_name"):
                meta["last_village_name"] = village_info["village_name"]
            if village_info.get("village_location_id"):
                meta["last_village_location_id"] = village_info["village_location_id"]
        
        if report_data.app_version is not None:
            meta["last_app_version"] = report_data.app_version
        if report_data.network_type is not None:
            meta["last_network_type"] = report_data.network_type
        if report_data.battery_level is not None:
            try:
                meta["last_battery_level"] = float(report_data.battery_level)
            except Exception:
                meta["last_battery_level"] = report_data.battery_level
        if report_data.gps_accuracy is not None:
            meta["last_gps_accuracy_m"] = report_data.gps_accuracy
        if report_data.motion_level is not None:
            meta["last_motion_level"] = report_data.motion_level
        if report_data.movement_speed is not None:
            meta["last_movement_speed_mps"] = report_data.movement_speed
        if report_data.was_stationary is not None:
            meta["last_was_stationary"] = report_data.was_stationary
        
        # Store the most recent location coordinates from this report
        if report_data.latitude is not None and report_data.longitude is not None:
            meta["last_latitude"] = float(report_data.latitude)
            meta["last_longitude"] = float(report_data.longitude)
            meta["last_location_timestamp"] = now_utc.isoformat()
            
            # Store location history (keep last 10 locations)
            if "location_history" not in meta:
                meta["location_history"] = []
            
            location_entry = {
                "latitude": float(report_data.latitude),
                "longitude": float(report_data.longitude),
                "timestamp": now_utc.isoformat(),
                "gps_accuracy": float(report_data.gps_accuracy) if report_data.gps_accuracy is not None else None,
                "report_id": str(report.report_id)
            }
            
            # Add to history and keep only last 10 entries
            meta["location_history"].append(location_entry)
            if len(meta["location_history"]) > 10:
                meta["location_history"] = meta["location_history"][-10:]
        
        if report_data.aggregate_update_at is not None:
            meta["last_aggregate_update_at"] = report_data.aggregate_update_at.isoformat()
        device.metadata_json = _json_safe(meta)
    # Best-effort counters based on current auto decision.
    # (Later police review can further adjust downstream analytics, but these keep the UI populated.)
    if report.is_flagged or report.rule_status in ("flagged", "rejected"):
        if hasattr(device, "flagged_reports"):
            device.flagged_reports = (device.flagged_reports or 0) + 1
        if hasattr(device, "spam_flags"):
            # Treat flagged/rejected submissions as one spam signal
            device.spam_flags = (device.spam_flags or 0) + 1

    # Get client IP and user agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_action(
        db, 
        "report_created", 
        entity_type="report", 
        entity_id=str(report.report_id), 
        actor_type="system", 
        ip_address=client_ip,
        user_agent=user_agent,
        success=True
    )

    # Create notifications for supervisors and admins about new report
    from app.api.v1.notifications import create_role_notifications
    create_role_notifications(
        db,
        title="New Report Submitted",
        message=f"A new {incident_type.type_name or 'incident'} report has been submitted (ID: {report.report_number}).",
        notif_type="report",
        related_entity_type="report",
        related_entity_id=str(report.report_id),
        target_roles=["supervisor", "admin"],
        target_location_id=report.village_location_id,
    )

    db.commit()
    db.refresh(report)

    # FIXED: Clear verification logic - BOTH rules AND ML must pass for auto-verification
    print(f"Verification check - rule_status: {rule_status}, is_flagged: {is_flagged}, verification_status: {report.verification_status}")  # Debug log
    
    if rule_status == "passed" and not is_flagged and report.verification_status != "under_review":
        # Rules passed, now check ML
        ml_safe = False
        ml_reason = ""
        
        if ml_prediction:
            trust_score = float(ml_prediction.trust_score) if ml_prediction.trust_score else 0
            prediction_label = ml_prediction.prediction_label
            
            print(f"ML check - prediction: {prediction_label}, trust_score: {trust_score:.1f}%")  # Debug log
            
            # Get ML thresholds from system config
            from app.database import SessionLocal
            from app.models.system_config import SystemConfig
            
            db_config = SessionLocal()
            try:
                trust_threshold_config = db_config.query(SystemConfig).filter(
                    SystemConfig.config_key == 'ml.trust_threshold'
                ).first()
                trust_threshold = float(trust_threshold_config.config_value.get('value', 70.0)) if trust_threshold_config else 70.0
            finally:
                db_config.close()
            
            # ML must say "likely_real" AND have >= threshold trust score
            if prediction_label == "likely_real" and trust_score >= trust_threshold:
                ml_safe = True
                ml_reason = f"ML passed: likely_real with sufficient trust ({trust_score:.1f}% >= {trust_threshold:.1f}%)"
            elif prediction_label == "likely_real" and trust_score < trust_threshold:
                ml_safe = False
                ml_reason = f"ML failed: likely_real but low trust ({trust_score:.1f}% < {trust_threshold:.1f}%)"
            elif prediction_label in ["suspicious", "uncertain"]:
                ml_safe = False
                ml_reason = f"ML failed: {prediction_label} prediction (needs review)"
            elif prediction_label == "fake":
                ml_safe = False
                ml_reason = "ML failed: fake prediction (should be rejected)"
            else:
                ml_safe = False
                ml_reason = f"ML failed: unknown prediction {prediction_label}"
        else:
            ml_safe = False
            ml_reason = "ML failed: no ML prediction available"
        
        print(f"ML decision: {ml_reason}")  # Debug log
        
        # Auto-verify ONLY if both rules AND ML pass
        if ml_safe:
            report.status = "verified"
            report.verification_status = "verified"
            print("✅ REPORT AUTO-VERIFIED: Both rules and ML passed")  # Debug log
            db.commit()
            
            # Count auto-verified reports toward device trusted_reports
            if hasattr(device, "trusted_reports"):
                device.trusted_reports = (device.trusted_reports or 0) + 1
                db.commit()
        else:
            print(f"❌ REPORT NOT AUTO-VERIFIED: {ml_reason}")  # Debug log
            # Keep status as "pending" for manual review
    else:
        print(f" REPORT NOT AUTO-VERIFIED: Rules failed - rule_status: {rule_status}, is_flagged: {is_flagged}")  # Debug log

    # Run hotspot auto-creation in background when criteria are met (no user intervention)
    background_tasks.add_task(run_hotspot_auto)
    
    # Auto-create cases if this report was verified and can form a cluster
    if report.verification_status == "verified":
        background_tasks.add_task(_check_and_create_auto_case, str(report.report_id))
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "report", "action": "created"})
    
    return report


def _build_report_response(r: Report, db: Optional[Session] = None, request_device_id: Optional[str] = None) -> ReportResponse:
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

    hotspots = []  # Hotspots relationship not available yet
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

    ml_prediction = resolve_ml_prediction_for_report(r)
    trust_factors = ml_prediction.explanation if ml_prediction else None
    trust_score = resolve_display_trust_score(r)
    if trust_score is not None:
        trust_score = float(trust_score)

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

    linked_case_id = None
    cr_links = list(getattr(r, "case_reports", None) or [])
    if cr_links:
        linked_case_id = cr_links[0].case_id

    # Parse community votes from feature_vector
    community_votes = {"real": 0, "false": 0, "unknown": 0}
    user_vote = None
    if getattr(r, "feature_vector", None) and isinstance(r.feature_vector, dict):
        votes_dict = r.feature_vector.get("community_votes", {})
        for dict_device_id, v in votes_dict.items():
            if str(v) in community_votes:
                community_votes[str(v)] += 1
            if request_device_id and str(dict_device_id) == str(request_device_id):
                user_vote = str(v)

    # Get device metadata and trust score
    device_metadata = getattr(r.device, "metadata_json", {}) if r.device else {}
    device_trust_score = getattr(r.device, "device_trust_score", None) if r.device else None
    total_reports = getattr(r.device, "total_reports", None) if r.device else None
    trusted_reports = getattr(r.device, "trusted_reports", None) if r.device else None

    return ReportResponse(
        report_id=r.report_id,
        report_number=getattr(r, "report_number", None),
        case_id=linked_case_id,
        device_id=r.device_id,
        incident_type_id=r.incident_type_id,
        description=r.description,
        latitude=r.latitude,
        longitude=r.longitude,
        gps_accuracy=getattr(r, "gps_accuracy", None),
        motion_level=getattr(r, "motion_level", None),
        movement_speed=getattr(r, "movement_speed", None),
        was_stationary=getattr(r, "was_stationary", None),
        reported_at=r.reported_at,
        rule_status=r.rule_status,
        priority=getattr(r, "priority", "medium"),  # Include calculated priority
        status=getattr(r, "status", None),
        verification_status=getattr(r, "verification_status", None),
        village_location_id=r.village_location_id,
        village_name=village_name,
        incident_type_name=r.incident_type.type_name if r.incident_type else None,
        evidence_count=len(evidence_files),
        evidence_preview=evidence_preview,
        trust_score=float(trust_score) if trust_score is not None else None,
        trust_factors=trust_factors,
        ml_prediction_label=resolve_ml_prediction_label_for_display(r),
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
        community_votes=community_votes,
        user_vote=user_vote,
        # Add device metadata fields
        metadata_json=device_metadata,
        device_trust_score=float(device_trust_score) if device_trust_score is not None else None,
        total_reports=total_reports,
        trusted_reports=trusted_reports,
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
            selectinload(Report.case_reports),
            # joinedload(Report.hotspots).joinedload(Hotspot.incident_type),  # Hotspots relationship not available yet
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
        selectinload(Report.case_reports),
        # joinedload(Report.hotspots).joinedload(Hotspot.incident_type),  # Hotspots relationship not available yet
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
    device_id: Optional[str] = Query(None, description="Device ID for 'my reports' (mobile). If omitted, auth required for all reports."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    rule_status: Optional[str] = Query(None, description="Filter by rule_status: pending, passed, flagged, rejected."),
    report_status: Optional[str] = Query(None, alias="status", description="Filter by report status: pending, verified, flagged, rejected. For list consistency, flagged includes rejected."),
    boundary_status: Optional[str] = Query(
        None,
        description="Filter by boundary status: out_of_boundary | in_boundary.",
    ),
    incident_type_id: Optional[int] = Query(None, description="Filter by incident type."),
    village_location_id: Optional[int] = Query(None, description="Filter by village/location."),
    sector_location_id: Optional[int] = Query(None, description="Filter by sector location id."),
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
        mobile_query = (
            db.query(Report)
            .options(
                joinedload(Report.device),
                joinedload(Report.incident_type),
                joinedload(Report.village_location),
                selectinload(Report.evidence_files),
                selectinload(Report.assignments),
                selectinload(Report.ml_predictions),
                selectinload(Report.case_reports),
            )
            .filter(Report.device_id == device_id)
        )
        if boundary_status == "out_of_boundary":
            mobile_query = mobile_query.filter(Report.flag_reason.like("out_of_musanze_boundary%"))
        elif boundary_status == "in_boundary":
            mobile_query = mobile_query.filter(
                or_(Report.flag_reason.is_(None), ~Report.flag_reason.like("out_of_musanze_boundary%"))
            )

        reports = mobile_query.order_by(Report.reported_at.desc()).all()
        return [_build_report_response(r, db, request_device_id=device_id) for r in reports]
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    query = db.query(Report).options(
        joinedload(Report.device),
        joinedload(Report.incident_type),
        joinedload(Report.village_location),
        selectinload(Report.evidence_files),
        # selectinload(Report.hotspots),  # Hotspots relationship not available yet
        selectinload(Report.assignments),
        selectinload(Report.ml_predictions),
        selectinload(Report.case_reports),
    )
    role = getattr(current_user, "role", None)

    # Officers see only reports assigned to them
    if role == "officer":
        query = query.join(Report.assignments).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
    # Supervisors are restricted to their own station's sector.
    elif role == "supervisor":
        supervisor_station_id = getattr(current_user, "station_id", None)
        if supervisor_station_id is None:
            raise HTTPException(
                status_code=403,
                detail="Supervisor station is not configured",
            )
        
        # Get station to find its sector location
        station = db.query(Station).filter(Station.station_id == supervisor_station_id).first()
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
            
            # Filter reports by location hierarchy (village_location_id in sector) + station assignments
            query = query.filter(
                or_(
                    Report.handling_station_id == supervisor_station_id,
                    Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                    ),
                    Report.village_location_id.in_(sector_location_ids)
                )
            )
        else:
            # Fallback: only station-based filtering
            query = query.filter(
                or_(
                    Report.handling_station_id == supervisor_station_id,
                    Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                    ),
                )
            )
    if rule_status:
        query = query.filter(Report.rule_status == rule_status)
    if report_status:
        if report_status == "flagged":
            query = query.filter(Report.status.in_(["flagged", "rejected"]))
        else:
            query = query.filter(Report.status == report_status)
    if boundary_status == "out_of_boundary":
        query = query.filter(Report.flag_reason.like("out_of_musanze_boundary%"))
    elif boundary_status == "in_boundary":
        query = query.filter(
            or_(Report.flag_reason.is_(None), ~Report.flag_reason.like("out_of_musanze_boundary%"))
        )
    if incident_type_id is not None:
        query = query.filter(Report.incident_type_id == incident_type_id)
    if village_location_id is not None:
        query = query.filter(Report.village_location_id == village_location_id)
    if sector_location_id is not None:
        # Villages can be direct children of sector or nested under cells in that sector.
        cell_ids = [
            row[0]
            for row in db.query(Location.location_id)
            .filter(
                Location.location_type == "cell",
                Location.parent_location_id == sector_location_id,
            )
            .all()
        ]
        village_q = db.query(Location.location_id).filter(
            Location.location_type == "village"
        )
        if cell_ids:
            village_q = village_q.filter(
                or_(
                    Location.parent_location_id == sector_location_id,
                    Location.parent_location_id.in_(cell_ids),
                )
            )
        else:
            village_q = village_q.filter(
                Location.parent_location_id == sector_location_id
            )
        sector_village_ids = [row[0] for row in village_q.all()]
        if not sector_village_ids:
            return ReportListResponse(items=[], total=0, limit=limit, offset=offset)
        query = query.filter(Report.village_location_id.in_(sector_village_ids))
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
        items=[_build_report_response(r, db, request_device_id=device_id) for r in reports],
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
        # Mobile: allow the device owner to view their own report,
        # and allow non-owners to view *eligible* reports for community confirmation.
        # This enables "nearby confirmations" where users can vote on other
        # devices' pending/under_review reports.
        report = (
            db.query(Report)
            .options(
                joinedload(Report.incident_type),
                joinedload(Report.evidence_files),
                joinedload(Report.device),
                selectinload(Report.ml_predictions),
            )
            .filter(Report.report_id == report_id)
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
                joinedload(Report.device),
                selectinload(Report.ml_predictions),
                joinedload(Report.assignments).joinedload(ReportAssignment.police_user),
                joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
            )
            .filter(Report.report_id == report_id)
            .first()
        )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # DEBUG: Check evidence files loading
    print(f"🔍 DEBUG: Report {report_id} evidence files:")
    print(f"   Raw evidence_files attribute: {getattr(report, 'evidence_files', 'NOT_FOUND')}")
    print(f"   Evidence files count: {len(report.evidence_files) if report.evidence_files else 0}")
    if report.evidence_files:
        for i, ef in enumerate(report.evidence_files, 1):
            print(f"     {i}. {ef.evidence_id} - {ef.file_type} - {ef.file_url}")
    else:
        print("   No evidence files found in query result")

    # Enforce mobile community visibility rules for non-owners.
    if device_id is not None and report.device_id != device_id:
        eligible = (
            getattr(report, "rule_status", None) == "passed"
            and not bool(getattr(report, "is_flagged", False))
            and getattr(report, "verification_status", None) in ("pending", "under_review")
        )
        if not eligible:
            raise HTTPException(status_code=403, detail="You can only view reports eligible for community confirmation")
    # Officers may only view reports assigned to them
    if device_id is None and current_user and getattr(current_user, "role", None) == "officer":
        assigned_to_me = any(
            a.police_user_id == current_user.police_user_id
            for a in (report.assignments or [])
        )
        if not assigned_to_me:
            raise HTTPException(status_code=403, detail="You can only view reports assigned to you")
    # Supervisors may only view reports within their station scope.
    if device_id is None and current_user and getattr(current_user, "role", None) == "supervisor":
        supervisor_station_id = getattr(current_user, "station_id", None)
        if supervisor_station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
        
        # Get station to find its sector location
        station = db.query(Station).filter(Station.station_id == supervisor_station_id).first()
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
            
            # Check if report is within supervisor's scope (station-based OR sector-based)
            in_station_scope = (
                report.handling_station_id == supervisor_station_id
                or any(
                    getattr(a.police_user, "station_id", None) == supervisor_station_id
                    for a in (report.assignments or [])
                )
                or report.village_location_id in sector_location_ids
            )
        else:
            # Fallback: only station-based filtering
            in_station_scope = (
                report.handling_station_id == supervisor_station_id
                or any(
                    getattr(a.police_user, "station_id", None) == supervisor_station_id
                    for a in (report.assignments or [])
                )
            )
        
        if not in_station_scope:
            raise HTTPException(
                status_code=403,
                detail="You can only view reports in your station or sector",
            )

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

    # Trust score and ML label: same resolution as list API (ML trust first, else device).
    trust_score = resolve_display_trust_score(report)
    context_tags_list = getattr(report, "context_tags", None) or []

    community_votes = {"real": 0, "false": 0, "unknown": 0}
    user_vote = None
    if getattr(report, "feature_vector", None) and isinstance(report.feature_vector, dict):
        votes_dict = report.feature_vector.get("community_votes", {})
        for dict_device_id, v in votes_dict.items():
            if str(v) in community_votes:
                community_votes[str(v)] += 1
            if device_id and str(dict_device_id) == str(device_id):
                user_vote = str(v)

    # Get device metadata and trust score
    device_metadata = getattr(report.device, "metadata_json", {}) if report.device else {}
    device_trust_score = getattr(report.device, "device_trust_score", None) if report.device else None
    total_reports = getattr(report.device, "total_reports", None) if report.device else None
    trusted_reports = getattr(report.device, "trusted_reports", None) if report.device else None

    return ReportDetailResponse(
        report_id=report.report_id,
        report_number=getattr(report, "report_number", None),
        device_id=report.device_id,
        incident_type_id=report.incident_type_id,
        description=report.description,
        latitude=report.latitude,
        longitude=report.longitude,
        gps_accuracy=getattr(report, "gps_accuracy", None),
        motion_level=getattr(report, "motion_level", None),
        movement_speed=getattr(report, "movement_speed", None),
        was_stationary=getattr(report, "was_stationary", None),
        reported_at=report.reported_at,
        rule_status=report.rule_status,
        priority=getattr(report, "priority", "medium"),  # Include calculated priority
        status=report.status,
        verification_status=report.verification_status,
        village_location_id=report.village_location_id,
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        trust_score=float(trust_score) if trust_score is not None else None,
        ml_prediction_label=resolve_ml_prediction_label_for_display(report),
        context_tags=context_tags_list,
        is_flagged=getattr(report, "is_flagged", None),
        flag_reason=getattr(report, "flag_reason", None),
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
                blur_score=float(ef.blur_score) if getattr(ef, "blur_score", None) is not None else None,
                tamper_score=float(ef.tamper_score) if getattr(ef, "tamper_score", None) is not None else None,
                quality_label=ef.quality_label.value if ef.quality_label else None,
            )
            for ef in report.evidence_files
        ],
        assignments=assignment_list,
        reviews=review_list,
        community_votes=community_votes,
        user_vote=user_vote,
        # Add device metadata fields
        metadata_json=device_metadata,
        device_trust_score=float(device_trust_score) if device_trust_score is not None else None,
        total_reports=total_reports,
        trusted_reports=trusted_reports,
    )
    
    # DEBUG: Check what's being returned
    print(f"🔍 DEBUG: Returning response with evidence files:")
    print(f"   Evidence files in response: {len(response.evidence_files) if response.evidence_files else 0}")
    if response.evidence_files:
        for i, ef in enumerate(response.evidence_files, 1):
            print(f"     {i}. {ef.evidence_id} - {ef.file_type} - {ef.file_url}")
    
    return response


@router.post("/{report_id}/reviews", response_model=ReviewResponse, status_code=201)
def add_review(
    report_id: UUID,
    body: ReviewCreate,
    request: Request,
    background_tasks: BackgroundTasks,
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

    # Ensure ML analysis stage exists before police review decisions.
    from app.models.ml_prediction import MLPrediction

    latest_pred = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if latest_pred is None:
        try:
            device = db.query(Device).filter(Device.device_id == report.device_id).first()
            evidence_count = (
                db.query(EvidenceFile)
                .filter(EvidenceFile.report_id == report.report_id)
                .count()
            )
            if device is not None:
                score_report_credibility(db, report, device, evidence_count)
        except Exception:
            pass

    # Update report verification and status when police confirms or rejects
    now_utc = datetime.now(timezone.utc)

    # Update ML prediction based on police review (human oversight)
    decision = (body.decision or "").strip().lower()

    if decision == "confirmed":
        # Police confirmed report - update ML to learn from this
        report.verified_at = now_utc
        report.verified_by = current_user.police_user_id  # Add who verified it
        report.rule_status = "passed"
        report.status = "verified"
        report.verification_status = "verified"
        report.is_flagged = False
        report.flag_reason = None
        
        # Get ML max trust score from config
        from app.database import SessionLocal
        from app.models.system_config import SystemConfig
        
        db_config = SessionLocal()
        try:
            max_trust_config = db_config.query(SystemConfig).filter(
                SystemConfig.config_key == 'ml.max_trust_score'
            ).first()
            max_trust_score = float(max_trust_config.config_value.get('value', 95.0)) if max_trust_config else 95.0
        finally:
            db_config.close()
        
        # Update ML prediction to reflect human confirmation
        existing_ml = db.query(MLPrediction).filter(
            MLPrediction.report_id == report_id
        ).order_by(MLPrediction.evaluated_at.desc()).first()
        
        if existing_ml:
            # Human confirmation increases trust score and sets label to likely_real
            existing_ml.trust_score = Decimal(str(max_trust_score))
            existing_ml.prediction_label = "likely_real"
            existing_ml.confidence = Decimal("0.95")
            existing_ml.is_final = True
            print(f"Updated ML prediction based on police confirmation: trust_score={max_trust_score}%, label=likely_real")  # Debug log
        else:
            # Create new ML prediction if none exists
            new_ml = MLPrediction(
                prediction_id=uuid4(),
                report_id=report_id,
                trust_score=Decimal(str(max_trust_score)),
                prediction_label="likely_real",
                confidence=Decimal("0.95"),
                model_type="human_override",
                is_final=True,
                evaluated_at=now_utc
            )
            db.add(new_ml)
            print(f"Created new ML prediction based on police confirmation: trust_score={max_trust_score}%, label=likely_real")  # Debug log
        
        # Update device trust score based on successful human confirmation
        if hasattr(report, "device") and report.device and hasattr(report.device, "device_trust_score"):
            current_device_score = float(report.device.device_trust_score) if report.device.device_trust_score else 50.0
            # Increase device trust score but cap at 100
            new_device_score = min(100.0, current_device_score + 5.0)
            report.device.device_trust_score = Decimal(str(new_device_score))
            print(f"Updated device trust score: {current_device_score:.1f}% → {new_device_score:.1f}%")  # Debug log
        
        # Update trusted_reports count
        if hasattr(report.device, "trusted_reports"):
            report.device.trusted_reports = (report.device.trusted_reports or 0) + 1
        
    elif decision == "rejected":
        # Police rejected report - update ML to learn from this
        report.verified_at = now_utc
        report.verified_by = current_user.police_user_id  # Add who verified it
        report.rule_status = "rejected"
        report.status = "rejected"
        report.verification_status = "rejected"
        report.is_flagged = True
        report.flag_reason = body.review_note or "rejected_by_reviewer"
        
        # Get ML min trust score from config
        from app.database import SessionLocal
        from app.models.system_config import SystemConfig
        
        db_config = SessionLocal()
        try:
            min_trust_config = db_config.query(SystemConfig).filter(
                SystemConfig.config_key == 'ml.min_trust_score'
            ).first()
            min_trust_score = float(min_trust_config.config_value.get('value', 5.0)) if min_trust_config else 5.0
        finally:
            db_config.close()
        
        # Update ML prediction to reflect human rejection
        existing_ml = db.query(MLPrediction).filter(
            MLPrediction.report_id == report_id
        ).order_by(MLPrediction.evaluated_at.desc()).first()
        
        if existing_ml:
            # Human rejection decreases trust score and sets label to fake
            existing_ml.trust_score = Decimal(str(min_trust_score))
            existing_ml.prediction_label = "fake"
            existing_ml.confidence = Decimal("0.95")  # High confidence in this assessment
            existing_ml.is_final = True
            print(f"Updated ML prediction based on police rejection: trust_score={min_trust_score}%, label=fake")  # Debug log
        else:
            # Create new ML prediction if none exists
            new_ml = MLPrediction(
                prediction_id=uuid4(),
                report_id=report_id,
                trust_score=Decimal(str(min_trust_score)),
                prediction_label="fake",
                confidence=Decimal("0.95"),
                model_type="human_override",
                is_final=True,
                evaluated_at=now_utc
            )
            db.add(new_ml)
            print(f"Created new ML prediction based on police rejection: trust_score={min_trust_score}%, label=fake")  # Debug log
        
        # Update device trust score based on human rejection
        if hasattr(report, "device") and report.device and hasattr(report.device, "device_trust_score"):
            current_device_score = float(report.device.device_trust_score) if report.device.device_trust_score else 50.0
            # Decrease device trust score but don't go below 0
            new_device_score = max(0.0, current_device_score - 10.0)
            report.device.device_trust_score = Decimal(str(new_device_score))
            print(f"Updated device trust score: {current_device_score:.1f}% → {new_device_score:.1f}%")  # Debug log
        
        # Update flagged_reports count
        if hasattr(report.device, "flagged_reports"):
            report.device.flagged_reports = (report.device.flagged_reports or 0) + 1
        
    else:
        # investigation
        report.verification_status = "under_review"
        if body.review_note:
            report.flag_reason = body.review_note

    existing_review = (
        db.query(PoliceReview)
        .filter(
            PoliceReview.report_id == report_id,
            PoliceReview.police_user_id == current_user.police_user_id,
        )
        .first()
    )

    if existing_review:
        review = existing_review
        review.decision = body.decision
        review.review_note = body.review_note
        review.reviewed_at = now_utc
    else:
        review = PoliceReview(
            review_id=uuid4(),
            report_id=report_id,
            police_user_id=current_user.police_user_id,
            decision=body.decision,
            review_note=body.review_note,
        )
        db.add(review)
    # Get client IP and user agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    try:
        db.commit()
        
        # Log the successful action
        log_action(
            db,
            "report_reviewed",
            actor_type="police_user",
            actor_id=current_user.police_user_id,
            entity_type="report",
            entity_id=str(report_id),
            action_details={
                "decision": body.decision,
                "updated_existing_review": bool(existing_review),
            },
            ip_address=client_ip,
            user_agent=user_agent,
            success=True,
        )
    except Exception as e:
        db.rollback()
        # Check if it's a duplicate key error
        if "duplicate key value violates unique constraint" in str(e) and "police_reviews_report_id_police_user_id_key" in str(e):
            raise HTTPException(status_code=400, detail="You have already reviewed this report")
        raise

    # Create notifications for report review
    from app.api.v1.notifications import create_role_notifications, create_notification
    
    # Notify admins and supervisors about the review decision
    decision_text = body.decision.upper()
    create_role_notifications(
        db,
        title=f"Report {decision_text}",
        message=f"Report {report.report_number} has been {body.decision} by {current_user.first_name} {current_user.last_name}.",
        notif_type="report",
        related_entity_type="report",
        related_entity_id=str(report_id),
        target_roles=["admin", "supervisor"],
        target_location_id=report.village_location_id,
        exclude_user_id=current_user.police_user_id,
    )
    
    # If there was an assigned officer, notify them about the review
    if hasattr(report, 'assignments') and report.assignments:
        for assignment in report.assignments:
            if assignment.police_user_id != current_user.police_user_id:
                create_notification(
                    db,
                    police_user_id=assignment.police_user_id,
                    title=f"Assigned Report {decision_text}",
                    message=f"Report {report.report_number} you were assigned has been {body.decision}.",
                    notif_type="report",
                    related_entity_type="report",
                    related_entity_id=str(report_id),
                )
    db.commit()
    db.refresh(review)
    reviewer_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "report", "action": "reviewed"})

    return ReviewResponse(
        review_id=review.review_id,
        report_id=review.report_id,
        police_user_id=review.police_user_id,
        decision=review.decision,
        review_note=review.review_note,
        reviewed_at=review.reviewed_at,
        reviewer_name=reviewer_name,
    )


@router.get("/{report_id}/reviews", response_model=List[ReviewResponse])
def get_reviews(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get all reviews for a report."""
    from sqlalchemy.orm import joinedload
    
    report = (
        db.query(Report)
        .options(joinedload(Report.police_reviews).joinedload(PoliceReview.police_user))
        .filter(Report.report_id == report_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    review_list = []
    if getattr(report, "police_reviews", None):
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
    
    return review_list


@router.post("/{report_id}/assign", response_model=AssignmentResponse, status_code=201)
def assign_report(
    report_id: UUID,
    body: AssignCreate,
    request: Request,
    background_tasks: BackgroundTasks,
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
        assignment_note=body.assignment_note,
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
    # Get client IP and user agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_action(
        db,
        "report_assigned",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id=str(report_id),
        action_details={"assigned_to": body.police_user_id, "priority": body.priority},
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    db.commit()
    db.refresh(assignment)
    officer_name = f"{officer.first_name or ''} {officer.last_name or ''}".strip() or officer.email
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "report", "action": "assigned"})

    return AssignmentResponse(
        assignment_id=assignment.assignment_id,
        report_id=assignment.report_id,
        police_user_id=assignment.police_user_id,
        status=assignment.status,
        priority=assignment.priority,
        assignment_note=assignment.assignment_note,
        assigned_at=assignment.assigned_at,
        completed_at=assignment.completed_at,
        officer_name=officer_name,
    )


@router.post("/admin/purge-outside-musanze")
def purge_outside_musanze_reports_admin(
    request: Request,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Admin-only cleanup: remove reports outside covered Musanze village polygons."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    deleted_reports, recomputed_hotspots = _purge_outside_musanze_reports(
        db,
        recompute_hotspots=True,
    )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_action(
        db,
        "purge_outside_musanze_reports",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id="bulk",
        action_details={
            "deleted_reports": deleted_reports,
            "recomputed_hotspots": recomputed_hotspots,
        },
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    db.commit()

    return {
        "status": "ok",
        "deleted_reports": deleted_reports,
        "recomputed_hotspots": recomputed_hotspots,
    }


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
    request: Request = None,
):
    """Upload evidence file (photo/video) for a report.

    Mobile: pass device_id to add evidence to your own report (only within evidence_add_window_hours after submit).
    Police dashboard: no device_id; requires auth (future use).
    """
    print(f"Evidence upload - report_id: {report_id}, device_id: {device_id}, filename: {file.filename}")  # Debug log
    
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
        print(f"Device ID validation - report.device_id: {report.device_id}, device_id_uuid: {device_id_uuid}")  # Debug log
        if str(report.device_id) != str(device_id_uuid):
            print("Device ID mismatch - raising 403")  # Debug log
            raise HTTPException(status_code=403, detail="You can only add evidence to your own report")
        window_hours = getattr(settings, "evidence_add_window_hours", 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
        print(f"Time window check - reported_at: {reported_at}, cutoff: {cutoff}, window_hours: {window_hours}")  # Debug log
        if reported_at < cutoff:
            print("Time window exceeded - raising 400")  # Debug log
            raise HTTPException(
                status_code=400,
                detail=f"You can add evidence only within {window_hours} hours of submitting the report",
            )
    elif current_user is None:
        print("No device_id and no current_user - raising 400")  # Debug log
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
    # Conservative check: filename + optional image metadata.
    is_screenshot = is_likely_screenshot_or_screen_recording(
        filename=file.filename,
        image_bytes=content if is_image else None,
    )
    if is_screenshot:
        _log_blocked_attempt(
            db,
            action_type="evidence_blocked_screenshot",
            request=request,
            device=report.device,
            report_id=str(report.report_id),
            details={
                "filename": file.filename,
                "file_type": file_type,
                "reason": "screenshot_or_screen_recording_detected",
            },
        )
        raise HTTPException(
            status_code=400,
            detail="Screenshots and screen recordings are not allowed. Please upload a photo, audio, or video taken with your camera or recorder.",
        )

    # Prevent evidence reuse from the same device (common fake-evidence pattern).
    content_hash = hashlib.sha256(content).hexdigest()
    if device_id_uuid is not None:
        duplicate_evidence = (
            db.query(EvidenceFile.evidence_id)
            .join(Report, EvidenceFile.report_id == Report.report_id)
            .filter(
                Report.device_id == device_id_uuid,
                EvidenceFile.perceptual_hash == content_hash,
            )
            .first()
        )
        if duplicate_evidence:
            _log_blocked_attempt(
                db,
                action_type="evidence_blocked_reuse",
                request=request,
                device=report.device,
                report_id=str(report.report_id),
                details={
                    "filename": file.filename,
                    "file_type": file_type,
                    "reason": "duplicate_evidence_hash",
                },
            )
            raise HTTPException(
                status_code=409,
                detail="This evidence appears to have been reused from a previous report on this device. Please upload original evidence.",
            )

    # Cloudinary upload if configured, otherwise save locally
    print(f"Cloudinary enabled: {_CLOUDINARY_ENABLED}")  # Debug log
    print(f"Cloudinary config - cloud_name: {settings.cloudinary_cloud_name}, api_key configured: {bool(settings.cloudinary_api_key)}")  # Debug log
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
        perceptual_hash=content_hash,
        media_latitude=final_lat,
        media_longitude=final_lon,
        captured_at=final_captured_at,
        is_live_capture=is_live_capture,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    # Re-run AI-enhanced rule-based verification (evidence count changed)
    report_after = db.query(Report).filter(Report.report_id == report.report_id).first()
    if report_after:
        evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_after.report_id).count()
        print(f"Re-applying AI-enhanced rules after evidence upload - evidence_count: {evidence_count}")  # Debug log
        
        # Get ML prediction if available
        ml_prediction = None
        if hasattr(report_after, 'ml_predictions') and report_after.ml_predictions:
            ml_prediction = max(report_after.ml_predictions, key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc))
            print(f"Using ML prediction for re-evaluation: {ml_prediction.prediction_label}, trust_score: {ml_prediction.trust_score}")  # Debug log
        
        # Apply AI-enhanced rules
        from app.core.report_priority import apply_ai_enhanced_rules, calculate_report_priority
        rule_status, is_flagged, flag_reason = apply_ai_enhanced_rules(
            report_after, evidence_count, ml_prediction, db
        )
        print(f"AI-enhanced rule result after evidence upload - rule_status: {rule_status}, is_flagged: {is_flagged}, flag_reason: {flag_reason}")  # Debug log
        
        # Recalculate priority
        priority = calculate_report_priority(report_after, ml_prediction, evidence_count, db)
        print(f"Recalculated priority after evidence upload: {priority}")  # Debug log
        
        report_after.rule_status = rule_status
        report_after.is_flagged = is_flagged
        report_after.priority = priority  # Save recalculated priority
        if is_flagged and flag_reason:
            report_after.flag_reason = flag_reason
        
        # Set verification_status based on AI results
        review_reasons = {
            "ai_suspicious_review",
            "ai_uncertain_review",
            "incident_description_mismatch",
            "evidence_time_mismatch",
            "stale_live_capture_timestamp",
            "device_burst_reporting",
            "duplicate_description_recent",
        }
        if flag_reason in review_reasons:
            report_after.verification_status = "under_review"
            print(f"Rule/AI review reason after evidence upload ({flag_reason}) - setting verification_status to under_review")  # Debug log
        
        # FIXED: Auto-verify if AI-enhanced rules pass and not flagged, using trust_score threshold
        ai_safe = True
        ml_trust_ok = True
        
        if ml_prediction:
            if ml_prediction.prediction_label in ["fake", "suspicious", "uncertain"]:
                ai_safe = False
                print(f"AI marked report as {ml_prediction.prediction_label} - not auto-verifying after evidence upload")  # Debug log
            
            # Use trust_score threshold (70%) for consistency
            trust_score = float(ml_prediction.trust_score) if ml_prediction.trust_score else 0
            if trust_score < 70.0:
                ml_trust_ok = False
                print(f"ML trust score too low ({trust_score:.1f}% < 70%) - not auto-verifying after evidence upload")  # Debug log
        
        if rule_status == "passed" and not is_flagged and ai_safe and ml_trust_ok and report_after.verification_status != "under_review":
            report_after.status = "verified"
            report_after.verification_status = "verified"
            print("Report auto-verified after evidence upload with AI safety check")  # Debug log
        db.commit()
    
    await manager.broadcast({"type": "refresh_data", "entity": "report", "action": "evidence_added"})
    
    return {"evidence_id": str(evidence.evidence_id), "file_url": file_url}
@router.post("/{report_id}/confirm")
def add_community_confirmation(
    report_id: UUID,
    body: CommunityVoteRequest,
    db: Session = Depends(get_db),
):
    """
    Allow community users to vote on a report to bridge directly into the credibility scoring system.
    """
    if body.vote.lower() not in ["real", "false", "unknown"]:
        raise HTTPException(status_code=400, detail="vote must be 'real', 'false', or 'unknown'")

    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    device_id_str = str(body.device_id).strip()
    if not device_id_str:
        raise HTTPException(status_code=400, detail="device_id required")
        
    if str(report.device_id) == device_id_str:
        raise HTTPException(status_code=400, detail="You cannot vote on your own report")

    # Access feature_vector safely
    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        fv = {}
        
    votes = fv.get("community_votes", {})
    if not isinstance(votes, dict):
        votes = {}
        
    # Apply vote
    votes[device_id_str] = body.vote.lower()
    fv["community_votes"] = votes
    
    # Must explicitly set it for SQLAlchemy JSONB mutation
    report.feature_vector = fv 
    
    db.commit()
    db.refresh(report)
    
    device = report.device
    # Recalculate credibility score since community votes changed
    evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).count()
    score_report_credibility(db, report, device, evidence_count)
    _ensure_fallback_ml_prediction_if_missing(db, report)
    update_device_ml_aggregates(db, device)

    # Persist updated ML prediction + device aggregates so the response includes fresh trust.
    db.commit()
    db.refresh(report)

    # Update report lifecycle state based on the new ML trust score
    try:
        from app.models.ml_prediction import MLPrediction
        latest_ml = (
            db.query(MLPrediction)
            .filter(MLPrediction.report_id == report_id)
            .order_by(MLPrediction.evaluated_at.desc())
            .first()
        )

        if latest_ml:
            trust_score = float(latest_ml.trust_score) if latest_ml.trust_score is not None else 0.0
            prediction_label = (latest_ml.prediction_label or "").lower()

            # Get ML thresholds from system config
            from app.database import SessionLocal
            from app.models.system_config import SystemConfig
            
            db = SessionLocal()
            try:
                auto_verify_config = db.query(SystemConfig).filter(
                    SystemConfig.config_key == 'ml.auto_verification_threshold'
                ).first()
                under_review_config = db.query(SystemConfig).filter(
                    SystemConfig.config_key == 'ml.under_review_threshold'
                ).first()
                
                auto_verify_threshold = float(auto_verify_config.config_value.get('value', 70.0)) if auto_verify_config else 70.0
                under_review_threshold = float(under_review_config.config_value.get('value', 45.0)) if under_review_config else 45.0
            finally:
                db.close()

            # Do not override police decisions; only move pending/under_review reports.
            if report.verification_status in ("pending", "under_review"):
                if report.rule_status == "passed" and not bool(getattr(report, "is_flagged", False)) and prediction_label == "likely_real" and trust_score >= auto_verify_threshold:
                    report.status = "verified"
                    report.verification_status = "verified"
                    report.is_flagged = False
                    report.flag_reason = None
                elif trust_score >= under_review_threshold:
                    report.status = "pending"
                    report.verification_status = "under_review"
                else:
                    report.status = "rejected"
                    report.verification_status = "rejected"
                    report.is_flagged = True
                    if not report.flag_reason:
                        report.flag_reason = "community_low_trust"

                db.add(report)
                db.commit()
                db.refresh(report)
    except Exception:
        # Best-effort only: community vote must not fail if state update is blocked
        pass
    
    return _build_report_response(report, db, request_device_id=device_id_str)


@router.get("/nearby-confirmations", response_model=List[ReportResponse])
def list_nearby_confirmations(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_meters: int = Query(600, ge=50, le=5000),
    limit: int = Query(10, ge=1, le=30),
    device_id: Optional[str] = Query(None),
    device_hash: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return candidate reports for community confirmation:
    - in radius around the provided GPS coords
    - not belonging to the requester device
    - rule_status passed, and verification_status not yet verified/rejected
    """
    if not device_id and not device_hash:
        raise HTTPException(status_code=400, detail="device_id or device_hash is required")

    from math import cos, radians
    from app.models.device import Device

    device: Device | None = None
    if device_id:
        device = db.query(Device).filter(Device.device_id == device_id).first()
    if device is None and device_hash:
        device = db.query(Device).filter(Device.device_hash == device_hash).first()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    lat = float(latitude)
    lon = float(longitude)

    # Bounding box approximation (then refine with haversine in python)
    lat_delta = radius_meters / 111000.0
    lon_delta = radius_meters / (111000.0 * max(0.1, cos(radians(lat))))

    from_dt = datetime.now(timezone.utc) - timedelta(days=3)

    q = (
        db.query(Report)
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.device),
            joinedload(Report.ml_predictions),
            selectinload(Report.case_reports),
        )
        .filter(
            Report.is_flagged == False,
            Report.rule_status == "passed",
            Report.verification_status.in_(["pending", "under_review"]),
            Report.reported_at >= from_dt,
            Report.latitude.between(lat - lat_delta, lat + lat_delta),
            Report.longitude.between(lon - lon_delta, lon + lon_delta),
            Report.device_id != device.device_id,
        )
        .order_by(Report.reported_at.desc())
        .limit(limit * 3)
    )

    import math

    def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        a = math.sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * math.sin(d_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    candidates = q.all()
    enriched: list[tuple[float, Report]] = []
    for r in candidates:
        if r.latitude is None or r.longitude is None:
            continue
        dist = haversine_m(lat, lon, float(r.latitude), float(r.longitude))
        if dist <= radius_meters:
            enriched.append((dist, r))

    enriched.sort(key=lambda x: (x[0], (x[1].reported_at or datetime.min.replace(tzinfo=timezone.utc))))
    selected = [rr for _, rr in enriched[:limit]]

    return [_build_report_response(r, db, request_device_id=str(device.device_id)) for r in selected]


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    device_id: Optional[str] = Query(None, description="Device ID of the original reporter"),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
):
    """
    Allow a user or admin to delete a report. Primary use case: rollback if evidence upload fails.
    """
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    is_authorized = False
    
    # Check if admin/supervisor
    if current_user and current_user.role in ["admin", "supervisor"]:
        is_authorized = True
        
    # Check if original creator
    if device_id and str(report.device_id) == str(device_id):
        # Only allow if it's still pending OR was very recently created (rollback window)
        now = datetime.now(timezone.utc)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
            
        age_seconds = (now - reported_at).total_seconds()
        
        if report.rule_status == "pending" or age_seconds < 300:
            is_authorized = True

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized to delete this report")

    db.delete(report)
    db.commit()
    return {}


def _check_and_create_auto_case(report_id: str):
    """Background task to check if a verified report can form a new case using proper location-based clustering"""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report or report.verification_status != "verified":
            return
        
        # Check if report is already in a case
        from app.models.case_reports import case_reports_table
        existing_case = db.query(case_reports_table).filter(
            case_reports_table.c.report_id == report_id
        ).first()
        
        if existing_case:
            return
        
        # Get clustering parameters from system config
        from app.models.system_config import SystemConfig
        dbscan_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.epsilon'
        ).first()
        min_samples_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.min_samples'
        ).first()
        
        # Use configured values or defaults
        cluster_radius_meters = 200  # Default 200m from system config
        min_reports_threshold = 3   # Default from system config
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 200)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 3)
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # Strategy 1: Cluster by same village/location (preferred)
        village_reports = []
        if report.village_location_id:
            village_reports = db.query(Report).filter(
                Report.incident_type_id == report.incident_type_id,
                Report.verification_status == "verified",
                Report.village_location_id == report.village_location_id,
                Report.report_id != report_id,
                ~Report.report_id.in_(
                    db.query(case_reports_table.c.report_id).distinct()
                )
            ).all()
            
            # Add the current report
            village_reports.insert(0, report)
            
            # Create case if enough reports in same village
            if len(village_reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, village_reports)
                if case_stats['cases_created'] > 0:
                    print(f"Auto-created village-based case {case_stats['case_number']} with {len(village_reports)} reports in village {report.village_location_id}")
                    return
        
        # Strategy 2: Geographic clustering using GPS coordinates (fallback)
        from math import radians, cos, sin, asin, sqrt
        
        def calculate_distance(lat1, lon1, lat2, lon2):
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c  # Returns distance in kilometers
        
        # Find nearby reports using GPS coordinates
        nearby_reports = db.query(Report).filter(
            Report.incident_type_id == report.incident_type_id,
            Report.verification_status == "verified",
            Report.report_id != report_id,
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            )
        ).all()
        
        # Filter by geographic proximity
        clustered_reports = [report]
        for other_report in nearby_reports:
            distance = calculate_distance(
                report.latitude, report.longitude,
                other_report.latitude, other_report.longitude
            )
            if distance <= cluster_radius_km:  # Use configured radius
                clustered_reports.append(other_report)
        
        # Create case if enough reports geographically clustered
        if len(clustered_reports) >= min_reports_threshold:
            case_stats = _create_case_from_reports(db, clustered_reports)
            if case_stats['cases_created'] > 0:
                print(f"Auto-created geo-clustered case {case_stats['case_number']} with {len(clustered_reports)} reports within {cluster_radius_meters}m")
    
    except Exception as e:
        print(f"Error in auto-case creation for report {report_id}: {e}")
    finally:
        db.close()

def _assign_officer_to_case_based_on_location(db: Session, case_lat: float, case_lon: float) -> Optional[int]:
    try:
        from app.models.station import Station
        from app.models.police_user import PoliceUser
        from app.models.case import Case
        from math import radians, cos, sin, asin, sqrt
        from sqlalchemy import func

        def calculate_distance(lat1, lon1, lat2, lon2):
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                return float('inf')
            lat1, lon1, lat2, lon2 = map(radians, map(float, [lat1, lon1, lat2, lon2]))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c

        stations = db.query(Station).filter(Station.is_active == True).all()
        if not stations:
            return None

        ranked_stations = sorted(stations, key=lambda s: calculate_distance(case_lat, case_lon, s.latitude, s.longitude))

        for station in ranked_stations:
            officers = db.query(PoliceUser).filter(
                PoliceUser.is_active == True,
                PoliceUser.role == 'officer',
                PoliceUser.station_id == station.station_id
            ).all()

            if officers:
                officer_ids = [o.police_user_id for o in officers]
                case_counts = db.query(Case.assigned_to_id, func.count(Case.case_id)).filter(
                    Case.assigned_to_id.in_(officer_ids),
                    Case.status != 'closed'
                ).group_by(Case.assigned_to_id).all()
                
                count_dict = dict(case_counts)
                selected_officer = min(officers, key=lambda o: count_dict.get(o.police_user_id, 0))
                return selected_officer.police_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error assigning officer to case: {e}")
        return None

def _create_case_from_reports(db: Session, reports: List[Report]) -> Dict[str, int]:
    """Create a case from a cluster of reports"""
    stats = {'cases_created': 0}
    
    try:
        from app.models.case import Case, CaseReport
        case_reports_table = CaseReport.__table__
        
        report = reports[0]  # Use first report as reference
        case_count = db.query(Case).count()
        case_number = f"CASE-{datetime.now().year}-{case_count + 1:04d}"
        
        high_priority_count = sum(1 for r in reports if r.priority == 'high')
        priority = 'high' if high_priority_count >= 2 else 'medium'
        
        case_lat = sum(r.latitude for r in reports) / len(reports)
        case_lon = sum(r.longitude for r in reports) / len(reports)
        officer_id = _assign_officer_to_case_based_on_location(db, float(case_lat), float(case_lon))
        
        case = Case(
            case_id=uuid4(),
            case_number=case_number,
            title=f"Incident Type {report.incident_type_id} case - Multiple Reports",
            description=f"Auto-generated case from {len(reports)} verified reports",
            incident_type_id=report.incident_type_id,
            priority=priority,
            status='open',
            assigned_to_id=officer_id,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            report_count=len(reports),
            location_id=report.location_id,
            latitude=case_lat,
            longitude=case_lon
        )
        
        db.add(case)
        db.flush()
        
        # Link reports to case
        for report in reports:
            db.execute(
                case_reports_table.insert().values(
                    case_id=case.case_id,
                    report_id=report.report_id,
                    added_at=datetime.now(timezone.utc)
                )
            )
        
        db.commit()
        stats['cases_created'] += 1
        print(f"Created auto-case {case.case_number} with {len(reports)} reports")
        
    except Exception as e:
        print(f"Error creating case from reports: {e}")
    
    return stats


def _create_auto_cases(db: Session) -> Dict[str, int]:
    """Automatically create cases from verified reports using proper location-based clustering"""
    
    stats = {'cases_created': 0}
    
    try:
        from app.models.case import Case, CaseReport
        case_reports_table = CaseReport.__table__
        
        # Get clustering parameters from system config
        from app.models.system_config import SystemConfig
        dbscan_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.epsilon'
        ).first()
        min_samples_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.min_samples'
        ).first()
        
        # Use configured values or defaults
        cluster_radius_meters = 200  # Default 200m from system config
        min_reports_threshold = 3   # Default from system config
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 200)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 3)
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # Strategy 1: Cluster by village/location (preferred)
        village_clusters = {}
        verified_reports = db.query(Report).filter(
            Report.verification_status == 'verified',
            Report.status == 'verified',
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            )
        ).all()
        
        logger.info(f"Found {len(verified_reports)} verified reports available for case creation")
        
        # Group by village and incident type
        for report in verified_reports:
            if report.village_location_id:
                village_key = f"{report.village_location_id}_{report.incident_type_id}"
                if village_key not in village_clusters:
                    village_clusters[village_key] = []
                village_clusters[village_key].append(report)
        
        # Create cases for village-based clusters
        for village_key, reports in village_clusters.items():
            if len(reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, reports)
                stats['cases_created'] += case_stats['cases_created']
                village_id, incident_type_id = village_key.split('_')
                logger.info(f"Created village-based case for village {village_id}, incident type {incident_type_id}")
        
        # Strategy 2: Geographic clustering for reports without village assignment
        unassigned_reports = [r for r in verified_reports if not r.village_location_id]
        if len(unassigned_reports) >= min_reports_threshold:
            # Group by incident type for geographic clustering
            by_incident_type = {}
            for report in unassigned_reports:
                incident_type_id = report.incident_type_id
                if incident_type_id not in by_incident_type:
                    by_incident_type[incident_type_id] = []
                by_incident_type[incident_type_id].append(report)
            
            # Apply geographic clustering
            from math import radians, cos, sin, asin, sqrt
            
            def calculate_distance(lat1, lon1, lat2, lon2):
                lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                return 6371 * c
            
            for incident_type_id, type_reports in by_incident_type.items():
                if len(type_reports) < min_reports_threshold:
                    continue
                
                # Find geographic clusters
                processed = set()
                for report in type_reports:
                    if report.report_id in processed:
                        continue
                        
                    cluster = [report]
                    processed.add(report.report_id)
                    
                    for other_report in type_reports:
                        if other_report.report_id in processed:
                            continue
                            
                        distance = calculate_distance(
                            report.latitude, report.longitude,
                            other_report.latitude, other_report.longitude
                        )
                        
                        if distance <= cluster_radius_km:  # Use configured radius
                            cluster.append(other_report)
                            processed.add(other_report.report_id)
                    
                    # Create case if cluster has enough reports
                    if len(cluster) >= min_reports_threshold:
                        case_stats = _create_case_from_reports(db, cluster)
                        stats['cases_created'] += case_stats['cases_created']
                        logger.info(f"Created geo-clustered case for incident type {incident_type_id} within {cluster_radius_meters}m")
        
        if stats['cases_created'] > 0:
            db.commit()
        return stats
        
    except Exception as e:
        logger.error(f"Auto-case creation error: {e}")
        return stats
        db.commit()
    
    return {"message": "Vote recorded", "vote": body.vote.lower()}
