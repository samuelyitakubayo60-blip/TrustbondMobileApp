import json
from typing import Annotated, List, Optional, Dict, Any
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session, joinedload, selectinload
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.core.cluster_classifier import predict_cluster_classification
from app.database import get_db
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.report import Report
from app.api.v1.auth import get_current_user, get_current_admin_or_supervisor
from app.models.police_user import PoliceUser
from app.schemas.hotspot import HotspotResponse, HotspotIncidentResponse, HotspotDeployRequest
from app.schemas.report import EvidenceFileResponse
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    ensure_hotspots_materialized,
    DEFAULT_TIME_WINDOW_HOURS,
    DEFAULT_MIN_INCIDENTS,
    DEFAULT_RADIUS_METERS,
    DEFAULT_TRUST_MIN,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from app.core.village_lookup import get_village_location_info
from app.core.websocket import manager
from app.core.llm_recommendations import (
    generate_recommendation,
    clear_recommendation_cache,
    load_hotspot_deployment_units,
    gather_cluster_case_context,
)

router = APIRouter(prefix="/hotspots", tags=["hotspots"])


def _deployment_fields_for_hotspot(db: Session, h: Hotspot) -> dict:
    from app.models.special_assignment_unit import SpecialAssignmentUnit

    unit_name = None
    code = getattr(h, "assigned_unit_code", None)
    if code:
        row = (
            db.query(SpecialAssignmentUnit.unit_name)
            .filter(SpecialAssignmentUnit.unit_code == code)
            .first()
        )
        unit_name = row[0] if row else code
    controlled_name = None
    ctrl = getattr(h, "controlled_by", None)
    if ctrl:
        parts = [ctrl.first_name or "", ctrl.last_name or ""]
        controlled_name = " ".join(p for p in parts if p).strip() or ctrl.email
    elif getattr(h, "controlled_by_user_id", None):
        u = db.query(PoliceUser).filter(PoliceUser.police_user_id == h.controlled_by_user_id).first()
        if u:
            parts = [u.first_name or "", u.last_name or ""]
            controlled_name = " ".join(p for p in parts if p).strip() or u.email
    return {
        "assigned_unit_code": code,
        "assigned_unit_name": unit_name,
        "deployed_at": getattr(h, "deployed_at", None),
        "deployment_note": getattr(h, "deployment_note", None),
        "controlled_by_user_id": getattr(h, "controlled_by_user_id", None),
        "controlled_by_name": controlled_name,
    }


def _station_covered_village_ids(db: Session, station_id: int) -> List[int]:
    """Return village ids covered by a station via station_coverage_cells."""
    from app.models.station_coverage import StationCoverageCell
    from app.models.location import Location

    cell_rows = (
        db.query(StationCoverageCell.cell_location_id)
        .filter(StationCoverageCell.station_id == station_id)
        .all()
    )
    cell_ids = [int(r[0]) for r in cell_rows if r and r[0] is not None]
    if not cell_ids:
        return []

    village_rows = (
        db.query(Location.location_id)
        .filter(
            Location.location_type == "village",
            Location.parent_location_id.in_(cell_ids),
        )
        .all()
    )
    return sorted({int(r[0]) for r in village_rows if r and r[0] is not None})


def _apply_officer_hotspot_scope(query, db: Session, current_user: PoliceUser):
    """Station commanders see hotspots in their station coverage; DPC and IO see district-wide."""
    role = getattr(current_user, "role", None)
    if role != "officer":
        return query
    officer_station_id = getattr(current_user, "station_id", None)
    if officer_station_id is None:
        raise HTTPException(status_code=403, detail="Officer station is not configured")
    covered_village_ids = _station_covered_village_ids(db, officer_station_id)
    if covered_village_ids:
        return (
            query.join(Hotspot.reports)
            .filter(Report.village_location_id.in_(covered_village_ids))
            .distinct()
        )
    return query.filter(False)


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
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


