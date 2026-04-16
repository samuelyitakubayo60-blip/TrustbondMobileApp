from typing import Annotated, List, Optional, Dict, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from datetime import datetime, timezone
from pydantic import BaseModel

from app.core.cluster_classifier import predict_cluster_classification
from app.database import get_db
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.report import Report
from app.api.v1.auth import get_current_user, get_current_admin_or_supervisor
from app.models.police_user import PoliceUser
from app.schemas.hotspot import HotspotResponse, HotspotIncidentResponse
from app.schemas.report import EvidenceFileResponse
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    DEFAULT_TIME_WINDOW_HOURS,
    DEFAULT_MIN_INCIDENTS,
    DEFAULT_RADIUS_METERS,
    DEFAULT_TRUST_MIN,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from app.core.village_lookup import get_village_location_info

router = APIRouter(prefix="/hotspots", tags=["hotspots"])

def _classify_hotspot(hotspot_score: float) -> str:
    """Classify hotspot based on trust-weighted DBSCAN score (0-100).

    TrustBond spec labels (matching hotspot_risk_level output variable):
      - low_activity : score < 40   -> low risk / normal
      - emerging     : 40 <= score < 60  -> emerging hotspot
      - active       : 60 <= score < 80  -> active hotspot (high risk)
      - critical     : score >= 80   -> critical hotspot
    """
    if hotspot_score >= 80:
        return "critical"
    if hotspot_score >= 60:
        return "active"
    if hotspot_score >= 40:
        return "emerging"
    return "low_activity"


def _dbscan_hotspot_score(
    incident_count: int,
    avg_trust: float,
    cluster_density: float,
    time_window_hours: int,
) -> float:
    """Compute a 0-100 trust-weighted hotspot score aligned with DBSCAN output.

    Components
    ----------
    incident_score : incident_count weighted by avg_trust (0-1 scale).
        Capped at 40 pts.
    density_score  : cluster density proxy normalized to 0-30 pts.
    recency_score  : tighter windows + trusted reports increase score (0-30 pts).
    """
    trust_weight = max(0.0, min(1.0, avg_trust / 100.0))
    incident_score = min(40.0, incident_count * 4.0 * trust_weight)

    density_score = min(30.0, cluster_density * 3.0)

    recency_factor = max(0.1, 24.0 / max(1, time_window_hours))
    recency_score = min(30.0, incident_count * recency_factor * trust_weight * 2)

    return round(min(100.0, incident_score + density_score + recency_score), 2)


class RecomputeHotspotsPayload(BaseModel):
    time_window_hours: Optional[int] = None
    min_incidents: Optional[int] = None
    radius_meters: Optional[float] = None
    trust_min: Optional[float] = None
    incident_type_id: Optional[int] = None


def _prediction_for_hotspot(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    crime_label = dominant_crime or "incident"
    area_text = area_label or "this area"

    if cluster_kind == "mixed_hotspot":
        mix_text = ""
        if incident_mix:
            top_mix = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:3]
            mix_text = ", ".join([f"{name}: {count}" for name, count in top_mix])
        return {
            "status": "security_alert",
            "predicted_increase_pct": min(85, 30 + incident_count * 4),
            "peak_time": "17:00-23:00",
            "recommendation": f"Mixed incidents co-located in {area_text}. Trigger coordinated security response.",
            "narrative": f"Different incident types are converging in {area_text}{f' ({mix_text})' if mix_text else ''}.",
        }

    if classification == "critical":
        return {
            "status": "escalation_likely",
            "predicted_increase_pct": min(75, 20 + incident_count * 4),
            "peak_time": "18:00-23:00",
            "recommendation": f"Deploy patrol units around {crime_label} cluster in {area_text}",
            "narrative": f"{crime_label.capitalize()} is rapidly escalating in {area_text}.",
        }
    if classification == "active":
        return {
            "status": "monitor_growth",
            "predicted_increase_pct": min(40, 10 + incident_count * 2),
            "peak_time": "17:00-21:00",
            "recommendation": "Increase monitoring and community patrol checks",
            "narrative": f"{crime_label.capitalize()} is increasing in {area_text}.",
        }
    return {
        "status": "emerging_trend",
        "predicted_increase_pct": min(25, 5 + incident_count * 2),
        "peak_time": None,
        "recommendation": f"Track early signals of {crime_label} in {area_text}",
        "narrative": f"Early pattern detected: {crime_label} may be emerging in {area_text}.",
    }


