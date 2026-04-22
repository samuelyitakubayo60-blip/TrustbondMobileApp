from typing import Annotated, Optional, List
import math

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from app.core.websocket import manager
import asyncio

from app.database import get_db
from app.models.device import Device
from app.models.report import Report
from app.models.ml_prediction import MLPrediction
from app.models.location import Location
from app.schemas.device import DeviceCreate, DeviceResponse
from app.api.v1.auth import get_current_admin_or_supervisor, get_current_admin_supervisor_or_officer
from app.models.police_user import PoliceUser
from app.schemas.ml import MLPredictionResponse, MLInsightResponse, DeviceMLStatsResponse
from app.core.credibility_model import (
    get_report_prediction,
    get_home_insights,
    get_device_ml_stats
)
from app.core.village_lookup import get_village_location_info

router = APIRouter(prefix="/devices", tags=["devices"])


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers"""
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def _report_is_trusted(report: Report) -> bool:
    """Normalize report trust semantics across legacy/new status fields."""
    rule_status = str(getattr(report, "rule_status", "") or "").strip().lower()
    status = str(getattr(report, "status", "") or "").strip().lower()
    verification_status = str(getattr(report, "verification_status", "") or "").strip().lower()
    return (
        rule_status in {"confirmed", "verified", "trusted", "passed"}
        or status in {"verified"}
        or verification_status in {"verified"}
    )


def _report_is_rejected_or_flagged(report: Report) -> bool:
    """Normalize rejected/flagged semantics used by the device registry table."""
    rule_status = str(getattr(report, "rule_status", "") or "").strip().lower()
    status = str(getattr(report, "status", "") or "").strip().lower()
    verification_status = str(getattr(report, "verification_status", "") or "").strip().lower()
    return (
        rule_status in {"flagged", "rejected", "false_report", "failed"}
        or status in {"flagged", "rejected"}
        or verification_status in {"rejected"}
    )


def _safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@router.post("/register", response_model=DeviceResponse)
def register_device(device_data: DeviceCreate, db: Session = Depends(get_db)):
    """Register or get existing device by hash (anonymous)"""
    device = (
        db.query(Device)
        .filter(Device.device_hash == device_data.device_hash)
        .first()
    )

    if device:
        return device

    new_device = Device(
        device_id=uuid4(),
        device_hash=device_data.device_hash,
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    return new_device


@router.get("/profile/{device_hash}")
def get_device_profile(device_hash: str, db: Session = Depends(get_db)):
    """
    Get device stats, total reports, and ML trust score by hash for the
    mobile profile screen.
    """
    device = (
        db.query(Device)
        .filter(Device.device_hash == device_hash)
        .first()
    )
    if not device:
        # Auto-create the device profile if it doesn't exist yet (brand new reporter)
        device = Device(
            device_id=uuid4(),
            device_hash=device_hash,
        )
        db.add(device)
        db.commit()
        db.refresh(device)

    # Aggregate report stats for this device.
    q = db.query(Report).filter(Report.device_id == device.device_id)
    total = q.count()
    trusted = (
        q.filter(
            Report.rule_status.in_(["confirmed", "verified", "trusted"])
        ).count()
        if total > 0
        else 0
    )
    flagged = (
        q.filter(
            Report.rule_status.in_(["flagged", "rejected", "false_report"])
        ).count()
        if total > 0
        else 0
    )

    trust_score = float(device.device_trust_score or 50.0)

    # Last ML credibility evaluation for any report from this device.
    last_ml = (
        db.query(func.max(MLPrediction.evaluated_at))
        .join(Report, MLPrediction.report_id == Report.report_id)
        .filter(Report.device_id == device.device_id)
        .scalar()
    )

    now = datetime.now(timezone.utc)
    trusted_statuses = ["confirmed", "verified", "trusted"]

    trusted_7d = (
        q.filter(
            Report.rule_status.in_(trusted_statuses),
            Report.reported_at >= now - timedelta(days=7),
        ).count()
        if total > 0
        else 0
    )

    trusted_30d = (
        q.filter(
            Report.rule_status.in_(trusted_statuses),
            Report.reported_at >= now - timedelta(days=30),
        ).count()
        if total > 0
        else 0
    )

    # Rank devices by trusted reports in the last 30 days.
    trusted_30d_by_device = (
        db.query(
            Report.device_id.label("device_id"),
            func.count(Report.report_id).label("trusted_cnt"),
        )
        .filter(
            Report.rule_status.in_(trusted_statuses),
            Report.reported_at >= now - timedelta(days=30),
        )
        .group_by(Report.device_id)
        .subquery()
    )

    max_trusted_30d = (
        db.query(func.coalesce(func.max(trusted_30d_by_device.c.trusted_cnt), 0)).scalar() or 0
    )

    # Achievements derived from real report stats (time-window aware)
    achievements = {
        "first_report": total >= 1,
        "five_verified": trusted >= 5,
        "ten_reports": total >= 10,
        # "Streak" approximated as number of trusted reports in the last 7 days.
        "streak_x7": trusted_7d >= 7,
        # "Top reporter" based on the highest trusted count in the last 30 days.
        "top_reporter": trusted_30d >= 10 and trusted_30d == max_trusted_30d and max_trusted_30d > 0,
    }

    return {
        "device_id": str(device.device_id),
        "device_hash": device.device_hash,
        "device_trust_score": trust_score,
        "total_reports": total,
        "trusted_reports": trusted,
        "flagged_reports": flagged,
        "last_ml_update": last_ml.isoformat() if last_ml else None,
        "achievements": achievements,
        "spam_flags": getattr(device, "spam_flags", None) or 0,
        "is_blacklisted": getattr(device, "is_blacklisted", False) or False,
        "blacklist_reason": getattr(device, "blacklist_reason", None),
        "last_seen_at": device.last_seen_at.isoformat() if getattr(device, "last_seen_at", None) else None,
    }


@router.get("/", response_model=dict)
def list_devices(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_supervisor_or_officer)],
    db: Session = Depends(get_db),
    trust_level: Optional[str] = Query(
        None, description="high (>=70), medium (40-69), low (<40)"
    ),
    include_banned: bool = Query(
        True,
        description="If true (default), include banned devices in the registry list.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List devices with trust stats for police dashboard. Admin/supervisor/officer access."""
    query = db.query(Device)
    if hasattr(Device, "is_banned") and not include_banned:
        query = query.filter(Device.is_banned == False)
    if trust_level == "high":
        query = query.filter(Device.device_trust_score >= 70)
    elif trust_level == "medium":
        query = query.filter(
            Device.device_trust_score >= 40, Device.device_trust_score < 70
        )
    elif trust_level == "low":
        query = query.filter(Device.device_trust_score < 40)
    total = query.count()
    devices = (
        query.order_by(
            Device.last_seen_at.desc() if hasattr(Device, "last_seen_at") else Device.first_seen_at.desc()
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Build per-device last activity and sector information from most recent report.
    items = []
    for d in devices:
        # Get actual report statistics for this device
        device_reports = db.query(Report).filter(Report.device_id == d.device_id).all()
        actual_total = len(device_reports)
        actual_trusted = sum(1 for r in device_reports if _report_is_trusted(r))
        actual_flagged = sum(1 for r in device_reports if _report_is_rejected_or_flagged(r))
        
        # Get most recent report for location and activity data
        last_report = None
        last_active = getattr(d, "last_seen_at", None)
        sector_location_id = None
        sector_name = None
        cell_location_id = None
        cell_name = None
        village_location_id = None
        village_name = None
        last_location = None
        last_latitude = None
        last_longitude = None
        
        if device_reports:
            last_report = max(device_reports, key=lambda r: r.reported_at or r.created_at)
            if not last_active:
                last_active = last_report.reported_at or last_report.created_at
            
            # Resolve coordinates + admin hierarchy from latest report location.
            lat_f = _safe_float(getattr(last_report, "latitude", None))
            lon_f = _safe_float(getattr(last_report, "longitude", None))
            if lat_f is not None and lon_f is not None:
                last_latitude = lat_f
                last_longitude = lon_f
                last_location = f"{lat_f:.4f}, {lon_f:.4f}"
                location_info = get_village_location_info(db, lat_f, lon_f)
                if isinstance(location_info, dict):
                    sector_location_id = location_info.get("sector_location_id")
                    sector_name = location_info.get("sector_name")
                    cell_location_id = location_info.get("cell_location_id")
                    cell_name = location_info.get("cell_name")
                    village_location_id = location_info.get("village_location_id")
                    village_name = location_info.get("village_name")

            # Fallback to report location relation if polygon lookup did not resolve.
            if village_name is None and getattr(last_report, "village_location", None):
                village = last_report.village_location
                village_location_id = getattr(village, "location_id", None)
                village_name = getattr(village, "location_name", None)
                parent_id = getattr(village, "parent_location_id", None)
                if parent_id:
                    parent = db.query(Location).filter(Location.location_id == parent_id).first()
                    if parent and parent.location_type == "cell":
                        cell_location_id = parent.location_id
                        cell_name = parent.location_name
                        if parent.parent_location_id:
                            sector = db.query(Location).filter(Location.location_id == parent.parent_location_id).first()
                            if sector:
                                sector_location_id = sector.location_id
                                sector_name = sector.location_name
                    elif parent and parent.location_type == "sector":
                        sector_location_id = parent.location_id
                        sector_name = parent.location_name

        # Metadata fallback for admin names/ids if report-derived values are unavailable.
        meta = getattr(d, "metadata_json", None)
        if isinstance(meta, dict):
            sector_location_id = sector_location_id or meta.get("last_sector_location_id")
            sector_name = sector_name or meta.get("last_sector_name")
            cell_location_id = cell_location_id or meta.get("last_cell_location_id")
            cell_name = cell_name or meta.get("last_cell_name")
            village_location_id = village_location_id or meta.get("last_village_location_id")
            village_name = village_name or meta.get("last_village_name")

        hierarchy_parts = [name for name in [sector_name, cell_name, village_name] if name]
        last_location_hierarchy = " > ".join(hierarchy_parts) if hierarchy_parts else None
        
        # Get ML data from device metadata and latest predictions
        ml_avg_trust = None
        ml_fake_rate = None
        ml_last_pred_at = None
        ml_avg_conf = None
        ml_last_conf = None
        
        # Try device metadata first
        try:
            meta = getattr(d, "metadata_json", None)
            if isinstance(meta, dict) and isinstance(meta.get("ml"), dict):
                ml = meta.get("ml") or {}
                ml_avg_trust = _safe_float(ml.get("avg_trust_score"))
                ml_fake_rate = _safe_float(ml.get("fake_rate"))
                ml_last_pred_at = ml.get("last_prediction_at")
                ml_avg_conf = _safe_float(ml.get("avg_confidence"))
                ml_last_conf = _safe_float(ml.get("last_confidence"))
        except Exception:
            pass
        
        # If no ML data in metadata, check latest ML prediction
        if ml_avg_trust is None and device_reports:
            latest_ml = (
                db.query(MLPrediction)
                .join(Report, MLPrediction.report_id == Report.report_id)
                .filter(Report.device_id == d.device_id)
                .order_by(MLPrediction.evaluated_at.desc())
                .first()
            )
            if latest_ml:
                ml_avg_trust = _safe_float(latest_ml.trust_score)
                # MLPrediction does not store aggregate fake_rate; derive a single-point proxy.
                if latest_ml.prediction_label is not None:
                    normalized_label = str(latest_ml.prediction_label).strip().lower()
                    ml_fake_rate = 1.0 if normalized_label == "fake" else 0.0
                ml_last_pred_at = latest_ml.evaluated_at.isoformat() if latest_ml.evaluated_at else None
                ml_avg_conf = _safe_float(latest_ml.confidence)
                ml_last_conf = ml_avg_conf  # Use same confidence for both
        items.append(
            {
                "device_id": str(d.device_id),
                "device_hash_short": d.device_hash[:8] + "..." + d.device_hash[-4:]
                if len(d.device_hash) >= 12
                else d.device_hash,
                "device_hash": d.device_hash,
                "device_trust_score": float(d.device_trust_score)
                if d.device_trust_score
                else 0,
                "total_reports": actual_total,  # Use actual count from reports
                "trusted_reports": actual_trusted,  # Use actual trusted count
                "flagged_reports": actual_flagged,  # Use actual flagged count (REJECTED column)
                "spam_flags": getattr(d, "spam_flags", 0) or 0,
                "is_banned": getattr(d, "is_banned", False) or False,
                "is_blacklisted": getattr(d, "is_blacklisted", False) or False,
                "blacklist_reason": getattr(d, "blacklist_reason", None),
                "metadata_json": getattr(d, "metadata_json", {}),  # Add metadata field
                "ml_avg_trust": float(ml_avg_trust) if ml_avg_trust is not None else None,
                "ml_fake_rate": float(ml_fake_rate) if ml_fake_rate is not None else None,
                "ml_last_prediction_at": ml_last_pred_at,  # LAST ML column
                "ml_avg_confidence": float(ml_avg_conf) if ml_avg_conf is not None else None,
                "ml_last_confidence": float(ml_last_conf) if ml_last_conf is not None else None,
                "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
                "last_active_at": last_active.isoformat() if last_active else None,  # LAST ACTIVE column
                "sector_location_id": sector_location_id,
                "sector_name": sector_name,
                "cell_location_id": cell_location_id,
                "cell_name": cell_name,
                "village_location_id": village_location_id,
                "village_name": village_name,
                "last_location": last_location,  # LAST LOCATION column
                "last_latitude": last_latitude,
                "last_longitude": last_longitude,
                "last_location_hierarchy": last_location_hierarchy,
                # Add location consistency analysis data
                "location_consistency": None,
                "movement_radius_km": None,
            }
        )
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)
    high = (
        db.query(func.count(Device.device_id))
        .filter(Device.device_trust_score >= 70)
        .scalar()
        or 0
    )
    medium = (
        db.query(func.count(Device.device_id))
        .filter(
            Device.device_trust_score >= 40, Device.device_trust_score < 70
        )
        .scalar()
        or 0
    )
    low = (
        db.query(func.count(Device.device_id))
        .filter(Device.device_trust_score < 40)
        .scalar()
        or 0
    )
    if hasattr(Device, "is_banned"):
        banned = (
            db.query(func.count(Device.device_id))
            .filter(Device.is_banned == True)
            .scalar()
            or 0
        )
    else:
        banned = 0
    # Active devices in last 30 days based on last_seen_at when available
    if hasattr(Device, "last_seen_at"):
        active_base = db.query(func.count(Device.device_id)).filter(
            Device.last_seen_at >= since_30d
        )
        if hasattr(Device, "is_banned"):
            active_base = active_base.filter(Device.is_banned == False)
        active_30d = active_base.scalar() or 0
    else:
        active_30d = (
            db.query(func.count(Device.device_id))
            .filter(Device.first_seen_at >= since_30d)
            .scalar()
            or 0
        )
        if hasattr(Device, "is_banned"):
            active_30d = (
                db.query(func.count(Device.device_id))
                .filter(
                    Device.first_seen_at >= since_30d, Device.is_banned == False
                )
                .scalar()
                or 0
            )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "active_30d": active_30d,
            "high_trust": high,
            "medium_trust": medium,
            "low_trust": low,
            "banned": banned,
        },
    }