def _coalesce_param(body_value, query_value, default_value):
    if body_value is not None:
        return body_value
    if query_value is not None:
        return query_value
    return default_value


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hours_between(start: datetime, end: datetime) -> int:
    seconds = max(1.0, (end - start).total_seconds())
    return max(1, int((seconds + 3599) // 3600))


def _compute_peak_window(report_times: List[datetime]) -> Optional[str]:
    """Derive a real 2-hour peak window from report timestamps.

    Counts incidents per hour-of-day across all reports, finds the hour
    with the highest count, and returns a "HH:00–HH+2:00" string.
    Returns None when fewer than 2 timestamps are available.
    """
    if len(report_times) < 2:
        return None
    hour_counts: Dict[int, int] = {}
    for dt in report_times:
        try:
            h = dt.astimezone(timezone.utc).hour
        except Exception:
            h = dt.hour
        hour_counts[h] = hour_counts.get(h, 0) + 1
    peak_hour = max(hour_counts, key=lambda h: hour_counts[h])
    end_hour = (peak_hour + 2) % 24
    return f"{peak_hour:02d}:00\u2013{end_hour:02d}:00"


def _prediction_for_hotspot(
    classification: str,
    incident_count: int,
    cluster_kind: str,
    report_times: Optional[List[datetime]] = None,
) -> Dict[str, Any]:
    """Return only the computed numeric fields; text fields (recommendation,
    narrative, status) are always provided by generate_recommendation()."""
    peak_time = _compute_peak_window(report_times or [])

    if cluster_kind == "mixed_hotspot":
        predicted_increase_pct = min(85, 30 + incident_count * 4)
    elif classification == "critical":
        predicted_increase_pct = min(75, 20 + incident_count * 4)
    elif classification == "active":
        predicted_increase_pct = min(40, 10 + incident_count * 2)
    else:
        predicted_increase_pct = min(25, 5 + incident_count * 2)

    return {
        "predicted_increase_pct": predicted_increase_pct,
        "peak_time": peak_time,
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
    time_period: Optional[str] = Query(
        None, description="Filter by time period: 'day', 'week', 'month', 'quarter', 'year'"
    ),
    hours_back: Optional[int] = Query(
        None, description="Custom time filter: show hotspots from last N hours"
    ),
    time_window_hours: Optional[int] = Query(
        None,
        ge=1,
        le=8760,
        description="Only return clusters generated for this DBSCAN time window.",
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """List hotspots.

    - Admin / IO (supervisor): all hotspots district-wide.
    - Officer: hotspots with at least one report in their station cell coverage.
    """
    try:
        ensure_hotspots_materialized(db)
    except Exception as exc:
        logger.warning("Hotspot materialization skipped: %s", exc)

    query = db.query(Hotspot).options(
        joinedload(Hotspot.incident_type),
        joinedload(Hotspot.controlled_by),
        selectinload(Hotspot.reports).selectinload(Report.ml_predictions),
        selectinload(Hotspot.reports).joinedload(Report.village_location),
        selectinload(Hotspot.reports).joinedload(Report.incident_type),
        selectinload(Hotspot.reports).selectinload(Report.evidence_files),
    )

    # Apply time-based filtering
    if time_period or hours_back:
        time_filter_hours = None
        if hours_back:
            time_filter_hours = hours_back
        elif time_period:
            time_mapping = {
                'day': 24,
                'week': 24 * 7,
                'month': 24 * 30,
                'quarter': 24 * 90,
                'year': 24 * 365
            }
            time_filter_hours = time_mapping.get(time_period.lower())
            if time_filter_hours is None:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid time_period. Use: {', '.join(time_mapping.keys())}"
                )
        
        if time_filter_hours:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=time_filter_hours)
            query = query.filter(Hotspot.detected_at >= cutoff_time)

    query = _apply_officer_hotspot_scope(query, db, current_user)
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
    if time_window_hours is not None:
        # Inclusive period semantics: selecting a larger window should include
        # hotspots created in smaller DBSCAN windows as long as they were
        # detected within the selected period.
        period_cutoff = datetime.now(timezone.utc) - timedelta(hours=int(time_window_hours))
        query = query.filter(Hotspot.detected_at >= period_cutoff)
    hotspots = query.limit(limit).all()
    deployment_units = load_hotspot_deployment_units(db)

    responses = []

    for h in hotspots:
        # Include all clustered reports; some legacy rows may miss village linkage
        # but still have valid coordinates required for map/hotspot analytics.
        reports_in_cluster = list(getattr(h, "reports", None) or [])
        if not reports_in_cluster:
            continue

        # Load is_core flag per report from the junction table
        core_report_ids: set = set()
        try:
            rows = db.execute(
                text("SELECT report_id FROM hotspot_reports WHERE hotspot_id = :hid AND is_core = true"),
                {"hid": h.hotspot_id},
            ).fetchall()
            core_report_ids = {str(row[0]) for row in rows}
        except Exception:
            pass

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
                    "is_core": str(r.report_id) in core_report_ids,
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
        # Prefer stored polygon (pre-computed, avoids per-request hull computation)
        stored_poly = getattr(h, "polygon_points", None)
        if stored_poly:
            try:
                boundary_points = json.loads(stored_poly)
            except Exception:
                boundary_points = _expand_hull(_convex_hull(cluster_points)) if cluster_points else []
        else:
            boundary_points = _expand_hull(_convex_hull(cluster_points)) if cluster_points else []

        dominant_crime = h.incident_type.type_name if h.incident_type else None
        area_label = None
        if area_counts:
            area_label = sorted(area_counts.items(), key=lambda x: x[1], reverse=True)[0][0]

        cluster_kind = "trend_cluster" if len(incident_mix) <= 1 else "mixed_hotspot"

        report_times = [
            r.reported_at for r in reports_in_cluster if r.reported_at is not None
        ]
        peak_time = _compute_peak_window(report_times)
        verified_count = sum(
            1
            for r in reports_in_cluster
            if (getattr(r, "verification_status", None) or "").strip().lower() == "verified"
        )

        unit_hint_counts: Dict[str, int] = {}
        for r in reports_in_cluster:
            it = getattr(r, "incident_type", None)
            default_u = getattr(it, "default_special_assignment_unit", None) if it else None
            if default_u:
                key_u = str(default_u).strip()
                unit_hint_counts[key_u] = unit_hint_counts.get(key_u, 0) + 1
        incident_unit_hint = (
            max(unit_hint_counts, key=unit_hint_counts.get)
            if unit_hint_counts
            else None
        )
        if not incident_unit_hint and h.incident_type:
            incident_unit_hint = getattr(
                h.incident_type, "default_special_assignment_unit", None
            )

        report_ids = [r.report_id for r in reports_in_cluster]
        cluster_case_context = gather_cluster_case_context(db, report_ids)

        # Build cluster evolution context for cluster-aware recommendations
        cluster_evolution = {
            "lifecycle_state": getattr(h, "lifecycle_state", None),
            "trend_direction": getattr(h, "trend_direction", None),
            "crime_group": getattr(h, "crime_group", None),
            "cluster_confidence": float(h.cluster_confidence) if getattr(h, "cluster_confidence", None) else None,
            "severity_score": float(h.severity_score) if getattr(h, "severity_score", None) else None,
            "temporal_intensity": float(h.temporal_intensity) if getattr(h, "temporal_intensity", None) else None,
            "composition": json.loads(h.composition) if getattr(h, "composition", None) else None,
        }
        # Count nearby clusters (within ~2km) to gauge area-wide security pressure
        try:
            nearby_clusters = db.query(Hotspot).filter(
                Hotspot.hotspot_id != h.hotspot_id,
                Hotspot.center_lat.between(
                    float(h.center_lat) - 0.018, float(h.center_lat) + 0.018
                ),
                Hotspot.center_long.between(
                    float(h.center_long) - 0.018, float(h.center_long) + 0.018
                ),
                Hotspot.incident_count >= 2,
            ).count()
        except Exception:
            nearby_clusters = 0
        cluster_evolution["nearby_clusters"] = nearby_clusters

        llm = generate_recommendation(
            classification=classification,
            incident_count=incident_count,
            dominant_crime=dominant_crime,
            cluster_kind=cluster_kind,
            area_label=area_label,
            incident_mix=incident_mix,
            peak_time=peak_time,
            verified_report_count=verified_count,
            recommended_unit=incident_unit_hint,
            deployment_units=deployment_units,
            cluster_case_context=cluster_case_context,
            cluster_evolution=cluster_evolution,
        )

        prediction = _prediction_for_hotspot(
            classification,
            incident_count,
            cluster_kind,
            report_times=report_times,
        )
        # All text/operation fields come from the LLM (Groq → Gemini → template fallback)
        prediction["recommendation"]    = llm["recommendation"]
        prediction["narrative"]          = llm["narrative"]
        prediction["status"]             = llm["status"]
        prediction["recommended_unit"]       = llm.get("recommended_unit")
        prediction["recommended_unit_name"]  = llm.get("recommended_unit_name")
        prediction["recommended_units"]      = llm.get("recommended_units")
        prediction["citizen_advisory"]       = llm.get("citizen_advisory")
        prediction["operation_hours"]          = llm.get("operation_hours")
        prediction["concentrate_window"]       = llm.get("concentrate_window")
            
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
            **_deployment_fields_for_hotspot(db, h),
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
            composition=json.loads(h.composition) if getattr(h, "composition", None) else None,
            temporal_intensity=float(h.temporal_intensity) if getattr(h, "temporal_intensity", None) else None,
            severity_score=float(h.severity_score) if getattr(h, "severity_score", None) else None,
            trend_direction=getattr(h, "trend_direction", None),
            cluster_confidence=float(h.cluster_confidence) if getattr(h, "cluster_confidence", None) else None,
            crime_group=getattr(h, "crime_group", None),
        ))
        
    return responses


