import json
import logging
from typing import List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from math import atan2, cos, radians, sin, sqrt

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.hotspot import Hotspot
from app.models.evidence_file import EvidenceFile
from app.models.report import Report
from app.schemas.hotspot import HotspotResponse
from app.core.village_lookup import get_village_location_info
from app.core.llm_recommendations import generate_citizen_advisory, clear_citizen_advisory_cache

logger = logging.getLogger(__name__)

# ── Improvement 5: Privacy-preserving coordinate grid ────────────────────────
# Grid precision ≈ 111 m × cos(lat) per step (0.001° ≈ 111 m at equator).
# Rounding exact coordinates to this grid prevents victim/reporter identification
# via repeated API queries while keeping the map visually accurate.
_PRIVACY_GRID_DEG = 0.001   # ≈ 111 m grid cell


def _snap_to_grid(lat: float, lon: float) -> Tuple[float, float]:
    """
    Snap a coordinate to the nearest privacy grid cell.

    Rounds both lat and lon to 3 decimal places (≈ 111 m precision).
    This preserves geographic clustering accuracy while making it impossible
    to recover exact GPS coordinates from the public API.
    """
    return round(lat / _PRIVACY_GRID_DEG) * _PRIVACY_GRID_DEG, \
           round(lon / _PRIVACY_GRID_DEG) * _PRIVACY_GRID_DEG


def _build_privacy_grid_cells(
    reports: List,
    *,
    window_start: datetime,
    window_end: datetime,
) -> List[dict]:
    """
    Aggregate report coordinates into privacy grid cells.

    Instead of returning one point per report (which can identify individuals),
    this groups all reports whose snapped coordinates match and returns:
      - The grid-cell centroid (snapped lat/lon)
      - The incident type of the most common crime in that cell
      - The count of reports in that cell
    No individual report IDs, exact coordinates, or descriptions are exposed.
    """
    cell_counts: dict = {}   # (grid_lat, grid_lon) → {"count": int, "types": {type: count}}
    for r in reports:
        reported_at = r.reported_at
        if reported_at:
            if reported_at.tzinfo is None:
                reported_at = reported_at.replace(tzinfo=timezone.utc)
            if not (window_start <= reported_at <= window_end):
                continue
        try:
            glat, glon = _snap_to_grid(float(r.latitude), float(r.longitude))
        except (TypeError, ValueError):
            continue
        key = (glat, glon)
        if key not in cell_counts:
            cell_counts[key] = {"count": 0, "types": {}}
        cell_counts[key]["count"] += 1
        type_name = r.incident_type.type_name if r.incident_type else "Unknown"
        cell_counts[key]["types"][type_name] = cell_counts[key]["types"].get(type_name, 0) + 1

    cells = []
    for (glat, glon), data in cell_counts.items():
        dominant = max(data["types"], key=data["types"].get) if data["types"] else "Unknown"
        cells.append({
            "grid_lat": glat,
            "grid_lon": glon,
            "incident_count": data["count"],
            "dominant_type": dominant,
        })
    return cells