@router.patch("/{device_id}/ban", response_model=dict)
def ban_device(
    device_id: UUID,
    background_tasks: BackgroundTasks,
    body: dict | None = None,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    db: Session = Depends(get_db),
):
    """Ban a device from reporting (admin/supervisor)."""
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not hasattr(device, "is_banned"):
        raise HTTPException(status_code=400, detail="Device ban is not supported by this schema")
    reason = None
    if isinstance(body, dict):
        reason = body.get("reason") or body.get("blacklist_reason")
    device.is_banned = True
    # Mirror into blacklist fields if present (keeps UI consistent)
    if hasattr(device, "is_blacklisted"):
        device.is_blacklisted = True
    if hasattr(device, "blacklist_reason") and reason:
        device.blacklist_reason = str(reason)[:255]
    db.commit()
    db.refresh(device)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "device"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "device"}))
    background_tasks.add_task(notify)

    return {
        "device_id": str(device.device_id),
        "is_banned": bool(getattr(device, "is_banned", False)),
        "is_blacklisted": bool(getattr(device, "is_blacklisted", False)),
        "blacklist_reason": getattr(device, "blacklist_reason", None),
    }


@router.patch("/{device_id}/unban", response_model=dict)
def unban_device(
    device_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    db: Session = Depends(get_db),
):
    """Unban a device (admin/supervisor)."""
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not hasattr(device, "is_banned"):
        raise HTTPException(status_code=400, detail="Device ban is not supported by this schema")
    device.is_banned = False
    if hasattr(device, "is_blacklisted"):
        device.is_blacklisted = False
    if hasattr(device, "blacklist_reason"):
        device.blacklist_reason = None
    db.commit()
    db.refresh(device)

    def notify():
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "device"}))
        except RuntimeError:
            asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "device"}))
    background_tasks.add_task(notify)

    return {
        "device_id": str(device.device_id),
        "is_banned": bool(getattr(device, "is_banned", False)),
        "is_blacklisted": bool(getattr(device, "is_blacklisted", False)),
        "blacklist_reason": getattr(device, "blacklist_reason", None),
    }