@router.get("/emergencies", response_model=List[HotspotResponse])
def get_daily_emergencies(
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    days_back: int = Query(1, ge=1, le=30, description="Number of days to look back for emergencies"),
    min_incidents: int = Query(3, ge=1, description="Minimum incidents to qualify as emergency"),
):
    """Get emergency hotspots detected within the specified time period.
    
    This endpoint focuses on detecting critical incidents that may require immediate attention.
    Defaults to showing emergencies from the last 24 hours.
    """
    from datetime import timedelta
    
    # Calculate time cutoff
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=days_back)
    
    # Query for critical hotspots within the time period
    query = db.query(Hotspot).options(
        joinedload(Hotspot.incident_type),
        joinedload(Hotspot.controlled_by),
        selectinload(Hotspot.reports).selectinload(Report.ml_predictions),
        selectinload(Hotspot.reports).joinedload(Report.village_location),
        selectinload(Hotspot.reports).joinedload(Report.incident_type),
        selectinload(Hotspot.reports).selectinload(Report.evidence_files),
    ).filter(
        Hotspot.detected_at >= cutoff_time,
        Hotspot.risk_level.in_(["critical", "active"])
    )
    
    query = _apply_officer_hotspot_scope(query, db, current_user)

    # Filter by minimum incident count for emergencies
    emergency_hotspots = []
    for h in query.all():
        reports_in_cluster = [r for r in h.reports if r.reported_at >= cutoff_time]
        if len(reports_in_cluster) >= min_incidents:
            emergency_hotspots.append(h)
    
    # Build response (reuse existing logic from main endpoint)
    responses = []
    for h in emergency_hotspots:
        reports_in_cluster = [r for r in h.reports if r.reported_at >= cutoff_time]
        if not reports_in_cluster:
            continue

        # Calculate hotspot metrics (simplified for emergencies)
        incident_count = len(reports_in_cluster)
        radius_m = float(getattr(h, "radius_meters", 500) or 500)
        
        # Use existing classification logic
        hotspot_score = min(95, 60 + (incident_count * 5))  # Emergency scoring
        classification = "critical" if hotspot_score >= 80 else "active"
        
        responses.append(HotspotResponse(
            hotspot_id=h.hotspot_id,
            latitude=float(h.latitude) if h.latitude else None,
            longitude=float(h.longitude) if h.longitude else None,
            radius_meters=radius_m,
            incident_count=incident_count,
            time_window_hours=24,  # Emergency detection uses 24-hour window
            risk_level=h.risk_level,
            incident_type_id=h.incident_type_id,
            incident_type=h.incident_type,
            detected_at=h.detected_at,
            updated_at=h.updated_at,
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
            lifecycle_state=classification,
            hotspot_score=hotspot_score,
            classification=classification,
            classification_confidence=0.9,
            classification_source="emergency_detection",
            avg_trust_score=75.0,  # Default for emergencies
            dominant_crime_type=h.incident_type.type_name if h.incident_type else "Emergency",
            cluster_kind="emergency",
            area_label="Emergency Zone",
            incident_mix={r.incident_type.type_name if r.incident_type else "Unknown": 1 for r in reports_in_cluster},
            prediction={"emergency": True, "severity": "high"},
            boundary_points=[(float(r.latitude), float(r.longitude)) for r in reports_in_cluster],
            incident_points=[
                {
                    "report_id": str(r.report_id),
                    "incident_type_name": r.incident_type.type_name if r.incident_type else "Unknown",
                    "description": r.description,
                    "latitude": float(r.latitude),
                    "longitude": float(r.longitude),
                    "reported_at": r.reported_at.isoformat() if r.reported_at else None,
                    "trust_score": 75.0,
                    "village_name": r.village_location.location_name if r.village_location else None,
                    "cell_name": None,
                    "sector_name": None,
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
                for r in reports_in_cluster
            ],
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
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
):
    """
    Recompute hotspots from recent reports using supplied parameters.

    Admin/supervisor only. This clears existing hotspots and hotspot_reports
    before running the auto-creation job, so the map reflects the new
    clustering configuration.
    """
    cfg_tw, cfg_min, cfg_rad = get_hotspot_params_from_db(
        db,
        time_window_hours=DEFAULT_TIME_WINDOW_HOURS,
        min_incidents=DEFAULT_MIN_INCIDENTS,
        radius_meters=DEFAULT_RADIUS_METERS,
    )
    cfg_trust = get_hotspot_trust_min_from_db(db, DEFAULT_TRUST_MIN)

    payload_tw = payload.time_window_hours if payload else None
    payload_min = payload.min_incidents if payload else None
    payload_rad = payload.radius_meters if payload else None
    payload_trust = payload.trust_min if payload else None
    payload_incident_type_id = payload.incident_type_id if payload else None
    payload_from = payload.from_date if payload else None
    payload_to = payload.to_date if payload else None

    eff_tw = int(_coalesce_param(payload_tw, time_window_hours, cfg_tw))
    eff_min = int(_coalesce_param(payload_min, min_incidents, cfg_min))
    eff_rad = float(_coalesce_param(payload_rad, radius_meters, cfg_rad))
    eff_trust = float(_coalesce_param(payload_trust, trust_min, cfg_trust))
    eff_incident_type_id = _coalesce_param(
        payload_incident_type_id,
        incident_type_id,
        None,
    )

    window_end = _as_utc(_coalesce_param(payload_to, to_date, None)) or datetime.now(timezone.utc)
    window_start = _as_utc(_coalesce_param(payload_from, from_date, None))
    if window_start is not None:
        if window_start >= window_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="from_date must be before to_date",
            )
        eff_tw = _hours_between(window_start, window_end)

    eff_tw = max(1, min(8760, eff_tw))
    eff_min = max(1, min(100, eff_min))
    eff_rad = max(50.0, min(10000.0, eff_rad))
    eff_trust = max(0.0, min(100.0, eff_trust))

    if window_start is None:
        window_start = window_end - timedelta(hours=eff_tw)

    # Clear existing hotspots + link table after parameters have been validated.
    db.execute(hotspot_reports_table.delete())
    db.query(Hotspot).delete()
    db.commit()

    created = create_hotspots_from_reports(
        db,
        time_window_hours=eff_tw,
        min_incidents=eff_min,
        radius_meters=eff_rad,
        trust_min=eff_trust,
        incident_type_id=eff_incident_type_id,
        analyze_all_reports=False,
        start_time=window_start,
        end_time=window_end,
    )
    db.commit()

    # New clusters → stale recommendations no longer apply; clear cache so the
    # next Safety Map load generates fresh LLM analysis for each new cluster.
    cleared = clear_recommendation_cache()
    logger.info("Recompute: cleared %d cached recommendations.", cleared)

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
            "from_date": window_start.isoformat(),
            "to_date": window_end.isoformat(),
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

@router.get("/stats")
async def get_hotspot_stats(
    time_period: Optional[str] = None,
    hours_back: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Get hotspot statistics for the sidebar cards
    """
    try:
        ensure_hotspots_materialized(db)

        # Calculate time cutoff based on parameters
        cutoff_time = datetime.utcnow()
        
        if time_period:
            if time_period == "day":
                cutoff_time -= timedelta(days=1)
            elif time_period == "week":
                cutoff_time -= timedelta(weeks=1)
            elif time_period == "month":
                cutoff_time -= timedelta(days=30)
            elif time_period == "quarter":
                cutoff_time -= timedelta(days=90)
            elif time_period == "year":
                cutoff_time -= timedelta(days=365)
        elif hours_back:
            cutoff_time -= timedelta(hours=hours_back)
        else:
            # Default to last 30 days if no time period specified
            cutoff_time -= timedelta(days=30)
        
        # Query hotspots within the time period
        query = db.query(Hotspot).filter(Hotspot.detected_at >= cutoff_time)
        
        # Note: Hotspots don't have station_id, so no role-based filtering needed
        # All users can see all hotspots
        hotspots = query.all()
        
        # Calculate statistics
        total_clusters = len(hotspots)
        reports_in_clusters = sum(h.incident_count or 0 for h in hotspots)
        
        # Calculate risk level counts
        crit_count = sum(1 for h in hotspots if h.risk_level in ["high", "critical"])
        warn_count = sum(1 for h in hotspots if h.risk_level == "medium")
        normal_count = sum(1 for h in hotspots if h.risk_level == "low")
        
        # Calculate formation stage counts
        stage_counts = {"emerging": 0, "active": 0, "intense": 0}
        for h in hotspots:
            # Determine formation stage based on risk level and incident count
            risk = h.risk_level or ""
            count = h.incident_count or 0
            
            if risk == "critical" or count >= 8:
                stage_counts["intense"] += 1
            elif risk == "high" or count >= 4:
                stage_counts["active"] += 1
            elif risk == "medium" or count >= 2:
                stage_counts["emerging"] += 1
            else:
                stage_counts["emerging"] += 1
        
        # Calculate average cluster trust (simplified calculation)
        avg_trust = 75  # Default trust score
        if hotspots:
            trust_scores = []
            for h in hotspots:
                # Base trust depends on incident count and risk level
                base_trust = 70
                if h.incident_count and h.incident_count > 10:
                    base_trust += 10
                elif h.incident_count and h.incident_count > 5:
                    base_trust += 5
                
                # Risk level adjustment
                if h.risk_level == "critical":
                    base_trust += 10
                elif h.risk_level == "high":
                    base_trust += 5
                elif h.risk_level == "medium":
                    base_trust += 2
                
                trust_scores.append(min(100, base_trust))  # Cap at 100
            
            if trust_scores:
                avg_trust = round(sum(trust_scores) / len(trust_scores))
        
        # Get latest cluster run time
        latest_run = "Never"
        if hotspots:
            latest_detection = max(h.detected_at for h in hotspots if h.detected_at)
            if latest_detection:
                latest_run = latest_detection.strftime("%Y-%m-%d %H:%M:%S")
        
        return {
            "total_clusters": total_clusters,
            "reports_in_clusters": reports_in_clusters,
            "risk_counts": {
                "critical": crit_count,
                "warning": warn_count,
                "normal": normal_count
            },
            "stage_counts": stage_counts,
            "avg_cluster_trust": avg_trust,
            "latest_cluster_run": latest_run,
            "time_period": time_period or "month",
            "cutoff_time": cutoff_time.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting hotspot stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get hotspot statistics")


def _load_hotspot_for_ops(db: Session, hotspot_id: int) -> Hotspot:
    h = (
        db.query(Hotspot)
        .options(
            selectinload(Hotspot.reports).joinedload(Report.village_location),
            joinedload(Hotspot.controlled_by),
        )
        .filter(Hotspot.hotspot_id == hotspot_id)
        .first()
    )
    if not h:
        raise HTTPException(status_code=404, detail="Hotspot not found")
    return h


@router.post("/{hotspot_id}/take-control")
def take_control_hotspot(
    hotspot_id: int,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    """IO/DPC takes operational control of a hotspot cluster."""
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Only IO or DPC can take hotspot control")
    from app.core.hotspot_deployment import take_hotspot_control

    h = _load_hotspot_for_ops(db, hotspot_id)
    take_hotspot_control(db, h, current_user)
    parts = [current_user.first_name or "", current_user.last_name or ""]
    name = " ".join(p for p in parts if p).strip() or current_user.email
    return {
        "message": f"Hotspot #{hotspot_id} is now under your control.",
        "controlled_by_user_id": current_user.police_user_id,
        "controlled_by_name": name,
    }


@router.post("/{hotspot_id}/deploy")
def deploy_unit_to_hotspot(
    hotspot_id: int,
    payload: HotspotDeployRequest,
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
):
    """Deploy a special assignment unit to a hotspot; emails the unit commander."""
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Only IO or DPC can authorize deployment")
    from app.core.hotspot_deployment import deploy_hotspot_unit

    h = _load_hotspot_for_ops(db, hotspot_id)
    try:
        _, unit, meta = deploy_hotspot_unit(
            db,
            h,
            unit_code=payload.unit_code,
            decided_by=current_user,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    msg = f"Unit {unit.unit_name} ({unit.unit_code}) deployed to hotspot #{hotspot_id}."
    if meta.get("email_sent"):
        msg += f" Commander notified at {meta.get('commander_email')}."
    elif meta.get("email_error"):
        msg += f" Warning: commander email failed — {meta['email_error']}."
    return {
        "message": msg,
        "hotspot_id": hotspot_id,
        "assigned_unit_code": unit.unit_code,
        "assigned_unit_name": unit.unit_name,
        "email_sent": meta.get("email_sent", False),
        "email_error": meta.get("email_error"),
    }
