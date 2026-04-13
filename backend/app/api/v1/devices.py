from typing import Annotated, Optional, List

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
from app.schemas.device import DeviceCreate, DeviceResponse
from app.api.v1.auth import get_current_admin_or_supervisor
from app.models.police_user import PoliceUser
from app.schemas.ml import MLPredictionResponse, MLInsightResponse, DeviceMLStatsResponse
from app.core.credibility_model import (
    get_report_prediction,
    get_home_insights,
    get_device_ml_stats
)

router = APIRouter(prefix="/devices", tags=["devices"])


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
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
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
    """List devices with trust stats for police dashboard. Admin/supervisor only."""
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
        last_report = None
        last_active = getattr(d, "last_seen_at", None)
        sector_location_id = None
        sector_name = None
        ml_avg_trust = None
        ml_fake_rate = None
        ml_last_pred_at = None
        ml_avg_conf = None
        ml_last_conf = None
        try:
            meta = getattr(d, "metadata_json", None)
            if isinstance(meta, dict) and isinstance(meta.get("ml"), dict):
                ml = meta.get("ml") or {}
                ml_avg_trust = ml.get("avg_trust_score")
                ml_fake_rate = ml.get("fake_rate")
                ml_last_pred_at = ml.get("last_prediction_at")
                ml_avg_conf = ml.get("avg_confidence")
                ml_last_conf = ml.get("last_confidence")
        except Exception:
            ml_avg_trust = None
            ml_fake_rate = None
            ml_last_pred_at = None
            ml_avg_conf = None
            ml_last_conf = None
        # Fallback to most recent report if last_seen_at is not yet populated
        if last_active is None:
            last_report = (
                db.query(Report)
                .options(joinedload(Report.village_location))
                .filter(Report.device_id == d.device_id)
                .order_by(Report.reported_at.desc())
                .first()
            )
            if last_report:
                last_active = last_report.reported_at
                if last_report.village_location:
                    sector_location_id = last_report.village_location.location_id
                    sector_name = last_report.village_location.location_name
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
                "total_reports": d.total_reports or 0,
                "trusted_reports": d.trusted_reports or 0,
                "flagged_reports": d.flagged_reports or 0,
                "spam_flags": getattr(d, "spam_flags", 0) or 0,
                "is_banned": getattr(d, "is_banned", False) or False,
                "is_blacklisted": getattr(d, "is_blacklisted", False) or False,
                "blacklist_reason": getattr(d, "blacklist_reason", None),
                "metadata_json": getattr(d, "metadata_json", {}),  # Add metadata field
                "ml_avg_trust": float(ml_avg_trust) if ml_avg_trust is not None else None,
                "ml_fake_rate": float(ml_fake_rate) if ml_fake_rate is not None else None,
                "ml_last_prediction_at": ml_last_pred_at,
                "ml_avg_confidence": float(ml_avg_conf) if ml_avg_conf is not None else None,
                "ml_last_confidence": float(ml_last_conf) if ml_last_conf is not None else None,
                "first_seen_at": d.first_seen_at.isoformat() if d.first_seen_at else None,
                "last_active_at": last_active.isoformat() if last_active else None,
                "sector_location_id": sector_location_id,
                "sector_name": sector_name,
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

@router.get("/{device_id}/ml-stats", response_model=DeviceMLStatsResponse)
async def get_device_ml_stats_endpoint(
    device_id: str,
    db: Session = Depends(get_db)
):
    """Get ML statistics for a specific device"""
    stats_data = get_device_ml_stats(db, device_id)
    
    if not stats_data:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceMLStatsResponse(**stats_data)
