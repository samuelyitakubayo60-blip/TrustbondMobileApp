from typing import List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.hotspot import Hotspot
from app.models.evidence_file import EvidenceFile
from app.models.report import Report
from app.schemas.hotspot import HotspotResponse
from app.core.village_lookup import get_village_location_info

router = APIRouter(prefix="/public/hotspots", tags=["public"])


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/", response_model=List[HotspotResponse])
def list_public_hotspots(
    limit: int = Query(30, ge=1, le=200),
    risk_level: Optional[str] = Query(None),
    time_window_hours: Optional[int] = Query(
        None,
        ge=1,
        le=8760,
        description="Only return clusters generated for this DBSCAN time window.",
    ),
    db: Session = Depends(get_db),
):
    """
    Public (no-auth) hotspot list for the mobile Safety Map.

    Returns recent hotspots with center coordinates, radius, incident count,
    risk level, and incident_type_name for labeling.
    """
    # Show clusters from recent DBSCAN runs; each hotspot still carries the
    # report window it was generated from in time_window_hours.
    recent_run_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    query = db.query(Hotspot).options(joinedload(Hotspot.incident_type))
    query = query.filter(Hotspot.detected_at >= recent_run_cutoff)
    query = query.order_by(Hotspot.detected_at.desc())
    
    if risk_level:
        query = query.filter(Hotspot.risk_level == risk_level)
    if time_window_hours is not None:
        query = query.filter(Hotspot.time_window_hours == int(time_window_hours))
    hotspots = query.limit(limit).all()
    return [
        HotspotResponse(
            hotspot_id=h.hotspot_id,
            center_lat=h.center_lat,
            center_long=h.center_long,
            radius_meters=h.radius_meters,
            incident_count=h.incident_count,
            risk_level=h.risk_level,
            time_window_hours=h.time_window_hours,
            detected_at=h.detected_at,
            incident_type_id=h.incident_type_id,
            incident_type_name=h.incident_type.type_name if h.incident_type else None,
            classification=(
                "critical"
                if h.risk_level == "critical"
                else "active"
                if h.risk_level == "high"
                else "emerging"
                if h.risk_level == "medium"
                else "low_activity"
            ),
        )
        for h in hotspots
    ]


@router.get("/{hotspot_id}", response_model=HotspotResponse)
def get_hotspot_details(
    hotspot_id: int,
    db: Session = Depends(get_db),
):
    """
    Get detailed information about a specific hotspot including:
    - Geographic information
    - Risk level computation details
    - Associated reports
    - Incident type distribution
    - Evidence files from all reports in this hotspot
    """
    hotspot = db.query(Hotspot).options(
        joinedload(Hotspot.incident_type),
        joinedload(Hotspot.reports)
    ).filter(
        Hotspot.hotspot_id == hotspot_id
    ).first()
    
    if not hotspot:
        raise HTTPException(status_code=404, detail="Hotspot not found")
    
    # Get all evidence files from reports in this hotspot
    evidence_files = []
    incident_points = []
    
    if hotspot.reports:
        # Extract report IDs from the relationship
        report_ids = [report.report_id for report in hotspot.reports]
        # Get evidence files for all reports in this hotspot
        evidence_files = db.query(EvidenceFile).filter(
            EvidenceFile.report_id.in_(report_ids)
        ).all()
        
        # Create incident points with location data for the same report period
        # used when this DBSCAN hotspot was generated.
        time_window_hours = int(hotspot.time_window_hours or 24)
        window_end = _as_utc(hotspot.detected_at) or datetime.now(timezone.utc)
        period_start = window_end - timedelta(hours=time_window_hours)
        
        for r in hotspot.reports:
            reported_at = _as_utc(r.reported_at)
            if reported_at and period_start <= reported_at <= window_end:
                # Get location hierarchy using the village lookup utility
                location_info = get_village_location_info(db, float(r.latitude), float(r.longitude))
                
                incident_points.append(
                    {
                        "report_id": str(r.report_id),
                        "incident_type_name": r.incident_type.type_name if r.incident_type else None,
                        "description": r.description,
                        "latitude": float(r.latitude),
                        "longitude": float(r.longitude),
                        "reported_at": r.reported_at.isoformat() if r.reported_at else None,
                        "trust_score": None,  # Public endpoint doesn't include ML predictions
                        "village_name": location_info.get("village_name") if location_info else None,
                        "cell_name": location_info.get("cell_name") if location_info else None,
                        "sector_name": location_info.get("sector_name") if location_info else None,
                    }
                )
    
    return HotspotResponse(
        hotspot_id=hotspot.hotspot_id,
        center_lat=hotspot.center_lat,
        center_long=hotspot.center_long,
        radius_meters=hotspot.radius_meters,
        incident_count=hotspot.incident_count,
        risk_level=hotspot.risk_level,
        time_window_hours=hotspot.time_window_hours,
        detected_at=hotspot.detected_at,
        incident_type_id=hotspot.incident_type_id,
        incident_type_name=hotspot.incident_type.type_name if hotspot.incident_type else None,
        classification=(
            "critical"
            if hotspot.risk_level == "critical"
            else "active"
            if hotspot.risk_level == "high"
            else "emerging"
            if hotspot.risk_level == "medium"
            else "low_activity"
        ),
        evidence_files=[
            {
                "evidence_id": str(evidence.evidence_id),
                "file_url": evidence.file_url,
                "file_type": evidence.file_type,
                "file_size": evidence.file_size,
                "duration": evidence.duration,
                "media_latitude": float(evidence.media_latitude) if evidence.media_latitude else None,
                "media_longitude": float(evidence.media_longitude) if evidence.media_longitude else None,
                "captured_at": evidence.captured_at.isoformat() if evidence.captured_at else None,
                "uploaded_at": evidence.uploaded_at.isoformat() if evidence.uploaded_at else None,
                "is_live_capture": evidence.is_live_capture,
                "quality_label": evidence.quality_label.value if evidence.quality_label else None,
                "cloudinary_url": evidence.cloudinary_url,
                "report_id": str(evidence.report_id)
            }
            for evidence in evidence_files
        ],
        incident_points=incident_points
    )
