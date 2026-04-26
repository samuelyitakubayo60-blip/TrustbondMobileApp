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

from app.services.evidence_analysis import evidence_analysis_service

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
from app.core.report_rules import (
    apply_rule_based_status, 
    is_likely_screenshot_or_screen_recording,
    enhanced_screenshot_detection,
    analyze_file_timing,
    validate_evidence_source,
    enhanced_screen_recording_detection,
    validate_location_consistency
)
from app.core.report_review import (
    needs_police_review_clause,
    resolve_ml_prediction_for_report,
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
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)

def _process_report_background(
    report_id: str,
    device_id: str,
    evidence_count: int,
    evidence_metadata_list: List[dict]
):
    """Background task to process heavy verification without blocking response."""
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        device = db.query(Device).filter(Device.device_id == device_id).first()
        
        if not report or not device:
            logger.error(f"Background processing failed: report {report_id} or device {device_id} not found")
            return
        
        # 1. Enhanced evidence verification
        verification_issues = []
        for evidence_meta in evidence_metadata_list:
            try:
                # Screenshot detection
                screenshot_result = enhanced_screenshot_detection(
                    filename=evidence_meta["file_url"].split('/')[-1],
                    file_path=evidence_meta["file_url"]
                )
                if screenshot_result["is_screenshot"]:
                    verification_issues.append(f"Screenshot detected: {screenshot_result['details']}")
            except Exception as e:
                logger.warning(f"Screenshot detection failed: {e}")
            
            try:
                # File timing analysis
                timing_result = analyze_file_timing(
                    file_path=evidence_meta["file_url"],
                    file_created_at=evidence_meta.get("captured_at")
                )
                if timing_result["is_suspicious"]:
                    verification_issues.append(f"Suspicious file timing: {timing_result['suspicious_reasons']}")
            except Exception as e:
                logger.warning(f"Timing analysis failed: {e}")
            
            try:
                # Evidence source validation
                source_result = validate_evidence_source(
                    filename=evidence_meta["file_url"].split('/')[-1],
                    file_path=evidence_meta["file_url"]
                )
                if not source_result["is_valid"]:
                    verification_issues.append(f"Invalid evidence source: {source_result['suspicious_indicators']}")
            except Exception as e:
                logger.warning(f"Source validation failed: {e}")
        
        # 2. Location consistency validation
        try:
            location_result = validate_location_consistency(
                report_latitude=float(report.latitude),
                report_longitude=float(report.longitude),
                evidence_metadata=evidence_metadata_list
            )
            if not location_result["is_consistent"]:
                verification_issues.append(f"Location inconsistency detected: {location_result['details']}")
            
            # Store location validation results in report metadata
            fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
            fv["location_validation"] = location_result
            report.feature_vector = _json_safe(fv)
        except Exception as e:
            logger.warning(f"Location consistency validation failed: {e}")
        
        # 3. ML-based credibility scoring - ensure it works properly
        try:
            score_report_credibility(db, report, device, evidence_count)
            logger.info(f"XGBoost ML scoring completed for report {report_id}")
        except Exception as e:
            logger.error(f"XGBoost ML scoring failed for report {report_id}: {e}")
            # Don't rely on fallback - fix the root cause
            raise HTTPException(status_code=500, detail=f"ML scoring failed during report creation: {str(e)}")
            
        try:
            update_device_ml_aggregates(db, device, window=30)
            logger.info(f"Device ML aggregates updated for report {report_id}")
        except Exception as e:
            logger.error(f"Device ML aggregates update failed for report {report_id}: {e}")
            # Non-critical, don't fail the whole request
        
        # 4. Apply rule-based verification
        try:
            apply_rule_based_status(db, report, device, verification_issues)
        except Exception as e:
            logger.error(f"Rule-based verification failed for report {report_id}: {e}")
        
        # 5. Update hotspot clustering
        try:
            if report.status not in ["rejected", "flagged"]:
                create_hotspots_from_reports(db, [report])
        except Exception as e:
            logger.error(f"Hotspot creation failed for report {report_id}: {e}")
        
        db.commit()
        logger.info(f"Background processing completed for report {report_id}")
        
        # Broadcast update to dashboard
        try:
            manager.broadcast({"type": "refresh_data", "entity": "report", "action": "processed"})
        except Exception as e:
            logger.warning(f"Failed to broadcast update for report {report_id}: {e}")
            
    except Exception as e:
        logger.error(f"Background processing error for report {report_id}: {e}")
        db.rollback()
    finally:
        db.close()


def _normalize_evidence_file_url(raw: str | None) -> str | None:
    """
    Ensure evidence file_url is stored as a usable URL/path, not a bare filename.
    - https://... stays as-is (Cloudinary / remote)
    - /uploads/... stays as-is (local static mount)
    - bare filename becomes /uploads/evidence/<filename>
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("/uploads/"):
        return s
    if s.startswith("/"):
        return s
    return f"/uploads/evidence/{s}"

# Evidence AI Analysis functions
def detect_blur(image_bytes: bytes) -> tuple[float, bool]:
    """Detect image blur using Laplacian variance method."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
        
        # Convert bytes to numpy array
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to grayscale
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
        
        # Calculate Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Normalize to 0-100 scale (typical range: 100-1000)
        blur_score = min(100.0, max(0.0, (laplacian_var / 10.0)))
        
        # Consider blurry if score < 20
        is_blurry = blur_score < 20.0
        
        return blur_score, is_blurry
        
    except Exception as e:
        logger.error(f"Blur detection failed: {e}")
        return 50.0, False  # Default medium score

def detect_tampering(image_bytes: bytes) -> tuple[float, bool]:
    """Detect potential image tampering using error level analysis."""
    try:
        from PIL import Image
        import numpy as np
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Save at quality 95 (high quality)
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=95)
        buffer.seek(0)
        resaved_image = Image.open(buffer)
        
        # Calculate difference
        original_array = np.array(image)
        resaved_array = np.array(resaved_image)
        
        # Calculate mean absolute error
        diff = np.abs(original_array.astype(float) - resaved_array.astype(float))
        mae = np.mean(diff)
        
        # Normalize to 0-100 scale (typical range: 0-50)
        tamper_score = min(100.0, max(0.0, (mae * 2.0)))
        
        # Consider tampered if score > 30
        is_tampered = tamper_score > 30.0
        
        return tamper_score, is_tampered
        
    except Exception as e:
        logger.error(f"Tamper detection failed: {e}")
        return 10.0, False  # Default low score

def assess_image_quality(image_bytes: bytes, blur_score: float, tamper_score: float) -> str:
    """Assess overall image quality based on multiple factors."""
    try:
        from PIL import Image
        
        image = Image.open(io.BytesIO(image_bytes))
        
        # Basic quality metrics
        width, height = image.size
        resolution_score = min(100.0, (width * height) / 10000.0)  # Scale based on resolution
        
        # Aspect ratio penalty for extreme ratios
        aspect_ratio = width / height
        aspect_penalty = 0.0
        if aspect_ratio < 0.5 or aspect_ratio > 2.0:
            aspect_penalty = 20.0
        
        # File size consideration (proxy for compression)
        file_size_score = min(100.0, len(image_bytes) / 10000.0)
        
        # Combined quality score
        quality_score = (
            (blur_score * 0.4) +           # Blur is most important
            ((100 - tamper_score) * 0.3) + # Lower tamper score is better
            (resolution_score * 0.2) +     # Resolution matters
            (file_size_score * 0.1) -      # File size consideration
            aspect_penalty
        )
        
        # Determine quality label
        if quality_score >= 80:
            return "high"
        elif quality_score >= 60:
            return "medium"
        elif quality_score >= 40:
            return "low"
        else:
            return "poor"
            
    except Exception as e:
        logger.error(f"Quality assessment failed: {e}")
        return "fair"  # Default medium quality

