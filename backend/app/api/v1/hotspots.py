from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.report import Report
from app.api.v1.auth import get_current_user, get_current_admin_or_supervisor
from app.models.police_user import PoliceUser
from app.schemas.hotspot import HotspotResponse
from app.schemas.report import EvidenceFileResponse
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    DEFAULT_TIME_WINDOW_HOURS,
    DEFAULT_MIN_INCIDENTS,
    DEFAULT_RADIUS_METERS,
)

router = APIRouter(prefix="/hotspots", tags=["hotspots"])


@router.get("/", response_model=List[HotspotResponse])
def list_hotspots(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    risk_level: Optional[str] = Query(
        None, description="Filter by risk_level (low, medium, high)."
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """List hotspots.

    - Admin: sees all hotspots.
    - Supervisor: hotspots that include at least one report in their assigned_location_id (if set).
    - Officer: same sector scoping as supervisor when assigned_location_id is set, otherwise all.
    """
    query = db.query(Hotspot).options(joinedload(Hotspot.incident_type))

    role = getattr(current_user, "role", None)
    assigned_loc = getattr(current_user, "assigned_location_id", None)

    # Scope for supervisors/officers by assigned_location_id, if configured
    if role in ("supervisor", "officer") and assigned_loc:
        query = (
            query.join(Hotspot.reports)
            .filter(Report.village_location_id == assigned_loc)
            .distinct()
        )

    query = query.order_by(Hotspot.detected_at.desc())
    if risk_level:
        query = query.filter(Hotspot.risk_level == risk_level)
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
        )
        for h in hotspots
    ]


@router.get("/params")
def get_hotspot_params():
    """
    Return default hotspot (DBSCAN-like) parameters used by the auto-creation job.
    """
    return {
        "time_window_hours": DEFAULT_TIME_WINDOW_HOURS,
        "min_incidents": DEFAULT_MIN_INCIDENTS,
        "radius_meters": float(DEFAULT_RADIUS_METERS),
    }


@router.post("/recompute")
def recompute_hotspots(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    min_incidents: int = DEFAULT_MIN_INCIDENTS,
    radius_meters: float = float(DEFAULT_RADIUS_METERS),
):
    """
    Recompute hotspots from recent reports using supplied parameters.

    Admin/supervisor only. This clears existing hotspots and hotspot_reports
    before running the auto-creation job, so the map reflects the new
    clustering configuration.
    """
    # Clear existing hotspots + link table
    db.execute(hotspot_reports_table.delete())
    db.query(Hotspot).delete()
    db.commit()

    created = create_hotspots_from_reports(
        db,
        time_window_hours=time_window_hours,
        min_incidents=min_incidents,
        radius_meters=radius_meters,
    )
    return {"created": created}


@router.get("/{hotspot_id}/evidence", response_model=List[EvidenceFileResponse])
def get_hotspot_evidence(
    hotspot_id: int,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
):
    """Return all evidence files from all reports that contributed to this hotspot."""
    hotspot = (
        db.query(Hotspot)
        .options(selectinload(Hotspot.reports).selectinload(Report.evidence_files))
        .filter(Hotspot.hotspot_id == hotspot_id)
        .first()
    )
    if not hotspot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotspot not found")

    evidence_items: List[EvidenceFileResponse] = []
    for r in hotspot.reports or []:
        for ef in r.evidence_files or []:
            evidence_items.append(
                EvidenceFileResponse(
                    evidence_id=ef.evidence_id,
                    report_id=ef.report_id,
                    file_url=ef.file_url,
                    file_type=ef.file_type,
                    uploaded_at=ef.uploaded_at,
                    media_latitude=ef.media_latitude,
                    media_longitude=ef.media_longitude,
                )
            )

    evidence_items.sort(key=lambda e: (e.uploaded_at is None, e.uploaded_at))
    return evidence_items