def _convex_hull(points: List[tuple[float, float]]) -> List[List[float]]:
    """Return hull as [[lat, lon], ...] using monotonic chain."""
    if len(points) < 3:
        return [[lat, lon] for lat, lon in points]

    pts = sorted(points, key=lambda p: (p[1], p[0]))

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[1] - o[1]) * (b[0] - o[0]) - (a[0] - o[0]) * (b[1] - o[1])

    lower: List[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: List[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    return [[lat, lon] for lat, lon in hull]


def _expand_hull(hull: List[List[float]], factor: float = 0.12) -> List[List[float]]:
    if len(hull) < 3:
        return hull
    c_lat = sum(p[0] for p in hull) / len(hull)
    c_lon = sum(p[1] for p in hull) / len(hull)
    out: List[List[float]] = []
    for lat, lon in hull:
        out.append([
            c_lat + (lat - c_lat) * (1 + factor),
            c_lon + (lon - c_lon) * (1 + factor),
        ])
    return out


@router.get("/", response_model=List[HotspotResponse])
def list_hotspots(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    risk_level: Optional[str] = Query(
        None, description="Filter by risk_level (low, medium, high, critical)."
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """List hotspots.

    - Admin: sees all hotspots.
    - Supervisor: hotspots that include at least one report in their assigned_location_id (if set).
    - Officer: same sector scoping as supervisor when assigned_location_id is set, otherwise all.
    """
    query = db.query(Hotspot).options(
        joinedload(Hotspot.incident_type),
        selectinload(Hotspot.reports).selectinload(Report.ml_predictions),
        selectinload(Hotspot.reports).joinedload(Report.village_location),
        selectinload(Hotspot.reports).joinedload(Report.incident_type),
        selectinload(Hotspot.reports).selectinload(Report.evidence_files),
    )

    role = getattr(current_user, "role", None)
    assigned_loc = getattr(current_user, "assigned_location_id", None)

    # Scope for supervisors/officers by station sector
    if role == "officer":
        officer_station_id = getattr(current_user, "station_id", None)
        if officer_station_id is None:
            raise HTTPException(status_code=403, detail="Officer station is not configured")
        
        # Get station to find its sector location
        from app.models.station import Station
        from app.models.location import Location
        from sqlalchemy import or_
        
        station = db.query(Station).filter(Station.station_id == officer_station_id).first()
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
            
            # Filter hotspots to include reports from officer's station sector
            query = (
                query.join(Hotspot.reports)
                .filter(Report.village_location_id.in_(sector_location_ids))
                .distinct()
            )
    elif role == "supervisor":
        supervisor_station_id = getattr(current_user, "station_id", None)
        if supervisor_station_id is None:
            raise HTTPException(status_code=403, detail="Supervisor station is not configured")
        
        # Get station to find its sector location
        from app.models.station import Station
        from app.models.location import Location
        from sqlalchemy import or_
        
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
            
            # Filter hotspots to include reports from supervisor's sector
            query = (
                query.join(Hotspot.reports)
                .filter(Report.village_location_id.in_(sector_location_ids))
                .distinct()
            )

    query = query.order_by(Hotspot.detected_at.desc())
    if risk_level:
        query = query.filter(Hotspot.risk_level == risk_level)
    hotspots = query.limit(limit).all()
    
    responses = []
    
    for h in hotspots:
        # Defensive filter: only consider reports mapped to covered village locations.
        reports_in_cluster = [
            r
            for r in (getattr(h, "reports", None) or [])
            if getattr(r, "village_location_id", None) is not None
            and getattr(r, "village_location", None) is not None
        ]
        if not reports_in_cluster:
            continue

        incident_count = len(reports_in_cluster)

        # Collect per-report trust scores from ML predictions first;
        # fall back to 50 (neutral) for reports without a prediction.
        pre_trust_scores: List[float] = []
        for r in reports_in_cluster:
            preds = list(getattr(r, "ml_predictions", None) or [])
            final_p = [p for p in preds if getattr(p, "is_final", False)]
            src_p = final_p if final_p else preds
            src_p.sort(
                key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            if src_p and getattr(src_p[0], "trust_score", None) is not None:
                pre_trust_scores.append(float(src_p[0].trust_score))
            else:
                pre_trust_scores.append(50.0)

        avg_pre_trust = (
            sum(pre_trust_scores) / len(pre_trust_scores) if pre_trust_scores else 50.0
        )

        # Cluster density proxy: incident_count / (pi*r^2) in points per sq-km.
        radius_m = float(getattr(h, "radius_meters", 500) or 500)
        area_sqkm = max(0.001, 3.14159 * (radius_m / 1000.0) ** 2)
        cluster_density = incident_count / area_sqkm

        time_window_hours = int(getattr(h, "time_window_hours", 24) or 24)

        hotspot_score = _dbscan_hotspot_score(
            incident_count=incident_count,
            avg_trust=avg_pre_trust,
            cluster_density=cluster_density,
            time_window_hours=time_window_hours,
        )
        classification_result = predict_cluster_classification(
            incident_count=incident_count,
            avg_trust=avg_pre_trust,
            cluster_density=cluster_density,
            time_window_hours=time_window_hours,
        )
        hotspot_score = float(classification_result["hotspot_score"])
        classification = str(classification_result["classification"])
        classification_confidence = classification_result.get("confidence")
        classification_source = str(classification_result.get("source") or "dbscan_fallback")
        lifecycle_state = classification

        ml_scores: List[float] = []
        cluster_points: List[tuple[float, float]] = []
        incident_points: List[Dict[str, Any]] = []
        incident_mix: Dict[str, int] = {}
        area_counts: Dict[str, int] = {}
        for r in reports_in_cluster:
            try:
                cluster_points.append((float(r.latitude), float(r.longitude)))
            except Exception:
                pass

            incident_name = r.incident_type.type_name if r.incident_type else "Unknown"
            incident_mix[incident_name] = incident_mix.get(incident_name, 0) + 1

            if getattr(r, "village_location", None) and r.village_location.location_name:
                area_name = str(r.village_location.location_name)
                area_counts[area_name] = area_counts.get(area_name, 0) + 1

            report_preds = list(getattr(r, "ml_predictions", None) or [])
            final_preds = [p for p in report_preds if getattr(p, "is_final", False)]
            src_preds = final_preds if final_preds else report_preds
            src_preds.sort(
                key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            report_trust = None
            if src_preds and getattr(src_preds[0], "trust_score", None) is not None:
                report_trust = float(src_preds[0].trust_score)

            # Get location hierarchy using the village lookup utility
            location_info = get_village_location_info(db, float(r.latitude), float(r.longitude))
            
            incident_points.append(
                {
                    "report_id": str(r.report_id),
                    "incident_type_name": incident_name,
                    "description": r.description,
                    "latitude": float(r.latitude),
                    "longitude": float(r.longitude),
                    "reported_at": r.reported_at.isoformat() if r.reported_at else None,
                    "trust_score": report_trust,
                    "village_name": location_info.get("village_name") if location_info else None,
                    "cell_name": location_info.get("cell_name") if location_info else None,
                    "sector_name": location_info.get("sector_name") if location_info else None,
                    "evidence_files": [
                        {
                            "evidence_id": str(e.evidence_id),
                            "file_type": e.file_type,
                            "file_url": e.file_url,
                            "uploaded_at": e.uploaded_at.isoformat() if e.uploaded_at else None,
                        }
                        for e in (r.evidence_files or [])
                    ],
                }
            )

            for p in (getattr(r, "ml_predictions", None) or []):
                if getattr(p, "is_final", False) and getattr(p, "trust_score", None) is not None:
                    ml_scores.append(float(p.trust_score))
        avg_trust_score = (
            round(sum(ml_scores) / len(ml_scores), 2)
            if ml_scores
            else round(avg_pre_trust, 2)
        )
        boundary_points = _expand_hull(_convex_hull(cluster_points)) if cluster_points else []

        dominant_crime = h.incident_type.type_name if h.incident_type else None
        area_label = None
        if area_counts:
            area_label = sorted(area_counts.items(), key=lambda x: x[1], reverse=True)[0][0]

        cluster_kind = "trend_cluster" if len(incident_mix) <= 1 else "mixed_hotspot"

        prediction = _prediction_for_hotspot(
            classification,
            incident_count,
            dominant_crime,
            cluster_kind,
            area_label,
            incident_mix,
        )
            
        responses.append(HotspotResponse(
            hotspot_id=h.hotspot_id,
            center_lat=h.center_lat,
            center_long=h.center_long,
            radius_meters=h.radius_meters,
            incident_count=incident_count,
            risk_level=h.risk_level,
            time_window_hours=h.time_window_hours,
            detected_at=h.detected_at,
            incident_type_id=h.incident_type_id,
            incident_type_name=h.incident_type.type_name if h.incident_type else None,
            evidence_files=[
                {
                    "evidence_id": str(e.evidence_id),
                    "file_type": e.file_type,
                    "file_url": e.file_url,
                    "uploaded_at": e.uploaded_at.isoformat() if e.uploaded_at else None,
                }
                for r in h.reports
                for e in (r.evidence_files or [])
            ],
            lifecycle_state=lifecycle_state,
            hotspot_score=hotspot_score,
            classification=classification,
            classification_confidence=(
                float(classification_confidence)
                if classification_confidence is not None
                else None
            ),
            classification_source=classification_source,
            avg_trust_score=avg_trust_score,
            dominant_crime_type=dominant_crime,
            cluster_kind=cluster_kind,
            area_label=area_label,
            incident_mix=incident_mix,
            prediction=prediction,
            boundary_points=boundary_points,
            incident_points=incident_points,
        ))
        
    return responses


@router.get("/params")
def get_hotspot_params(db: Session = Depends(get_db)):
    """
    Return default hotspot (DBSCAN-like) parameters used by the auto-creation job.
    """
    # Pulled from system_config when present; otherwise defaults are returned.
    tw, mi, rm = get_hotspot_params_from_db(
        db,
        time_window_hours=DEFAULT_TIME_WINDOW_HOURS,
        min_incidents=DEFAULT_MIN_INCIDENTS,
        radius_meters=DEFAULT_RADIUS_METERS,
    )
    return {
        "time_window_hours": tw,
        "min_incidents": mi,
        "radius_meters": float(rm),
        "trust_min": float(get_hotspot_trust_min_from_db(db, DEFAULT_TRUST_MIN)),
    }


@router.post("/recompute")
def recompute_hotspots(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    payload: Optional[RecomputeHotspotsPayload] = None,
    time_window_hours: Optional[int] = Query(None),
    min_incidents: Optional[int] = Query(None),
    radius_meters: Optional[float] = Query(None),
    trust_min: Optional[float] = Query(None),
    incident_type_id: Optional[int] = Query(None),
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

    cfg_tw, cfg_min, cfg_rad = get_hotspot_params_from_db(
        db,
        time_window_hours=DEFAULT_TIME_WINDOW_HOURS,
        min_incidents=DEFAULT_MIN_INCIDENTS,
        radius_meters=DEFAULT_RADIUS_METERS,
    )
    cfg_trust = get_hotspot_trust_min_from_db(db, DEFAULT_TRUST_MIN)

    # Force 24-hour time window for Safety Map consistency
    eff_tw = 24  # Always use 24 hours regardless of config or payload
    eff_min = (
        payload.min_incidents
        if payload and payload.min_incidents is not None
        else min_incidents
        if min_incidents is not None
        else cfg_min
    )
    eff_rad = (
        payload.radius_meters
        if payload and payload.radius_meters is not None
        else radius_meters
        if radius_meters is not None
        else cfg_rad
    )
    eff_trust = (
        payload.trust_min
        if payload and payload.trust_min is not None
        else trust_min
        if trust_min is not None
        else cfg_trust
    )
    eff_incident_type_id = (
        payload.incident_type_id
        if payload and payload.incident_type_id is not None
        else incident_type_id
    )

    created = create_hotspots_from_reports(
        db,
        time_window_hours=eff_tw,
        min_incidents=eff_min,
        radius_meters=eff_rad,
        trust_min=eff_trust,
        incident_type_id=eff_incident_type_id,
        analyze_all_reports=False,  # Use time-filtered reports for 24-hour consistency
    )
    
    # Broadcast hotspot update to all connected clients for real-time Safety Map updates
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "hotspot", "action": "recomputed"})
    
    return {
        "created": created,
        "params": {
            "time_window_hours": eff_tw,
            "min_incidents": eff_min,
            "radius_meters": float(eff_rad),
            "trust_min": float(eff_trust),
            "incident_type_id": eff_incident_type_id,
        },
    }


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


@router.get("/{hotspot_id}/incidents", response_model=List[HotspotIncidentResponse])
def get_hotspot_incidents(
    hotspot_id: int,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return real incident reports that formed the selected hotspot."""
    hotspot = (
        db.query(Hotspot)
        .options(
            selectinload(Hotspot.reports).joinedload(Report.incident_type),
            selectinload(Hotspot.reports).selectinload(Report.ml_predictions),
        )
        .filter(Hotspot.hotspot_id == hotspot_id)
        .first()
    )
    if not hotspot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hotspot not found")

    incidents: List[HotspotIncidentResponse] = []
    for r in hotspot.reports or []:
        preds = list(getattr(r, "ml_predictions", None) or [])
        final_preds = [p for p in preds if getattr(p, "is_final", False)]
        source_preds = final_preds if final_preds else preds
        source_preds.sort(
            key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        trust_score = None
        if source_preds and getattr(source_preds[0], "trust_score", None) is not None:
            trust_score = float(source_preds[0].trust_score)

        incidents.append(
            HotspotIncidentResponse(
                report_id=str(r.report_id),
                incident_type_name=r.incident_type.type_name if r.incident_type else None,
                description=r.description,
                latitude=r.latitude,
                longitude=r.longitude,
                reported_at=r.reported_at,
                rule_status=r.rule_status,
                verification_status=r.verification_status,
                trust_score=trust_score,
            )
        )

    incidents.sort(
        key=lambda i: i.reported_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return incidents