def analyze_evidence_file(file_bytes: bytes, file_type: str) -> dict:
    """Perform comprehensive AI analysis on evidence file."""
    analysis = {
        'blur_score': None,
        'tamper_score': None,
        'quality_label': None,
        'ai_checked_at': datetime.now(timezone.utc),
        'analysis_method': 'basic_cv'
    }
    
    try:
        if file_type.startswith('image'):
            # Image analysis
            blur_score, is_blurry = detect_blur(file_bytes)
            tamper_score, is_tampered = detect_tampering(file_bytes)
            quality_label = assess_image_quality(file_bytes, blur_score, tamper_score)
            
            analysis.update({
                'blur_score': round(blur_score, 3),
                'tamper_score': round(tamper_score, 3),
                'quality_label': quality_label,
                'is_blurry': is_blurry,
                'is_tampered': is_tampered
            })
            
        elif file_type.startswith('video'):
            # Video analysis (basic for now)
            analysis.update({
                'blur_score': 75.0,  # Default good score for video
                'tamper_score': 15.0,  # Low tamper risk for video
                'quality_label': "medium",
                'analysis_method': 'video_default'
            })
            
        elif file_type.startswith('audio'):
            # Audio analysis (basic for now)
            analysis.update({
                'blur_score': None,  # Not applicable for audio
                'tamper_score': 10.0,  # Low tamper risk for audio
                'quality_label': "medium",
                'analysis_method': 'audio_default'
            })
            
        else:
            # Unknown file type
            analysis.update({
                'blur_score': None,
                'tamper_score': 50.0,
                'quality_label': "low",
                'analysis_method': 'unknown'
            })
            
    except Exception as e:
        logger.error(f"Evidence analysis failed: {e}")
        analysis.update({
            'blur_score': None,
            'tamper_score': 50.0,
            'quality_label': "poor",
            'analysis_error': str(e)
        })
    
    return analysis


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _log_blocked_device_action(
    db: Session,
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
    3) Rate limiting - prevent suspicious rapid submissions.
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

    # Professional rate limiting: Balance security with emergency reporting needs
    
    # Check for suspicious rapid submissions (last 10 minutes)
    rate_limit_window = now_utc - timedelta(minutes=10)  # Last 10 minutes
    recent_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= rate_limit_window,
        )
        .count()
    )
    
    # Allow max 8 reports per 10 minutes per device (reasonable for multiple incidents)
    max_submissions_per_10min = 8
    if recent_submissions >= max_submissions_per_10min:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_rate_limit",
            request=request,
            device=device,
            details={
                "recent_submissions": recent_submissions,
                "time_window_minutes": 10,
                "max_allowed": max_submissions_per_10min,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: Maximum {max_submissions_per_10min} reports allowed per 10 minutes. For emergency assistance, please contact authorities directly.",
        )
    
    # Check for very suspicious activity (multiple submissions in 2 minutes)
    very_recent_window = now_utc - timedelta(minutes=2)  # Last 2 minutes
    very_recent_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= very_recent_window,
        )
        .count()
    )
    
    # Allow max 3 reports per 2 minutes per device (prevents spam but allows legitimate multiple reports)
    max_submissions_per_2min = 3
    if very_recent_submissions >= max_submissions_per_2min:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_suspicious_activity",
            request=request,
            device=device,
            details={
                "very_recent_submissions": very_recent_submissions,
                "time_window_minutes": 2,
                "max_allowed": max_submissions_per_2min,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Please wait at least 2 minutes before submitting additional reports. This helps ensure system stability for all users.",
        )
    
    # Check for extreme spam (multiple submissions in 30 seconds)
    extreme_window = now_utc - timedelta(seconds=30)  # Last 30 seconds
    extreme_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= extreme_window,
        )
        .count()
    )
    
    # Allow max 1 report per 30 seconds per device (prevents automated spam)
    max_submissions_per_30sec = 1
    if extreme_submissions >= max_submissions_per_30sec:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_extreme_spam",
            request=request,
            device=device,
            details={
                "extreme_submissions": extreme_submissions,
                "time_window_seconds": 30,
                "max_allowed": max_submissions_per_30sec,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Please wait at least 30 seconds between report submissions. Automated submissions are not allowed.",
        )
    
    # Additional check: Prevent obvious bot behavior (same incident type repeatedly)
    very_recent_reports = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= very_recent_window,
        )
        .order_by(Report.reported_at.desc())
        .limit(5)
        .all()
    )
    
    if len(very_recent_reports) >= 3:
        # Check if last 3 reports are all the same incident type (potential bot behavior)
        recent_incident_types = [r.incident_type_id for r in very_recent_reports[:3]]
        current_incident_type = int(report_data.incident_type_id)
        
        if len(set(recent_incident_types)) == 1 and recent_incident_types[0] == current_incident_type:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_repetitive_bot_behavior",
                request=request,
                device=device,
                details={
                    "current_incident_type": current_incident_type,
                    "recent_incident_types": recent_incident_types,
                    "identical_count": 3,
                    "time_window_minutes": 2,
                },
            )
            raise HTTPException(
                status_code=429,
                detail=f"Multiple identical reports detected. Please ensure each report represents a unique incident. If this is an error, please wait 2 minutes.",
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
            analyze_all_reports=False,  # Use time window for real-time updates
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
                    loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "geographic_intelligence", "action": "updated"}))
                except RuntimeError:
                    asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "hotspot", "action": "auto_created"}))
                    asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "geographic_intelligence", "action": "updated"}))
            except Exception as e:
                print(f"Failed to broadcast hotspot update: {e}")
            
            # Create notifications for admins and supervisors about new hotspots
            from app.api.v1.notifications import create_role_notifications
            
            # Get the most recently created hotspot for notification
            latest_hotspot = db.query(Hotspot).order_by(Hotspot.detected_at.desc()).first() if created > 0 else None
            
            create_role_notifications(
                db,
                title="New Hotspots Detected",
                message=f"{created} new safety hotspots have been automatically detected based on recent reports.",
                notif_type="system",
                related_entity_type="hotspot",
                related_entity_id=str(latest_hotspot.hotspot_id) if created == 1 and latest_hotspot else None,
                target_roles=["admin", "supervisor"],
                send_email=True  # Enable email notifications for hotspots
            )
        db.commit()
    except Exception as e:
        print(f"Error in background hotspot creation: {e}")
        db.rollback()
    finally:
        db.close()


def run_auto_case_realtime():
    """Background task to run case auto-linking/creation after live report changes."""
    db = SessionLocal()
    try:
        case_stats = _create_auto_cases(db)
        if case_stats.get("cases_created", 0) > 0:
            print(
                f"Realtime auto-case run: created {case_stats['cases_created']} case(s)"
            )
            try:
                _balance_workload_and_reassign(db)
            except Exception as balance_error:
                print(f"Warning: workload balancing failed after auto-case run: {balance_error}")
    except Exception as e:
        print(f"Error in realtime auto-case run: {e}")
        db.rollback()
    finally:
        db.close()