router = APIRouter(prefix="/public/hotspots", tags=["public"])


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in meters."""
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


@router.get("/", response_model=List[HotspotResponse])
@router.get("", response_model=List[HotspotResponse])
def list_public_hotspots(
    limit: int = Query(30, ge=1, le=200),
    risk_level: Optional[str] = Query(None),
    lat: Optional[float] = Query(
        None, ge=-90, le=90, description="User latitude for nearby filtering."
    ),
    lon: Optional[float] = Query(
        None, ge=-180, le=180, description="User longitude for nearby filtering."
    ),
    radius_meters: int = Query(
        1500, ge=200, le=10000, description="Nearby filter radius in meters (from user GPS)."
    ),
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
    # `time_window_hours` tells us which reporting period the caller is interested
    # in, but hotspot clustering runs periodically (not in real-time).  Using the
    # requested window as a hard detection-time cutoff would blank the map between
    # clustering runs.  Instead we always look back at least 7 days so the map
    # continues to show the most-recently-detected clusters even when the user
    # selects a short reporting window (e.g. "last 24 h").
    effective_hours = int(time_window_hours) if time_window_hours is not None else 72
    lookback_hours = max(effective_hours, 3 * 24)   # never blank the map between runs (min 3-day floor)
    period_cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    logger.info(
        "[public_hotspots] request — time_window=%dh, lookback=%dh, "
        "lat=%s, lon=%s, radius_m=%d",
        effective_hours, lookback_hours, lat, lon, radius_meters,
    )

    query = db.query(Hotspot).options(joinedload(Hotspot.incident_type))
    query = query.filter(Hotspot.detected_at >= period_cutoff)
    query = query.order_by(Hotspot.detected_at.desc())

    if risk_level:
        rl = risk_level.strip().lower()
        aliases = {
            "critical": ["critical", "high"],
            "warning": ["active", "medium"],
            "normal": ["emerging", "low_activity", "low"],
            "high": ["high", "critical"],
            "medium": ["medium", "active"],
            "low": ["low", "low_activity", "emerging"],
        }
        allowed_levels = aliases.get(rl, [rl])
        query = query.filter(Hotspot.risk_level.in_(allowed_levels))

    hotspots = query.limit(500).all()
    if (lat is None) != (lon is None):
        raise HTTPException(
            status_code=400,
            detail="lat and lon must be provided together for nearby hotspot filtering.",
        )

    if lat is not None and lon is not None:
        nearby: List[Tuple[Hotspot, float]] = []
        for h in hotspots:
            try:
                d = _haversine_meters(
                    float(lat),
                    float(lon),
                    float(h.center_lat),
                    float(h.center_long),
                )
            except (TypeError, ValueError):
                continue
            if d <= float(radius_meters):
                nearby.append((h, d))
        nearby.sort(key=lambda item: (item[1], -int(item[0].incident_count or 0)))
        hotspots = [h for h, _ in nearby[:limit]]
        distance_by_id = {h.hotspot_id: d for h, d in nearby[:limit]}
    else:
        hotspots = hotspots[:limit]
        distance_by_id = {}
    responses = []
    hotspots_needing_advisory: List[Hotspot] = []

    for h in hotspots:
        classification = (
            "critical" if h.risk_level == "critical"
            else "active" if h.risk_level == "high"
            else "emerging" if h.risk_level == "medium"
            else "low_activity"
        )
        incident_type_name = h.incident_type.type_name if h.incident_type else None

        # Use the persisted advisory when available — avoids calling the LLM/template
        # on every mobile request.  Regenerate when missing or stale (>12 h) so
        # advisories stay current as incident counts and compositions evolve.
        advisory = h.llm_citizen_advisory
        now_utc = datetime.now(timezone.utc)
        gen_at = h.llm_generated_at
        if gen_at is not None and gen_at.tzinfo is None:
            gen_at = gen_at.replace(tzinfo=timezone.utc)
        advisory_stale = (
            not advisory
            or gen_at is None
            or (now_utc - gen_at).total_seconds() > 12 * 3600
        )
        if advisory_stale:
            incident_mix: Optional[dict] = None
            if getattr(h, "composition", None):
                try:
                    incident_mix = json.loads(h.composition)
                except Exception:
                    pass
            advisory = generate_citizen_advisory(
                classification=classification,
                incident_count=int(h.incident_count or 0),
                dominant_crime=incident_type_name,
                time_window_hours=int(h.time_window_hours or effective_hours),
                hotspot_id=h.hotspot_id,
                incident_mix=incident_mix,
            )
            # Mark for persistence so future requests can use the cached text.
            h.llm_citizen_advisory = advisory
            h.llm_provider = "api_generated"
            h.llm_generated_at = now_utc
            hotspots_needing_advisory.append(h)

        responses.append(
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
                incident_type_name=incident_type_name,
                classification=classification,
                prediction={"citizen_advisory": advisory},
                distance_meters=round(distance_by_id.get(h.hotspot_id, 0.0), 1)
                if h.hotspot_id in distance_by_id
                else None,
            )
        )

    # Persist newly generated advisories in one batch.
    if hotspots_needing_advisory:
        try:
            for h in hotspots_needing_advisory:
                db.add(h)
            db.commit()
        except Exception as _e:
            logger.warning(
                "[public_hotspots] advisory persist failed (will regenerate next request): %s", _e
            )
            db.rollback()

    logger.info(
        "[public_hotspots] returning %d hotspot(s) (advisories generated=%d)",
        len(responses), len(hotspots_needing_advisory),
    )
    return responses


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
        # Improvement 5: privacy-preserving grid cells instead of exact coordinates
        # The public endpoint must NEVER expose exact report coordinates — doing so
        # allows the exact GPS position of victims, witnesses, and anonymous reporters
        # to be recovered via repeated API queries (triangulation / correlation).
        # We aggregate reports into ~111 m grid cells and expose only the cell
        # centroid + dominant crime type + count per cell.
        time_window_hours = int(hotspot.time_window_hours or 24)
        window_end = _as_utc(hotspot.detected_at) or datetime.now(timezone.utc)
        period_start = window_end - timedelta(hours=time_window_hours)

        grid_cells = _build_privacy_grid_cells(
            hotspot.reports,
            window_start=period_start,
            window_end=window_end,
        )
        # Expose grid cells as "incident_points" — same field name, safe content
        incident_points = grid_cells
    
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
