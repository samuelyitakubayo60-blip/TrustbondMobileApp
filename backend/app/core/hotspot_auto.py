"""Hotspot auto-creation using DBSCAN over trusted incident reports."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload

from app.core.cluster_classifier import (
    classification_to_risk_level,
    predict_cluster_classification,
)
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.location import Location
from app.models.report import Report
from app.models.system_config import SystemConfig


DEFAULT_TIME_WINDOW_HOURS = 24
DEFAULT_MIN_INCIDENTS = 2
DEFAULT_RADIUS_METERS = 500
DEFAULT_TRUST_MIN = 50.0


def get_hotspot_params_from_db(
    db: Session,
    *,
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    min_incidents: int = DEFAULT_MIN_INCIDENTS,
    radius_meters: float = DEFAULT_RADIUS_METERS,
) -> tuple[int, int, float]:
    """Read DBSCAN params from system config when present."""
    tw = time_window_hours
    mi = min_incidents
    rm = radius_meters
    try:
        eps = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == "dbscan.epsilon")
            .first()
        )
        if eps and isinstance(eps.config_value, dict):
            value = eps.config_value.get("value")
            if value is not None:
                rm = float(value)
    except Exception:
        pass
    try:
        ms = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == "dbscan.min_samples")
            .first()
        )
        if ms and isinstance(ms.config_value, dict):
            value = ms.config_value.get("value")
            if value is not None:
                mi = int(value)
    except Exception:
        pass
    return tw, max(1, mi), max(50.0, rm)


def get_hotspot_trust_min_from_db(db: Session, default: float = DEFAULT_TRUST_MIN) -> float:
    """Read trust threshold used before clustering."""
    try:
        row = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == "dbscan.trust_min")
            .first()
        )
        if row and isinstance(row.config_value, dict):
            value = row.config_value.get("value")
            if value is not None:
                return max(0.0, min(100.0, float(value)))
    except Exception:
        pass
    return max(0.0, min(100.0, float(default)))


def _latest_ml_trust(report: Report) -> Optional[float]:
    preds = list(getattr(report, "ml_predictions", None) or [])
    if not preds:
        return None
    final = [p for p in preds if getattr(p, "is_final", False)]
    source = final if final else preds
    source.sort(
        key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    latest = source[0]
    try:
        if latest.trust_score is None:
            return None
        return float(latest.trust_score)
    except Exception:
        return None


def _report_trust_score(report: Report) -> float:
    """Best-effort trust score in range 0..100 for hotspot filtering."""
    ml_score = _latest_ml_trust(report)
    if ml_score is not None:
        return max(0.0, min(100.0, ml_score))

    officer_confirmed = any(
        (rv.decision or "").lower() == "confirmed"
        for rv in (getattr(report, "police_reviews", None) or [])
    )
    if officer_confirmed or (report.verification_status or "").lower() == "verified":
        return 90.0
    if (report.rule_status or "").lower() == "passed":
        return 65.0
    return 35.0


def _is_report_eligible(report: Report) -> bool:
    """Exclude reports that are already rejected by rules/police workflow."""
    status = (report.status or "").lower()
    verification = (report.verification_status or "").lower()
    rule_status = (report.rule_status or "").lower()
    if status == "rejected" or verification == "rejected" or rule_status == "rejected":
        return False
    return True


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _trust_weight(point: Dict[str, Any]) -> float:
    """Return a normalized DBSCAN density weight from a report trust score."""
    try:
        trust = float(point.get("trust", 100.0))
    except (TypeError, ValueError):
        trust = 50.0
    return max(0.05, min(1.0, trust / 100.0))


def _dbscan(points: List[Dict[str, Any]], eps_meters: float, min_pts: int) -> List[int]:
    n = len(points)
    labels = [-2] * n  # -2 unvisited, -1 noise, >=0 cluster id
    cluster_id = 0
    min_density_weight = max(1.0, float(min_pts) * 0.5)

    def neighbors(i: int) -> Tuple[List[int], float]:
        p = points[i]
        out: List[int] = []
        for j, q in enumerate(points):
            if _haversine_meters(p["lat"], p["lon"], q["lat"], q["lon"]) <= eps_meters:
                out.append(j)
        density_weight = sum(_trust_weight(points[j]) for j in out)
        return out, density_weight

    for i in range(n):
        if labels[i] != -2:
            continue
        nbs, density_weight = neighbors(i)
        if len(nbs) < min_pts or density_weight < min_density_weight:
            labels[i] = -1
            continue

        labels[i] = cluster_id
        queue = list(nbs)
        qi = 0
        while qi < len(queue):
            j = queue[qi]
            if labels[j] == -1:
                labels[j] = cluster_id
            if labels[j] != -2:
                qi += 1
                continue
            labels[j] = cluster_id
            jn, j_density_weight = neighbors(j)
            if len(jn) >= min_pts and j_density_weight >= min_density_weight:
                for cand in jn:
                    if cand not in queue:
                        queue.append(cand)
            qi += 1

        cluster_id += 1

    return labels


def cleanup_expired_hotspots(db: Session):
    """Deprecated: Hotspots should persist for historical analysis.
    
    This function is disabled to allow clusters to remain for long-term
    pattern analysis over weeks, months, and years.
    """
    # Hotspots now persist indefinitely for historical analysis
    # Time-based filtering will be handled at the API level
    return 0


def create_hotspots_from_reports(
    db: Session,
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    min_incidents: int = DEFAULT_MIN_INCIDENTS,
    radius_meters: float = DEFAULT_RADIUS_METERS,
    trust_min: float = DEFAULT_TRUST_MIN,
    incident_type_id: Optional[int] = None,
    analyze_all_reports: bool = False,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> int:
    """
    Enhanced Pipeline:
    Reports in the chosen time period -> trust-weighted geographic DBSCAN -> hotspots with risk levels.
    """
    effective_time_window_hours = max(1, int(time_window_hours or DEFAULT_TIME_WINDOW_HOURS))
    now = datetime.now(timezone.utc)
    window_end = end_time or now
    window_start = start_time or (window_end - timedelta(hours=effective_time_window_hours))

    reports_query = (
        db.query(Report)
        .join(Location, Report.village_location_id == Location.location_id)
        .filter(
            Report.village_location_id.isnot(None),
            Location.location_type == "village",
            Location.is_active == True,
        )
        .options(
            selectinload(Report.police_reviews),
            selectinload(Report.ml_predictions),
        )
    )
    if not analyze_all_reports:
        reports_query = reports_query.filter(
            Report.reported_at >= window_start,
            Report.reported_at <= window_end,
        )
    reports = reports_query.all()

    # Filter eligible reports
    eligible_reports = []
    for r in reports:
        if not _is_report_eligible(r):
            continue
        if incident_type_id is not None and int(r.incident_type_id) != int(incident_type_id):
            continue

        try:
            lat = float(r.latitude)
            lon = float(r.longitude)
        except (TypeError, ValueError):
            continue

        trust = _report_trust_score(r)
        if trust < float(trust_min):
            continue

        eligible_reports.append({
            "report": r,
            "lat": lat,
            "lon": lon,
            "trust": trust,
            "incident_type_id": int(r.incident_type_id),
            "reported_at": r.reported_at,
            "village_location_id": r.village_location_id,
        })

    if len(eligible_reports) < max(1, int(min_incidents)):
        return 0

    created = _create_geographic_hotspots(
        db, eligible_reports, radius_meters, min_incidents, effective_time_window_hours
    )
    print(
        f"Created {created} DBSCAN hotspots "
        f"from {len(eligible_reports)} eligible reports in {effective_time_window_hours}h"
    )
    
    return created


def _create_village_based_hotspots(
    db: Session, 
    reports: List[Dict[str, Any]], 
    min_incidents: int, 
    time_window_hours: int
) -> int:
    """Create hotspots based on village clustering with strict 24-hour time constraint"""
    created = 0
    
    # Group reports by village and incident type (ensuring same place and type)
    village_groups = {}
    for report in reports:
        village_key = f"{report['village_location_id']}_{report['incident_type_id']}"
        if village_key not in village_groups:
            village_groups[village_key] = []
        village_groups[village_key].append(report)
    
    # Create hotspots for village groups with enough incidents and within time window
    for village_key, village_reports in village_groups.items():
        if len(village_reports) < min_incidents:
            continue
        
        village_id, incident_type_id = village_key.split('_')
        
        # Strict time filtering: ensure all reports are within 24 hours
        village_reports.sort(key=lambda r: r["reported_at"])
        time_span = (village_reports[-1]["reported_at"] - village_reports[0]["reported_at"]).total_seconds() / 3600
        
        if time_span > time_window_hours:
            print(f"Skipped village hotspot for village {village_id}, type {incident_type_id} - time span {time_span:.1f}h exceeds {time_window_hours}h limit")
            continue
        
        # Calculate center and statistics
        incident_count = len(village_reports)
        center_lat = sum(r["lat"] for r in village_reports) / incident_count
        center_long = sum(r["lon"] for r in village_reports) / incident_count
        avg_trust = sum(r["trust"] for r in village_reports) / incident_count
        
        # Risk classification
        area_sqkm = 0.01  # Village area approximation
        cluster_density = incident_count / area_sqkm
        classification_result = predict_cluster_classification(
            incident_count=incident_count,
            avg_trust=avg_trust,
            cluster_density=cluster_density,
            time_window_hours=time_window_hours,
        )
        risk_level = classification_to_risk_level(classification_result["classification"])
        
        # Create or update hotspot
        existing_hotspot = db.query(Hotspot).filter(
            Hotspot.incident_type_id == int(incident_type_id),
            Hotspot.center_lat.between(center_lat - 0.001, center_lat + 0.001),
            Hotspot.center_long.between(center_long - 0.001, center_long + 0.001),
            Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24)
        ).first()
        
        if existing_hotspot:
            # Update existing hotspot
            existing_hotspot.center_lat = Decimal(str(center_lat))
            existing_hotspot.center_long = Decimal(str(center_long))
            existing_hotspot.radius_meters = Decimal("300")  # Village radius
            existing_hotspot.incident_count = incident_count
            existing_hotspot.risk_level = risk_level
            existing_hotspot.time_window_hours = time_window_hours
            existing_hotspot.detected_at = datetime.now(timezone.utc)
            
            # Refresh report associations
            db.execute(
                text("DELETE FROM hotspot_reports WHERE hotspot_id = :hotspot_id"),
                {"hotspot_id": existing_hotspot.hotspot_id},
            )
            
            for report in village_reports:
                db.execute(
                    text("INSERT INTO hotspot_reports (hotspot_id, report_id) VALUES (:hotspot_id, :report_id)"),
                    {"hotspot_id": existing_hotspot.hotspot_id, "report_id": report["report"].report_id},
                )
            
            print(f"Updated village-based hotspot for village {village_id}, incident type {incident_type_id}")
        else:
            # Create new hotspot
            hotspot = Hotspot(
                center_lat=Decimal(str(center_lat)),
                center_long=Decimal(str(center_long)),
                radius_meters=Decimal("300"),  # Village radius
                incident_count=incident_count,
                risk_level=risk_level,
                time_window_hours=time_window_hours,
                incident_type_id=int(incident_type_id),
                detected_at=datetime.now(timezone.utc),
            )
            
            db.add(hotspot)
            db.flush()
            
            # Link reports to hotspot
            for report in village_reports:
                db.execute(
                    text("INSERT INTO hotspot_reports (hotspot_id, report_id) VALUES (:hotspot_id, :report_id)"),
                    {"hotspot_id": hotspot.hotspot_id, "report_id": report["report"].report_id},
                )
            
            created += 1
            print(f"Created village-based hotspot {hotspot.hotspot_id} for village {village_id}, incident type {incident_type_id}")
    
    return created


def _create_geographic_hotspots(
    db: Session,
    reports: List[Dict[str, Any]], 
    radius_meters: float, 
    min_incidents: int, 
    time_window_hours: int
) -> int:
    """Create hotspots using geographic DBSCAN clustering with strict time constraint"""
    # Convert reports to points format for DBSCAN
    points = reports  # Already in correct format
    
    # Apply DBSCAN clustering
    labels = _dbscan(points, max(50.0, float(radius_meters)), max(1, int(min_incidents)))
    clusters: Dict[int, List[Dict[str, Any]]] = {}
    for idx, label in enumerate(labels):
        if label < 0:
            continue
        clusters.setdefault(label, []).append(points[idx])

    created = 0
    for _, cluster_points in clusters.items():
        incident_count = len(cluster_points)
        if incident_count < int(min_incidents):
            continue

        # Strict time filtering: ensure all reports in cluster are within 24 hours
        cluster_points.sort(key=lambda p: p["reported_at"])
        time_span = (cluster_points[-1]["reported_at"] - cluster_points[0]["reported_at"]).total_seconds() / 3600
        
        if time_span > time_window_hours:
            print(f"Skipped geographic cluster - time span {time_span:.1f}h exceeds {time_window_hours}h limit")
            continue

        center_lat = sum(p["lat"] for p in cluster_points) / incident_count
        center_long = sum(p["lon"] for p in cluster_points) / incident_count
        avg_trust = sum(p["trust"] for p in cluster_points) / incident_count

        # Ensure all reports in cluster are of the same incident type
        type_counts: Dict[int, int] = {}
        for p in cluster_points:
            tid = int(p["incident_type_id"])
            type_counts[tid] = type_counts.get(tid, 0) + 1
        
        # Only create hotspot if all reports are of the same type
        if len(type_counts) != 1:
            print(f"Skipped geographic cluster - contains multiple incident types: {list(type_counts.keys())}")
            continue
            
        dominant_incident_type_id = list(type_counts.keys())[0]

        area_sqkm = max(0.001, 3.14159 * (float(radius_meters) / 1000.0) ** 2)
        cluster_density = incident_count / area_sqkm
        classification_result = predict_cluster_classification(
            incident_count=incident_count,
            avg_trust=avg_trust,
            cluster_density=cluster_density,
            time_window_hours=time_window_hours,
        )
        risk_level = classification_to_risk_level(classification_result["classification"])

        existing_query = db.query(Hotspot).filter(
            Hotspot.incident_type_id == dominant_incident_type_id,
            Hotspot.center_lat.between(center_lat - 0.01, center_lat + 0.01),
            Hotspot.center_long.between(center_long - 0.01, center_long + 0.01),
        )
        existing_query = existing_query.filter(Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24))
        existing = existing_query.order_by(Hotspot.detected_at.desc()).first()

        hotspot = existing
        if hotspot is None:
            hotspot = Hotspot(
                center_lat=Decimal(str(center_lat)),
                center_long=Decimal(str(center_long)),
                radius_meters=Decimal(str(radius_meters)),
                incident_count=incident_count,
                risk_level=risk_level,
                time_window_hours=time_window_hours,
                incident_type_id=dominant_incident_type_id,
                detected_at=datetime.now(timezone.utc),
            )
            db.add(hotspot)
            db.flush()
            created += 1
        else:
            hotspot.center_lat = Decimal(str(center_lat))
            hotspot.center_long = Decimal(str(center_long))
            hotspot.radius_meters = Decimal(str(radius_meters))
            hotspot.incident_count = incident_count
            hotspot.risk_level = risk_level
            hotspot.time_window_hours = time_window_hours
            hotspot.incident_type_id = dominant_incident_type_id
            hotspot.detected_at = datetime.now(timezone.utc)
            db.execute(
                text("DELETE FROM hotspot_reports WHERE hotspot_id = :hotspot_id"),
                {"hotspot_id": hotspot.hotspot_id},
            )

        for p in cluster_points:
            db.execute(
                text(
                    "INSERT INTO hotspot_reports (hotspot_id, report_id) "
                    "VALUES (:hotspot_id, :report_id) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "hotspot_id": hotspot.hotspot_id,
                    "report_id": str(p["report"].report_id),
                },
            )
    
    return created