def run_auto_case_for_report(report_id: str):
    """Background task wrapper for single-report real-time auto-case processing."""
    try:
        logger.info("[AUTO_CASE] Triggered realtime processing for report %s", report_id)
        _check_and_create_auto_case(report_id)
    except Exception as e:
        logger.error(
            "[AUTO_CASE] Error in realtime processing for report %s: %s",
            report_id,
            e,
        )
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
    
    incoming_report_id = report_data.report_id or uuid4()
    if report_data.report_id:
        existing_report = (
            db.query(Report)
            .filter(Report.report_id == report_data.report_id)
            .first()
        )
        if existing_report:
            raise HTTPException(status_code=409, detail="Report already exists")

    report_num = _generate_report_number(db) if hasattr(Report, "report_number") else None
    report = Report(
        report_id=incoming_report_id,
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
    try:
        db.flush()  # Get report_id
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Report already exists")

    # Evidence processing with content analysis
    evidence_metadata_list = []
    evidence_validations = []
    
    for evidence_data in report_data.evidence_files:
        normalized_url = _normalize_evidence_file_url(getattr(evidence_data, "file_url", None))
        if not normalized_url:
            continue
        
        evidence_metadata_list.append({
            "media_latitude": evidence_data.media_latitude,
            "media_longitude": evidence_data.media_longitude,
            "captured_at": evidence_data.captured_at,
            "file_url": normalized_url,
            "file_type": evidence_data.file_type,
        })
        
        # Analyze evidence content for image files
        blur_score = None
        tamper_score = None
        quality_label = None
        validation_result = None
        
        if evidence_data.file_type and evidence_data.file_type.lower() in ['photo', 'image/jpeg', 'image/png', 'image/jpg']:
            try:
                # Perform evidence analysis
                analysis = evidence_analysis_service.analyze_image_from_url(normalized_url)
                
                # Validate evidence against incident type
                validation_result = evidence_analysis_service.validate_incident_evidence(
                    incident_type_id=report_data.incident_type_id,
                    description=report_data.description or "",
                    analysis=analysis
                )
                
                # Extract quality metrics
                blur_score = float(analysis.blur_score) if analysis.blur_score else None
                tamper_score = float(1.0 - analysis.confidence_score) if analysis.confidence_score else None
                
                # Determine quality label based on analysis
                if analysis.confidence_score >= 0.8:
                    quality_label = "good"
                elif analysis.confidence_score >= 0.5:
                    quality_label = "fair"
                else:
                    quality_label = "poor"
                
                # Log validation results
                logger.info(f"Evidence validation for report {report.report_id}: "
                           f"valid={validation_result['valid']}, "
                           f"confidence={validation_result['confidence']:.2f}, "
                           f"issues={validation_result['issues']}")
                
                # Store validation for later processing
                evidence_validations.append({
                    'evidence_url': normalized_url,
                    'validation': validation_result
                })
                
            except Exception as e:
                logger.error(f"Error analyzing evidence {normalized_url}: {e}")
                # Set default values if analysis fails
                quality_label = "poor"
                blur_score = 0.0
                tamper_score = 1.0
        
        evidence = EvidenceFile(
            evidence_id=uuid4(),
            report_id=report.report_id,
            file_url=normalized_url,
            file_type=evidence_data.file_type,
            media_latitude=evidence_data.media_latitude,
            media_longitude=evidence_data.media_longitude,
            captured_at=evidence_data.captured_at,
            is_live_capture=evidence_data.is_live_capture,
            blur_score=blur_score,
            tamper_score=tamper_score,
            quality_label=quality_label,
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
    
    # Text-only analysis for reports without evidence
    elif not evidence_validations:
        # This report has no evidence files - perform text-only analysis
        try:
            from app.services.evidence_analysis import analyze_text_only_report
            
            incident_type = db.query(IncidentType).filter(IncidentType.incident_type_id == report.incident_type_id).first()
            incident_type_name = incident_type.type_name if incident_type else "unknown"
            
            # Perform text-only analysis
            text_analysis = analyze_text_only_report(
                description=report_data.description or "",
                incident_type_name=incident_type_name,
                incident_type_id=report.incident_type_id
            )

            # Extract quality metrics
            blur_score = float(analysis.blur_score) if analysis.blur_score else None
            tamper_score = float(1.0 - analysis.confidence_score) if analysis.confidence_score else None

            # Determine quality label based on analysis
            if analysis.confidence_score >= 0.8:
                quality_label = "good"
            elif analysis.confidence_score >= 0.5:
                quality_label = "fair"
            else:
                quality_label = "poor"

            # Log validation results
            logger.info(f"Evidence validation for report {report.report_id}: "
                       f"valid={validation_result['valid']}, "
                       f"confidence={validation_result['confidence']:.2f}, "
                       f"issues={validation_result['issues']}")

            # Store validation for later processing
            evidence_validations.append({
                'evidence_url': normalized_url,
                'validation': validation_result
            })

        except Exception as e:
            logger.error(f"Error analyzing evidence {normalized_url}: {e}")
            # Set default values if analysis fails
            quality_label = "poor"
            blur_score = 0.0
            tamper_score = 1.0

    evidence = EvidenceFile(
        evidence_id=uuid4(),
        report_id=report.report_id,
        file_url=normalized_url,
        file_type=evidence_data.file_type,
        media_latitude=evidence_data.media_latitude,
        media_longitude=evidence_data.media_longitude,
        captured_at=evidence_data.captured_at,
        is_live_capture=evidence_data.is_live_capture,
        blur_score=blur_score,
        tamper_score=tamper_score,
        quality_label=quality_label,
    )
    db.add(evidence)
    ml_prediction = resolve_ml_prediction_for_report(report)
    trust_score = (
        float(ml_prediction.trust_score)
        if ml_prediction is not None and ml_prediction.trust_score is not None
        else None
    )
    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()
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
        ml_prediction_label=ml_prediction_label,
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
                file_url=_absolute_evidence_url(getattr(ef, "file_url", None)) or "",
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
    
    return response


@router.get("/", response_model=ReportListResponse)
def list_reports(
    device_id: Optional[UUID] = Query(None, description="Device ID (mobile owner). If omitted, auth required."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    report_status: Optional[str] = Query(None, description="Filter by report status"),
    rule_status: Optional[str] = Query(None, description="Filter by rule status"),
    boundary_status: Optional[str] = Query(None, description="Filter by boundary status"),
    incident_type_id: Optional[UUID] = Query(None, description="Filter by incident type"),
    village_location_id: Optional[UUID] = Query(None, description="Filter by village location"),
    sector_location_id: Optional[UUID] = Query(None, description="Filter by sector location"),
    from_date: Optional[datetime] = Query(None, description="Filter reports from this date"),
    to_date: Optional[datetime] = Query(None, description="Filter reports to this date"),
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
                joinedload(Report.village_location)
                .joinedload(Location.parent),  # Load parent location (cell -> sector hierarchy)
                selectinload(Report.evidence_files),
                selectinload(Report.assignments)
                .joinedload(ReportAssignment.police_user)
                .joinedload(PoliceUser.station),  # Load station through police user assignments
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
        joinedload(Report.village_location)
        .joinedload(Location.parent),  # Load parent location (cell -> sector hierarchy)
        selectinload(Report.evidence_files),
        selectinload(Report.assignments)
        .joinedload(ReportAssignment.police_user)
        .joinedload(PoliceUser.station),  # Load station through police user assignments
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
        
        # Get station to find its sector location(s)
        station = db.query(Station).filter(Station.station_id == supervisor_station_id).first()
        if station:
            # Handle both primary and secondary sectors
            sector_location_ids = []
            
            # Primary sector
            if station.location_id:
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
                sector_location_ids.extend([loc[0] for loc in sector_locations_query.all()])
            
            # Secondary sector (if exists)
            if station.sector2_id:
                sector2_location_id = station.sector2_id
                # Find all villages/cells in secondary sector
                sector2_locations_query = db.query(Location.location_id).filter(
                    or_(
                        Location.location_id == sector2_location_id,  # The sector itself
                        Location.parent_location_id == sector2_location_id,  # Direct children (cells)
                        # Also get villages under cells in this sector
                        Location.location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id.in_(
                                    db.query(Location.location_id).filter(
                                        Location.parent_location_id == sector2_location_id
                                    )
                                )
                            )
                        )
                    )
                )
                sector_location_ids.extend([loc[0] for loc in sector2_locations_query.all()])
            
            # Remove duplicates
            sector_location_ids = list(set(sector_location_ids))
            
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
        # Human review for flagged reports - police can make final decisions
        report.verification_status = "verified"
        report.status = "verified"
        report.is_flagged = False
        report.flag_reason = None
        if body.review_note:
            print(f" POLICE VERIFIED: Report {report_id} manually verified - {body.review_note}")
        else:
            print(f" POLICE VERIFIED: Report {report_id} manually verified")

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
        # Recompute device aggregates after police final decision and ML override updates.
        if getattr(report, "device", None) is not None:
            update_device_ml_aggregates(db, report.device, window=30)

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
    
    # Trigger real-time automation after police review decisions.
    # Cases need verified outcomes; hotspots should refresh for any final decision change.
    if report.verification_status == "verified":
        background_tasks.add_task(run_auto_case_for_report, str(report.report_id))
    background_tasks.add_task(run_hotspot_auto)
    
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


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get a single report by ID."""
    from sqlalchemy.orm import joinedload
    
    report = (
        db.query(Report)
        .options(
            joinedload(Report.device),
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.evidence_files),
            joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
        )
        .filter(Report.report_id == report_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return _build_report_response(report, db)


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


@router.get("/{report_id}/related", response_model=List[ReportResponse])
def get_related_reports(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
):
    """Get related reports based on location and incident type."""
    from sqlalchemy.orm import joinedload
    
    # Get the original report
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Find related reports based on:
    # 1. Same incident type
    # 2. Nearby location (within ~5km)
    # 3. Recent reports (last 30 days)
    
    from datetime import datetime, timedelta
    from sqlalchemy import and_, or_
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Calculate nearby location bounds (approximate 5km radius)
    lat_diff = 0.05  # ~5.5km
    lon_diff = 0.05  # ~5.5km at equator
    
    related_reports = (
        db.query(Report)
        .options(
            joinedload(Report.device),
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.evidence_files),
            joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
        )
        .filter(
            and_(
                Report.report_id != report_id,  # Exclude the original report
                Report.reported_at >= thirty_days_ago,
                or_(
                    Report.incident_type_id == report.incident_type_id,  # Same incident type
                    and_(
                        Report.latitude.between(
                            float(report.latitude) - lat_diff,
                            float(report.latitude) + lat_diff
                        ),
                        Report.longitude.between(
                            float(report.longitude) - lon_diff,
                            float(report.longitude) + lon_diff
                        )
                    )  # Nearby location
                )
            )
        )
        .order_by(Report.reported_at.desc())
        .limit(limit)
        .all()
    )
    
    return [_build_report_response(r, db) for r in related_reports]


@router.get("/{report_id}/location-history")
def get_reporter_location_history(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get location history for the reporter of a specific report.
    Returns chronological list of location changes with timestamps.
    """
    try:
        # Get the target report
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Get all reports from the same device (reporter)
        device_reports = (
            db.query(Report)
            .filter(Report.device_id == report.device_id)
            .filter(Report.report_id != report_id)  # Exclude current report
            .order_by(Report.reported_at.desc())
            .limit(limit)
            .all()
        )
        
        # Helper function to get location name from location relationship
        def get_location_name(location):
            if not location:
                return "Unknown"
            return location.location_name or "Unknown"
        
        # Build location history timeline
        location_history = []
        current_location = {
            "sector": get_location_name(report.location),
            "cell": get_location_name(report.village_location),
            "village": get_location_name(report.village_location),
        }
        
        # Add current report location first
        location_history.append({
            "report_id": str(report.report_id),
            "report_number": report.report_number,
            "timestamp": report.reported_at.isoformat(),
            "sector": current_location["sector"],
            "cell": current_location["cell"],
            "village": current_location["village"],
            "location_changed": False,  # This is the reference point
            "latitude": float(report.latitude) if report.latitude else None,
            "longitude": float(report.longitude) if report.longitude else None,
        })
        
        # Process historical reports to detect location changes
        for hist_report in device_reports:
            hist_location = {
                "sector": get_location_name(hist_report.location),
                "cell": get_location_name(hist_report.village_location),
                "village": get_location_name(hist_report.village_location),
            }
            
            # Check if location changed from previous
            location_changed = (
                hist_location["sector"] != current_location["sector"] or
                hist_location["cell"] != current_location["cell"] or
                hist_location["village"] != current_location["village"]
            )
            
            location_entry = {
                "report_id": str(hist_report.report_id),
                "report_number": hist_report.report_number,
                "timestamp": hist_report.reported_at.isoformat(),
                "sector": hist_location["sector"],
                "cell": hist_location["cell"],
                "village": hist_location["village"],
                "location_changed": location_changed,
                "latitude": float(hist_report.latitude) if hist_report.latitude else None,
                "longitude": float(hist_report.longitude) if hist_report.longitude else None,
            }
            
            location_history.append(location_entry)
            
            # Update current location for next comparison
            if location_changed:
                current_location = hist_location.copy()
        
        # Sort by timestamp (newest first)
        location_history.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
                "device_id": str(report.device_id),
                "current_location": current_location,
                "total_reports": len(location_history),
                "location_changes": len([loc for loc in location_history if loc["location_changed"]]),
                "history": location_history,
            }
    except Exception as e:
        # Log the error for debugging
        import logging
        logging.error(f"Error in location history endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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


@router.post("/{report_id}/evidence/{evidence_id}/validate")
def validate_evidence(
    report_id: UUID,
    evidence_id: UUID,
    ground_truth_label: str = Form(...),
    verification_confidence: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
    request: Request = None,
):
    """
    Validate evidence with ground truth label for AI training.
    
    Args:
        ground_truth_label: "real", "fake", or "manipulated"
        verification_confidence: 0-100 confidence in the ground truth assessment
    """
    if ground_truth_label not in ("real", "fake", "manipulated"):
        raise HTTPException(status_code=400, detail="ground_truth_label must be real, fake, or manipulated")
    
    # Verify evidence exists and belongs to report
    evidence = db.query(EvidenceFile).filter(
        EvidenceFile.evidence_id == evidence_id,
        EvidenceFile.report_id == report_id
    ).first()
    
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # Update evidence with ground truth
    evidence.ground_truth_label = ground_truth_label
    evidence.evidence_verified_by = current_user.police_user_id
    evidence.evidence_verified_at = datetime.now(timezone.utc)
    evidence.verification_confidence = verification_confidence
    
    # Log the validation action
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_action(
        db,
        "evidence_validated",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="evidence_file",
        entity_id=str(evidence_id),
        action_details={
            "ground_truth_label": ground_truth_label,
            "verification_confidence": verification_confidence,
            "ai_analysis": {
                "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
                "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
                "quality_label": evidence.quality_label.value if evidence.quality_label else None
            }
        },
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    
    db.commit()
    
    return {
        "evidence_id": str(evidence.evidence_id),
        "ground_truth_label": evidence.ground_truth_label,
        "verified_at": evidence.evidence_verified_at,
        "verified_by": current_user.police_user_id,
        "ai_analysis": {
            "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
            "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
            "quality_label": evidence.quality_label.value if evidence.quality_label else None
        }
    }


@router.get("/evidence-training-data")
def get_evidence_training_data(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    include_unvalidated: bool = Query(False),
):
    """
    Get evidence data with AI analysis and ground truth for ML training.
    
    Args:
        limit: Maximum number of records to return
        include_unvalidated: Include evidence without ground truth labels
    """
    query = db.query(EvidenceFile).options(
        joinedload(EvidenceFile.report)
    )
    
    if not include_unvalidated:
        query = query.filter(EvidenceFile.ground_truth_label.isnot(None))
    
    evidence_list = query.limit(limit).all()
    
    training_data = []
    for evidence in evidence_list:
        training_data.append({
            "evidence_id": str(evidence.evidence_id),
            "report_id": str(evidence.report_id),
            "file_type": evidence.file_type,
            "file_size": evidence.file_size,
            "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
            "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
            "quality_label": evidence.quality_label.value if evidence.quality_label else None,
            "ground_truth_label": evidence.ground_truth_label,
            "verification_confidence": float(evidence.verification_confidence) if evidence.verification_confidence else None,
            "verified_by": evidence.evidence_verified_by,
            "verified_at": evidence.evidence_verified_at.isoformat() if evidence.evidence_verified_at else None,
            "is_live_capture": evidence.is_live_capture,
            "ai_checked_at": evidence.ai_checked_at.isoformat() if evidence.ai_checked_at else None,
        })
    
    return {
        "training_data": training_data,
        "total_count": len(training_data),
        "includes_unvalidated": include_unvalidated,
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
            # The mobile client may queue retries locally and resend later.
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
    
    # Perform AI analysis on evidence
    ai_analysis = None
    try:
        ai_analysis = analyze_evidence_file(content, file_type)
        print(f"AI Analysis completed for evidence: {ai_analysis}")
    except Exception as e:
        print(f"AI Analysis failed for evidence: {e}")
        ai_analysis = {
            'blur_score': None,
            'tamper_score': 50.0,
            'quality_label': 'fair',
            'ai_checked_at': datetime.now(timezone.utc),
            'analysis_error': str(e)
        }
    
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
        blur_score=ai_analysis.get('blur_score'),
        tamper_score=ai_analysis.get('tamper_score'),
        quality_label=ai_analysis.get('quality_label'),
        ai_checked_at=ai_analysis.get('ai_checked_at'),
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
        # AI-PRIMARY with human oversight for flagged reports
        if rule_status == "passed" and not is_flagged:
            # AI makes final decision for clean reports
            report_after.status = "verified"
            report_after.verification_status = "verified"
            print(" AI-PRIMARY: Report auto-verified after evidence upload - rules passed")
        elif rule_status == "rejected":
            # Clear rejections are auto-rejected
            report_after.status = "rejected"
            report_after.verification_status = "rejected"
            print(f" AI-PRIMARY: Report auto-rejected after evidence upload - {rule_status}")
        else:
            # Flagged reports need human review
            report_after.status = "pending"
            report_after.verification_status = "under_review"
            print(f" HUMAN REVIEW NEEDED: Report flagged after evidence upload - {flag_reason}")
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

            # AI-PRIMARY: Community voting disabled - AI makes all decisions
            # Community votes only affect ML model training, not verification status
            print(" AI-PRIMARY: Community vote processed, but verification status unchanged")
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
    AI-PRIMARY: Community confirmation disabled - return empty list
    In AI-primary mode, there are no pending reports for community confirmation.
    """
    # AI-PRIMARY: No community confirmation needed
    return []

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
    background_tasks: BackgroundTasks = None,
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
    if background_tasks is not None:
        # Recompute hotspots after deletions so map stays live and accurate.
        background_tasks.add_task(run_hotspot_auto)
    return {}


def _check_and_create_auto_case(report_id: str):
    """Background task to add verified report to existing case or create new case using proper location-based clustering"""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report or report.verification_status != "verified":
            logger.info(
                "[AUTO_CASE] Skip report %s: report_exists=%s verification_status=%s",
                report_id,
                bool(report),
                getattr(report, "verification_status", None),
            )
            return
        
        # Check if report is already in a case
        from app.models.case_reports import case_reports_table
        existing_case = db.query(case_reports_table).filter(
            case_reports_table.c.report_id == report_id
        ).first()
        
        if existing_case:
            logger.info("[AUTO_CASE] Skip report %s: already linked to case", report_id)
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
        cluster_radius_meters = 500  # Default 500m for better incident grouping
        min_reports_threshold = 3   # Default from system config
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 500)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 3)

        logger.info(
            "[AUTO_CASE] Start report %s: incident_type=%s village=%s radius_m=%s min_reports=%s",
            report_id,
            report.incident_type_id,
            report.village_location_id,
            cluster_radius_meters,
            min_reports_threshold,
        )
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # STRATEGY 1: Try to add to existing case first
        existing_case_added = _try_add_to_existing_case(db, report, cluster_radius_km)
        if existing_case_added:
            logger.info("[AUTO_CASE] Report %s attached to existing case", report_id)
            return
        
        # STRATEGY 2: Create new case if no existing case found
        _create_new_case_for_report(db, report, cluster_radius_km, min_reports_threshold)
    
    except Exception as e:
        print(f"Error in auto-case processing for report {report_id}: {e}")
    finally:
        db.close()


def _try_add_to_existing_case(db: Session, report: Report, cluster_radius_km: float) -> bool:
    """Try to add report to existing compatible case"""
    try:
        from app.models.case import Case
        from app.models.case_reports import case_reports_table
        
        # Find existing cases with same incident type that are still open
        compatible_cases = db.query(Case).filter(
            Case.incident_type_id == report.incident_type_id,
            Case.status.in_(['open', 'assigned', 'in_progress']),
            Case.latitude.isnot(None),
            Case.longitude.isnot(None)
        ).all()

        logger.info(
            "[AUTO_CASE] Existing-case scan report=%s compatible_cases=%s",
            report.report_id,
            len(compatible_cases),
        )
        
        if not compatible_cases:
            return False
        
        from math import radians, cos, sin, asin, sqrt
        
        def calculate_distance(lat1, lon1, lat2, lon2):
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c  # Returns distance in kilometers
        
        # Priority 1: Same village (most precise)
        if report.village_location_id:
            for case in compatible_cases:
                if case.location_id == report.village_location_id:
                    # Add report to this case
                    db.execute(
                        case_reports_table.insert().values(
                            case_id=case.case_id,
                            report_id=report.report_id,
                            added_at=datetime.now(timezone.utc)
                        )
                    )
                    # Update case report count and timestamp
                    case.report_count = (case.report_count or 0) + 1
                    case.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    print(f"Added report {report.report_id} to existing case {case.case_number} (same village)")
                    return True
        
        # Priority 2: Geographic proximity (fallback)
        for case in compatible_cases:
            distance = calculate_distance(
                report.latitude, report.longitude,
                float(case.latitude), float(case.longitude)
            )
            logger.info(
                "[AUTO_CASE] Distance check report=%s case=%s distance_km=%.3f threshold_km=%.3f",
                report.report_id,
                case.case_number,
                distance,
                cluster_radius_km,
            )
            if distance <= cluster_radius_km:
                # Add report to this case
                db.execute(
                    case_reports_table.insert().values(
                        case_id=case.case_id,
                        report_id=report.report_id,
                        added_at=datetime.now(timezone.utc)
                    )
                )
                # Update case report count and timestamp
                case.report_count = (case.report_count or 0) + 1
                case.updated_at = datetime.now(timezone.utc)
                db.commit()
                print(f"Added report {report.report_id} to existing case {case.case_number} (within {cluster_radius_km * 1000:.0f}m)")
                return True
        
        return False
        
    except Exception as e:
        print(f"Error trying to add report to existing case: {e}")
        return False


def _create_new_case_for_report(db: Session, report: Report, cluster_radius_km: float, min_reports_threshold: int):
    """Create new case for report if enough similar reports exist"""
    try:
        from app.models.case_reports import case_reports_table
        
        # Strategy 1: Cluster by same village/location (preferred)
        if report.village_location_id:
            village_reports = db.query(Report).filter(
                Report.incident_type_id == report.incident_type_id,
                Report.verification_status == "verified",
                Report.village_location_id == report.village_location_id,
                Report.report_id != report.report_id,
                ~Report.report_id.in_(
                    db.query(case_reports_table.c.report_id).distinct()
                )
            ).all()
            
            # Add the current report
            village_reports.insert(0, report)
            logger.info(
                "[AUTO_CASE] Village candidate report=%s count=%s threshold=%s village=%s",
                report.report_id,
                len(village_reports),
                min_reports_threshold,
                report.village_location_id,
            )
            
            # Create case if enough reports in same village
            if len(village_reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, village_reports)
                if case_stats['cases_created'] > 0:
                    print(f"Created new village-based case {case_stats['case_number']} with {len(village_reports)} reports in village {report.village_location_id}")
                    return
            else:
                logger.info(
                    "[AUTO_CASE] Village threshold not met report=%s %s/%s",
                    report.report_id,
                    len(village_reports),
                    min_reports_threshold,
                )
        
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
            Report.report_id != report.report_id,
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

        logger.info(
            "[AUTO_CASE] Geo candidate report=%s count=%s threshold=%s radius_km=%.3f",
            report.report_id,
            len(clustered_reports),
            min_reports_threshold,
            cluster_radius_km,
        )
        
        # Create case if enough reports geographically clustered
        if len(clustered_reports) >= min_reports_threshold:
            case_stats = _create_case_from_reports(db, clustered_reports)
            if case_stats['cases_created'] > 0:
                print(f"Created new geo-clustered case {case_stats['case_number']} with {len(clustered_reports)} reports within {cluster_radius_km * 1000:.0f}m")
        else:
            logger.info(
                "[AUTO_CASE] Geo threshold not met report=%s %s/%s",
                report.report_id,
                len(clustered_reports),
                min_reports_threshold,
            )
    
    except Exception as e:
        print(f"Error creating new case for report: {e}")


def _auto_remove_rejected_report(report_id: str):
    """Background task to safely remove rejected reports"""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report:
            return
        
        # Double-check it's still rejected before removal
        if report.verification_status == "rejected" and report.status == "rejected":
            # Remove evidence files first
            from app.models.evidence import EvidenceFile
            evidence_files = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).all()
            for evidence in evidence_files:
                db.delete(evidence)
            
            # Remove ML predictions
            from app.models.ml_prediction import MLPrediction
            ml_predictions = db.query(MLPrediction).filter(MLPrediction.report_id == report_id).all()
            for ml_pred in ml_predictions:
                db.delete(ml_pred)
            
            # Remove case associations
            from app.models.case_reports import case_reports_table
            db.execute(case_reports_table.delete().where(case_reports_table.c.report_id == report_id))
            
            # Finally remove the report
            db.delete(report)
            db.commit()
            
            print(f" Successfully removed rejected report {report_id}")
            
            # Broadcast removal to keep clients in sync
            from app.api.v1.ws import manager
            try:
                background_tasks.add_task(
                    manager.broadcast,
                    {"type": "refresh_data", "entity": "report", "action": "deleted", "report_id": report_id}
                )
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast report removal: {broadcast_error}")
        
    except Exception as e:
        print(f"Error removing rejected report {report_id}: {e}")
        db.rollback()
    finally:
        db.close()


def _balance_report_workload_and_reassign(db: Session):
    """Smart workload balancing for assigned reports across multiple officers"""
    try:
        from app.models.report import Report
        from app.models.police_user import PoliceUser
        from sqlalchemy import func
        
        # Get all active officers
        officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer'
        ).all()
        
        if len(officers) < 2:
            return  # Need at least 2 officers for balancing
        
        # Calculate current report workload per officer
        workload = {str(officer.police_user_id): 0 for officer in officers}
        for officer_id, count in db.query(Report.verified_by, func.count(Report.report_id)).filter(
            Report.verified_by.in_([o.police_user_id for o in officers]),
            Report.status.in_(['pending', 'under_review'])
        ).group_by(Report.verified_by).all():
            workload[str(officer_id)] = count
        
        # Find overloaded and underloaded officers
        avg_reports = sum(workload.values()) / len(workload)
        overloaded = [oid for oid, count in workload.items() if count > avg_reports + 3]  # Threshold of 3 reports above average
        underloaded = [oid for oid, count in workload.items() if count < avg_reports - 1]  # Threshold of 1 report below average
        
        if not overloaded or not underloaded:
            return  # Workload is already balanced
        
        # Reassign reports from overloaded to underloaded officers
        reassigned = 0
        for overloaded_officer in overloaded:
            # Get newest assigned reports from overloaded officer (only flagged/boundary reports)
            reports_to_reassign = db.query(Report).filter(
                Report.verified_by == int(overloaded_officer),
                Report.status.in_(['pending', 'under_review']),
                Report.is_flagged == True,  # Only reassign flagged reports
                Report.reported_at >= datetime.now(timezone.utc) - timedelta(hours=6)  # Only recent reports (6 hours)
            ).order_by(Report.reported_at.desc()).limit(2).all()
            
            for report in reports_to_reassign:
                if underloaded:
                    # Find least loaded underloaded officer
                    target_officer = min(underloaded, key=lambda oid: workload[oid])
                    
                    # Reassign report
                    old_officer_id = report.verified_by
                    report.verified_by = int(target_officer)
                    report.handling_station_id = db.query(PoliceUser.station_id).filter(PoliceUser.police_user_id == int(target_officer)).scalar()
                    
                    # Update workload tracking
                    workload[overloaded_officer] -= 1
                    workload[target_officer] += 1
                    
                    # Remove from underloaded if they're now balanced
                    if workload[target_officer] >= avg_reports - 1:
                        underloaded.remove(target_officer)
                    
                    reassigned += 1
                    
                    print(f"🔄 Reassigned report {report.report_id} from officer {old_officer_id} to officer {target_officer}")
        
        if reassigned > 0:
            db.commit()
            print(f" Report workload balanced: {reassigned} reports reassigned across {len(officers)} officers")
            
            # Broadcast changes to keep clients synchronized
            try:
                from app.api.v1.ws import manager
                from app.core.websocket import manager as ws_manager
                ws_manager.broadcast({"type": "refresh_data", "entity": "report", "action": "reassigned"})
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast report reassignments: {broadcast_error}")
    
    except Exception as e:
        print(f"Error in report workload balancing: {e}")
        db.rollback()


def _balance_workload_and_reassign(db: Session):
    """Smart workload balancing across multiple officers"""
    try:
        from app.models.case import Case
        from app.models.police_user import PoliceUser
        from sqlalchemy import func
        
        # Get all active officers
        officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer'
        ).all()
        
        if len(officers) <= 1:
            return  # No balancing needed with 0 or 1 officer
        
        # Get current case counts per officer
        case_counts = db.query(
            Case.assigned_to_id,
            func.count(Case.case_id).label('active_cases')
        ).filter(
            Case.status.in_(['open', 'assigned', 'in_progress']),
            Case.assigned_to_id.isnot(None)
        ).group_by(Case.assigned_to_id).all()
        
        # Create workload dictionary
        workload = {str(officer.police_user_id): 0 for officer in officers}
        for officer_id, count in case_counts:
            workload[str(officer_id)] = count
        
        # Find overloaded and underloaded officers (aggressive balancing for equal distribution)
        avg_cases = sum(workload.values()) / len(workload)
        max_cases = max(workload.values()) if workload else 0
        min_cases = min(workload.values()) if workload else 0
        
        # Trigger balancing if there's any imbalance (difference of 1 or more)
        if max_cases - min_cases <= 0:
            return  # Already perfectly balanced
        
        overloaded = [oid for oid, count in workload.items() if count > min_cases]
        underloaded = [oid for oid, count in workload.items() if count < max_cases]
        
        if not overloaded or not underloaded:
            return  # No imbalance to fix
        
        # Reassign cases from overloaded to underloaded officers
        reassigned = 0
        for overloaded_officer in overloaded:
            # Get cases from overloaded officer (aggressive rebalancing)
            cases_to_reassign = db.query(Case).filter(
                Case.assigned_to_id == overloaded_officer,
                Case.status.in_(['assigned', 'open', 'in_progress']),  # Include more statuses
                Case.created_at >= datetime.now(timezone.utc) - timedelta(days=7)  # Include last 7 days
            ).order_by(Case.created_at.desc()).limit(5).all()  # Reassign up to 5 cases
            
            for case in cases_to_reassign:
                if underloaded:
                    # Find least loaded underloaded officer
                    target_officer = min(underloaded, key=lambda oid: workload[oid])
                    
                    # Reassign case
                    case.assigned_to_id = target_officer
                    case.status = 'assigned'
                    case.updated_at = datetime.now(timezone.utc)
                    
                    # Update workload tracking
                    workload[overloaded_officer] -= 1
                    workload[target_officer] += 1
                    
                    # Remove from underloaded if they're now balanced
                    if workload[target_officer] >= avg_cases - 1:
                        underloaded.remove(target_officer)
                    
                    reassigned += 1
                    
                    print(f"🔄 Reassigned case {case.case_number} from officer {overloaded_officer} to officer {target_officer}")
        
        if reassigned > 0:
            db.commit()
            print(f" Workload balanced: {reassigned} cases reassigned across {len(officers)} officers")
            
            # Broadcast changes to keep clients synchronized
            try:
                from app.api.v1.ws import manager
                background_tasks.add_task(
                    manager.broadcast,
                    {"type": "refresh_data", "entity": "case", "action": "reassigned"}
                )
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast case reassignments: {broadcast_error}")
    
    except Exception as e:
        print(f"Error in workload balancing: {e}")
        db.rollback()


def _handle_officer_case_finalization(db: Session, officer_id: str):
    """Reassign cases when an officer finalizes their current cases"""
    try:
        from app.models.case import Case
        from app.models.police_user import PoliceUser
        
        # Check if officer has any active cases
        active_cases = db.query(Case).filter(
            Case.assigned_to_id == officer_id,
            Case.status.in_(['open', 'assigned', 'in_progress'])
        ).count()
        
        if active_cases > 0:
            return  # Officer still has active cases
        
        # Find other active officers to reassign new cases to
        other_officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer',
            PoliceUser.police_user_id != officer_id
        ).all()
        
        if not other_officers:
            return  # No other officers available
        
        # Assign new unassigned cases to other officers
        unassigned_cases = db.query(Case).filter(
            Case.assigned_to_id.is_(None),
            Case.status == 'open'
        ).order_by(Case.created_at.asc()).limit(5).all()
        
        for case in unassigned_cases:
            # Assign to least loaded officer
            least_loaded = min(other_officers, key=lambda officer: 
                db.query(Case).filter(
                    Case.assigned_to_id == officer.police_user_id,
                    Case.status.in_(['open', 'assigned', 'in_progress'])
                ).count()
            )
            
            case.assigned_to_id = least_loaded.police_user_id
            case.status = 'assigned'
            case.updated_at = datetime.now(timezone.utc)
            
            print(f" Assigned unassigned case {case.case_number} to officer {least_loaded.police_user_id}")
        
        if unassigned_cases:
            db.commit()
            print(f" Redistributed {len(unassigned_cases)} unassigned cases after officer {officer_id} finalized all cases")
    
    except Exception as e:
        print(f"Error handling officer case finalization: {e}")
        db.rollback()

def _assign_officer_to_report_based_on_location(db: Session, report_lat: float, report_lon: float) -> Optional[int]:
    """Assign an officer to a flagged report based on station proximity and workload."""
    try:
        from app.models.station import Station
        from app.models.police_user import PoliceUser
        from app.models.report import Report
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

        ranked_stations = sorted(stations, key=lambda s: calculate_distance(report_lat, report_lon, s.latitude, s.longitude))

        for station in ranked_stations:
            officers = db.query(PoliceUser).filter(
                PoliceUser.is_active == True,
                PoliceUser.role == 'officer',
                PoliceUser.station_id == station.station_id
            ).all()

            if officers:
                officer_ids = [o.police_user_id for o in officers]
                # Count assigned reports (not cases) for workload
                report_counts = db.query(Report.verified_by, func.count(Report.report_id)).filter(
                    Report.verified_by.in_(officer_ids),
                    Report.status.in_(['pending', 'under_review'])
                ).group_by(Report.verified_by).all()
                
                count_dict = dict(report_counts)
                selected_officer = min(officers, key=lambda o: count_dict.get(o.police_user_id, 0))
                return selected_officer.police_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error assigning officer to report: {e}")
        return None


def _assign_officer_to_case_based_on_location(db: Session, case_lat: float, case_lon: float) -> Optional[int]:
    try:
        from app.models.station import Station
        from app.models.police_user import PoliceUser
        from app.models.case import Case
        from math import radians, cos, sin, asin, sqrt
        from sqlalchemy import func
        import random

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
                
                # Get current case counts for all officers
                officer_workloads = []
                for officer in officers:
                    count = count_dict.get(officer.police_user_id, 0)
                    officer_workloads.append((officer, count))
                
                # Sort by workload (ascending) - officers with fewer cases first
                officer_workloads.sort(key=lambda x: x[1])
                
                # Get minimum workload
                min_workload = officer_workloads[0][1] if officer_workloads else 0
                
                # Filter officers with minimum workload (for fair distribution)
                least_loaded_officers = [off for off, count in officer_workloads if count == min_workload]
                
                # Randomly select from least loaded officers to ensure rotation
                selected_officer = random.choice(least_loaded_officers)
                
                print(f"🎯 Assigned case to officer {selected_officer.police_user_id} (workload: {min_workload}) from {len(least_loaded_officers)} eligible officers")
                
                return selected_officer.police_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error assigning officer to case: {e}")
        return None

def _create_case_from_reports(db: Session, reports: List[Report]) -> Dict[str, int]:
    """Create a case from a cluster of reports"""
    stats = {'cases_created': 0, 'case_number': None}
    
    try:
        from app.models.case import Case, CaseReport
        case_reports_table = CaseReport.__table__
        
        report = reports[0]  # Use first report as reference
        case_count = db.query(Case).count()
        case_number = f"CASE-{datetime.now().year}-{case_count + 1:04d}"
        
        high_priority_count = sum(1 for r in reports if r.priority == 'high')
        priority = 'high' if high_priority_count >= 1 else 'medium'  # Single high priority report makes case high priority
        
        case_lat = sum(r.latitude for r in reports) / len(reports)
        case_lon = sum(r.longitude for r in reports) / len(reports)
        officer_id = _assign_officer_to_case_based_on_location(db, float(case_lat), float(case_lon))
        
        # Adjust title and description based on number of reports
        if len(reports) == 1:
            title = f"Incident Type {report.incident_type_id} case - Single Report"
            description = f"Auto-generated case from 1 verified report"
        else:
            title = f"Incident Type {report.incident_type_id} case - Multiple Reports"
            description = f"Auto-generated case from {len(reports)} verified reports"
        
        case = Case(
            case_id=uuid4(),
            case_number=case_number,
            title=title,
            description=description,
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
                )
            )
        
        # Update report status to indicate they're in a case
        for report in reports:
            report.status = "verified"
        
        db.commit()
        stats['cases_created'] += 1
        stats['case_number'] = case_number
        
        # Trigger workload balancing after case creation to ensure fair distribution
        try:
            _continuous_workload_balancing(db)
        except Exception as e:
            print(f"Warning: Could not trigger continuous workload balancing: {e}")
        print(f"Created auto-case {case.case_number} with {len(reports)} reports")
        
        # Broadcast case creation to all connected clients for real-time updates
        try:
            import asyncio
            payload = {"type": "refresh_data", "entity": "case", "action": "created"}
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager.broadcast(payload))
            except RuntimeError:
                asyncio.run(manager.broadcast(payload))
        except Exception as e:
            print(f"Warning: Could not broadcast case creation: {e}")
        
        # Send email notifications for auto case creation
        try:
            from app.api.v1.notifications import create_role_notifications
            from app.models.police_user import PoliceUser
            
            # Notify supervisors and admins about auto case creation
            create_role_notifications(
                db=db,
                title=f"Auto-Generated Case: {case.case_number}",
                message=f"A new case has been automatically created from {len(reports)} verified reports. Case: {case.title}",
                notif_type="system",
                related_entity_type="case",
                related_entity_id=str(case.case_id),
                target_roles=["supervisor", "admin"],
                send_email=True
            )
            
            # Notify assigned officer if case was assigned
            if case.assigned_to_id:
                from app.api.v1.notifications import create_notification
                create_notification(
                    db=db,
                    police_user_id=case.assigned_to_id,
                    title=f"Case Assigned: {case.case_number}",
                    message=f"You have been assigned to auto-generated case: {case.title}",
                    notif_type="assignment",
                    related_entity_type="case",
                    related_entity_id=str(case.case_id),
                    send_email=True
                )
                
        except Exception as e:
            print(f"Failed to send email notifications for case {case.case_number}: {e}")
        
    except Exception as e:
        print(f"Error creating case from reports: {e}")
    
    return stats


def _create_auto_cases(db: Session) -> Dict[str, int]:
    """Automatically create cases from verified reports using 12-hour time constraint and proper location-based clustering"""
    
    stats = {'cases_created': 0}
    
    try:
        from app.models.case import Case, CaseReport
        from datetime import datetime, timedelta, timezone
        case_reports_table = CaseReport.__table__
        
        # Time constraint: only reports within last 12 hours
        time_window_hours = 12
        since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
        
        # Get clustering parameters from system config
        from app.models.system_config import SystemConfig
        dbscan_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.epsilon'
        ).first()
        min_samples_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.min_samples'
        ).first()
        
        # Use configured values or defaults
        cluster_radius_meters = 500  # Default 500m for better incident grouping
        min_reports_threshold = 1   # Allow single reports to create cases
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 500)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 2)
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # Strategy 1: Cluster by village/location with time constraint (preferred)
        village_clusters = {}
        verified_reports = db.query(Report).filter(
            Report.verification_status == 'verified',
            Report.status == 'verified',
            Report.reported_at >= since,  # 12-hour time constraint
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            )
        ).all()
        
        logger.info(f"Found {len(verified_reports)} verified reports available for case creation")
        
        # Group by village and incident type with time constraint
        for report in verified_reports:
            if report.village_location_id:
                village_key = f"{report.village_location_id}_{report.incident_type_id}"
                if village_key not in village_clusters:
                    village_clusters[village_key] = []
                village_clusters[village_key].append(report)
        
        # Create cases for village-based clusters with time filtering
        for village_key, reports in village_clusters.items():
            if len(reports) >= min_reports_threshold:
                # Additional time filtering: ensure all reports in cluster are within 12 hours
                reports.sort(key=lambda r: r.reported_at)
                time_span = (reports[-1].reported_at - reports[0].reported_at).total_seconds() / 3600
                
                if time_span <= time_window_hours:  # Only create case if within 12-hour window
                    case_stats = _create_case_from_reports(db, reports)
                    stats['cases_created'] += case_stats['cases_created']
                    village_id, incident_type_id = village_key.split('_')
                    logger.info(f"Created ONE village-based case for {len(reports)} reports in village {village_id}, incident type {incident_type_id} (time span: {time_span:.1f}h)")
                else:
                    logger.info(f"Skipped village cluster for village {village_id}, incident type {incident_type_id} - time span {time_span:.1f}h exceeds {time_window_hours}h limit")
        
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
                    
                    # Create case if cluster has enough reports and within time window
                    if len(cluster) >= min_reports_threshold:
                        # Additional time filtering for geographic clusters
                        cluster.sort(key=lambda r: r.reported_at)
                        time_span = (cluster[-1].reported_at - cluster[0].reported_at).total_seconds() / 3600
                        
                        if time_span <= time_window_hours:  # Only create case if within 12-hour window
                            case_stats = _create_case_from_reports(db, cluster)
                            stats['cases_created'] += case_stats['cases_created']
                            logger.info(f"Created ONE geo-clustered case for {len(cluster)} reports of incident type {incident_type_id} within {cluster_radius_meters}m (time span: {time_span:.1f}h)")
                        else:
                            logger.info(f"Skipped geo cluster for incident type {incident_type_id} - time span {time_span:.1f}h exceeds {time_window_hours}h limit")
        
        if stats['cases_created'] > 0:
            db.commit()
        return stats
        
    except Exception as e:
        logger.error(f"Auto-case creation error: {e}")
        return stats
        db.commit()


def _automatic_incident_consolidation(db: Session, report: Report):
    """
    Automatic incident consolidation for verified reports.
    Uses existing case creation system for same-incident grouping.
    """
    print(f"Starting automatic incident consolidation for verified report {report.report_id}")
    
    # Use the existing auto-case creation system that was already working
    # This will handle same-incident grouping and case creation
    try:
        # Call the existing auto-case creation function
        from app.core.report_priority import auto_create_cases_from_verified_reports
        
        # Create a list with just this report to trigger the existing logic
        result = auto_create_cases_from_verified_reports(db, [report])
        
        if result and result.get('cases_created', 0) > 0:
            print(f"Auto-created {result['cases_created']} cases for report {report.report_id}")
        else:
            print(f"No case created for report {report.report_id} - will be grouped later")
            
    except Exception as e:
        print(f"Auto-case creation failed for report {report.report_id}: {e}")
        # Don't fail the report creation if case creation fails


def _build_report_response(report: Report, db: Session, request_device_id: Optional[str] = None) -> ReportResponse:
    """Build a ReportResponse from a Report object."""
    # Get ML prediction
    ml_prediction = resolve_ml_prediction_for_report(report)
    trust_score = (
        float(ml_prediction.trust_score)
        if ml_prediction is not None and ml_prediction.trust_score is not None
        else None
    )
    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()
    
    # Get device metadata and calculate device trust score
    device_metadata = None
    device_trust_score = None
    total_reports = None
    trusted_reports = None
    
    if report.device:
        device_metadata = report.device.metadata_json or {}
        
        # Get basic stats from device metadata
        total_reports = device_metadata.get("total_reports", 0)
        confirmed_reports = device_metadata.get("confirmed_reports", 0)
        
        # Calculate device trust score based on confirmed reports vs total reports
        if total_reports and total_reports > 0:
            # Device trust score = (confirmed_reports / total_reports) * 100
            # But cap at 100% and handle cases where confirmed_reports > total_reports
            if confirmed_reports and confirmed_reports > 0:
                # Ensure confirmed_reports doesn't exceed total_reports for calculation
                effective_confirmed = min(confirmed_reports, total_reports)
                device_trust_score = (effective_confirmed / total_reports) * 100
                # Cap at 100%
                device_trust_score = min(100, device_trust_score)
            else:
                # For new devices with no confirmed reports, give a baseline score
                # More reports = higher baseline trust (up to 50% max)
                device_trust_score = min(50, total_reports * 10)
        else:
            device_trust_score = 0
            
        # Use confirmed_reports as trusted_reports for display
        trusted_reports = confirmed_reports
        
        # Also check if device_trust_score is explicitly stored and use that if available
        stored_device_trust_score = device_metadata.get("device_trust_score")
        if stored_device_trust_score is not None:
            device_trust_score = float(stored_device_trust_score)
    
    # Build evidence files response
    evidence_files_response = [
        EvidenceFileResponse(
            report_id=str(report.report_id),
            evidence_id=str(ef.evidence_id),
            file_url=ef.file_url,
            file_type=ef.file_type,
            file_size=ef.file_size,
            uploaded_at=ef.uploaded_at,
            media_latitude=float(ef.media_latitude) if ef.media_latitude is not None else None,
            media_longitude=float(ef.media_longitude) if ef.media_longitude is not None else None,
            blur_score=float(ef.blur_score) if getattr(ef, "blur_score", None) is not None else None,
            tamper_score=float(ef.tamper_score) if getattr(ef, "tamper_score", None) is not None else None,
            quality_label=ef.quality_label.value if ef.quality_label else None,
        )
        for ef in (report.evidence_files or [])
    ]
    
    return ReportResponse(
        report_id=str(report.report_id),
        report_number=report.report_number,
        title=None,  # Report model doesn't have title field
        description=report.description,
        incident_type_id=str(report.incident_type_id) if report.incident_type_id else None,
        incident_type=report.incident_type,
        status=report.status,
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        reported_at=report.reported_at,
        village_location_id=str(report.village_location_id) if report.village_location_id else None,
        village_location=report.village_location,
        reporter_name=None,  # Report model doesn't have reporter_name field
        reporter_contact=None,  # Report model doesn't have reporter_contact field
        is_anonymous=True,  # Default to True since reports are from devices
        evidence_files=evidence_files_response,
        assignments=[],
        reviews=[],
        community_votes={},  # Changed from [] to {} to match dict type
        user_vote=None,
        metadata_json=device_metadata,
        device_trust_score=float(device_trust_score) if device_trust_score is not None else None,
        total_reports=total_reports,
        trusted_reports=trusted_reports,
        trust_score=trust_score,
        ml_prediction_label=ml_prediction_label,
        # Add missing required fields
        device_id=str(report.device_id),
        latitude=float(report.latitude) if report.latitude else None,
        longitude=float(report.longitude) if report.longitude else None,
        # Add fields needed by frontend reports table
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        village_name=report.village_location.location_name if report.village_location else None,
        # Add ML predictions array for frontend
        ml_predictions=[{
            'trust_score': float(ml_prediction.trust_score) if ml_prediction and ml_prediction.trust_score else None,
            'prediction_label': ml_prediction.prediction_label if ml_prediction else None,
            'evaluated_at': ml_prediction.evaluated_at.isoformat() if ml_prediction and ml_prediction.evaluated_at else None
        }] if ml_prediction else [],
    )