# ML Endpoints
@router.get("/reports/{report_id}/prediction", response_model=MLPredictionResponse)
async def get_report_prediction_endpoint(
    report_id: str,
    device_id: str = Query(..., description="Device ID"),
    db: Session = Depends(get_db)
):
    """Get ML prediction for a specific report"""
    prediction = get_report_prediction(db, report_id, device_id)
    
    if not prediction:
        raise HTTPException(status_code=404, detail="Report not found or no prediction available")
    
    return MLPredictionResponse(
        prediction_id=str(prediction.prediction_id),
        report_id=str(prediction.report_id),
        trust_score=float(prediction.trust_score),
        prediction_label=prediction.prediction_label,
        model_version=prediction.model_version,
        confidence=float(prediction.confidence),
        evaluated_at=prediction.evaluated_at.isoformat() if prediction.evaluated_at else None,
        is_final=prediction.is_final,
        explanation=prediction.explanation,
        processing_time=prediction.processing_time,
    )

@router.get("/ml-insights", response_model=List[MLInsightResponse])
async def get_home_insights_endpoint(
    db: Session = Depends(get_db)
):
    """Get ML-powered insights for the home dashboard"""
    # credibility_model.get_home_insights returns a summary dict, not a list of cards
    return get_home_insights(db)

@router.get("/{device_id}/location-history")
def get_device_location_history(
    device_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_supervisor_or_officer)],
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get device location history from device metadata.
    Returns the device's location history with analysis of movement patterns.
    """
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Get location history from device metadata
    metadata = device.metadata_json or {}
    location_history = metadata.get('location_history', [])
    
    if not location_history:
        return {
            "device_id": device_id,
            "total_locations": 0,
            "days_active": 0,
            "radius_km": 0.0,
            "activity_level": "No history",
            "locations": [],
            "current_location": None
        }
    
    # Sort by timestamp (newest first)
    location_history.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Calculate time span
    if len(location_history) >= 2:
        oldest_time = location_history[-1].get('timestamp')
        newest_time = location_history[0].get('timestamp')
        
        if oldest_time and newest_time:
            try:
                oldest_date = datetime.fromisoformat(oldest_time.replace('Z', '+00:00'))
                newest_date = datetime.fromisoformat(newest_time.replace('Z', '+00:00'))
                days_active = (newest_date - oldest_date).days
            except:
                days_active = 0
        else:
            days_active = 0
    else:
        days_active = 0
    
    # Calculate movement radius (distance from first to last location)
    radius_km = 0.0
    if len(location_history) >= 2:
        first_loc = location_history[-1]
        last_loc = location_history[0]
        
        if (first_loc.get('latitude') and first_loc.get('longitude') and 
            last_loc.get('latitude') and last_loc.get('longitude')):
            radius_km = haversine_distance(
                first_loc['latitude'], first_loc['longitude'],
                last_loc['latitude'], last_loc['longitude']
            )
    
    # Determine activity level
    total_locations = len(location_history)
    if days_active > 0:
        locations_per_day = total_locations / max(days_active, 1)
        if locations_per_day >= 3:
            activity_level = "Highly active"
        elif locations_per_day >= 1:
            activity_level = "Moderately active"
        else:
            activity_level = "Low activity"
    else:
        activity_level = "Limited data"
    
    # Get current location (most recent)
    current_location = location_history[0] if location_history else None
    
    return {
        "device_id": device_id,
        "total_locations": total_locations,
        "days_active": days_active,
        "radius_km": round(radius_km, 1),
        "activity_level": activity_level,
        "locations": location_history[:limit],  # Return limited results
        "current_location": current_location,
        "device_status": "Active reporter" if days_active < 30 else "Inactive reporter"
    }


@router.get("/{device_id}/ml-stats", response_model=DeviceMLStatsResponse)
async def get_device_ml_stats_endpoint(
    device_id: str,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_supervisor_or_officer)],
    db: Session = Depends(get_db)
):
    """Get ML statistics for a specific device"""
    stats_data = get_device_ml_stats(db, device_id)
    
    if not stats_data:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceMLStatsResponse(**stats_data)
