"""Hotspot auto-creation using ST-DBSCAN over trusted incident reports."""

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.cluster_classifier import (
    classification_to_risk_level,
    predict_cluster_classification,
)
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.location import Location
from app.models.report import Report
from app.models.system_config import SystemConfig
from app.config import settings
from app.core.leader_workflow import report_ready_for_cases_and_hotspots


DEFAULT_TIME_WINDOW_HOURS = 720   # 30 days — wide enough to include sparse report data
DEFAULT_MIN_INCIDENTS = 2         # 2 nearby incidents form a cluster
DEFAULT_RADIUS_METERS = 300       # 300 m keeps clusters tight, prevents city-wide chaining
DEFAULT_TRUST_MIN = 30            # include all verified incidents (verified → trust=90)

# ─── Crime taxonomy ──────────────────────────────────────────────────────────

#: Groups of related crime types that may co-cluster.
#: Keys are group names; values are lowercase substrings to match against.
CRIME_GROUPS: Dict[str, List[str]] = {
    "violent":      ["assault", "domestic violence", "threat", "murder",
                     "robbery with violence", "gbv", "gender-based violence",
                     "bodily harm", "manslaughter"],
    "property":     ["theft", "robbery", "burglary", "vandalism",
                     "property damage", "breaking and entering",
                     "shoplifting", "motor vehicle theft", "pickpocketing"],
    "drug":         ["drug activity", "drug trafficking", "substance abuse",
                     "narcotics", "drug possession"],
    "fraud":        ["fraud", "scam", "cybercrime", "identity theft",
                     "forgery", "corruption", "bribery", "financial crime"],
    "sexual":       ["sexual assault", "harassment", "rape", "indecent",
                     "sexual harassment", "defilement"],
    "traffic":      ["traffic", "accident", "hit and run", "dui", "road accident"],
    "public_order": ["suspicious", "public disturbance", "trespass",
                     "loitering", "illegal gathering", "riot"],
}

#: Severity 1.0–10.0 per crime type (lower-case lookup).
CRIME_SEVERITY: Dict[str, float] = {
    "murder": 10.0, "manslaughter": 9.8,
    "sexual assault": 9.5, "rape": 9.5, "defilement": 9.5,
    "robbery with violence": 9.0,
    "gbv": 8.8, "gender-based violence": 8.8, "sexual violence": 8.5,
    "assault": 8.0, "domestic violence": 8.0, "bodily harm": 7.8,
    "drug trafficking": 7.5, "robbery": 7.5,
    "burglary": 7.0, "breaking and entering": 7.0,
    "threats": 6.5, "threat": 6.5, "motor vehicle theft": 6.5,
    "fraud/scam": 5.5, "fraud": 5.5, "cybercrime": 5.5,
    "theft": 5.0, "harassment": 5.0, "sexual harassment": 5.0,
    "vandalism": 4.5, "drug activity": 4.0, "drug possession": 4.0,
    "substance abuse": 4.0, "identity theft": 4.0,
    "corruption": 4.5, "forgery": 3.5,
    "public disturbance": 3.5, "traffic incident": 3.0, "road accident": 3.0,
    "suspicious activity": 2.5, "trespass": 2.0, "loitering": 1.5,
}
_DEFAULT_SEVERITY = 4.0


def _get_severity(type_name: str) -> float:
    if not type_name:
        return _DEFAULT_SEVERITY
    return CRIME_SEVERITY.get(type_name.strip().lower(), _DEFAULT_SEVERITY)


def _get_crime_group(type_name: str) -> str:
    if not type_name:
        return "other"
    name = type_name.strip().lower()
    for group, members in CRIME_GROUPS.items():
        if any(m in name or name in m for m in members):
            return group
    return "other"


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

    if (report.verification_status or "").lower() == "verified":
        return 90.0
    if (report.rule_status or "").lower() == "passed":
        return 65.0
    return 35.0


def _is_report_eligible(
    report: Report,
    *,
    require_leader_confirmation: Optional[bool] = None,
) -> bool:
    """Eligible for safety-map clustering.

    Includes all non-rejected reports (verified, pending, under_review) so
    every incident in the system is represented on the map.  Only hard-rejected
    reports (by status, verification, or rule engine) are excluded.
    """
    status = (report.status or "").lower()
    verification = (report.verification_status or "").lower()
    rule_status = (report.rule_status or "").lower()
    if status == "rejected" or verification == "rejected" or rule_status == "rejected":
        return False

    from app.core.leader_workflow import leader_gate_enabled, report_ready_for_cases_and_hotspots

    if require_leader_confirmation is None:
        require_leader_confirmation = leader_gate_enabled()

    if require_leader_confirmation:
        return report_ready_for_cases_and_hotspots(report)

    # Accept verified, pending, or under_review — anything not rejected
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


def _st_dbscan(
    points: List[Dict[str, Any]],
    eps_meters: float,
    eps_seconds: float,
    min_pts: int,
) -> Tuple[List[int], List[bool]]:
    """
    Spatio-Temporal DBSCAN (ST-DBSCAN).

    Point j is a neighbor of i iff:
      haversine(i,j) <= eps_meters  AND  |t_i – t_j| <= eps_seconds

    Core condition: |neighborhood(i)| >= min_pts
                    OR  sum of severity-trust weights in neighborhood >= min_pts * 2
                    (allows a single high-severity report to anchor a cluster)

    Returns (labels, is_core).
    """
    n = len(points)

    # Pre-compute timestamps (seconds since epoch)
    ts: List[float] = []
    for p in points:
        rt = p.get("reported_at")
        try:
            ts.append(rt.timestamp() if rt else 0.0)
        except Exception:
            ts.append(0.0)

    # Per-point weight = (trust / 100) * severity
    weights: List[float] = [
        (float(p.get("trust", 100.0)) / 100.0) * _get_severity(p.get("incident_type_name", ""))
        for p in points
    ]
    weight_threshold = float(min_pts) * 2.0

    # ── Step 1: pre-compute ST-neighborhoods ──────────────────────────────
    neighborhoods: List[List[int]] = []
    is_core: List[bool] = []
    for i, p in enumerate(points):
        nbs: List[int] = []
        for j, q in enumerate(points):
            if _haversine_meters(p["lat"], p["lon"], q["lat"], q["lon"]) > eps_meters:
                continue
            if eps_seconds > 0 and abs(ts[i] - ts[j]) > eps_seconds:
                continue
            nbs.append(j)
        neighborhoods.append(nbs)
        nb_weight = sum(weights[j] for j in nbs)
        is_core.append(len(nbs) >= min_pts or nb_weight >= weight_threshold)

    # ── Step 2: expand clusters from core points ───────────────────────────
    labels: List[int] = [-1] * n
    visited: List[bool] = [False] * n
    cluster_id = 0

    for i in range(n):
        if visited[i] or not is_core[i]:
            continue
        visited[i] = True
        labels[i] = cluster_id
        queue = list(neighborhoods[i])
        qi = 0
        while qi < len(queue):
            j = queue[qi]; qi += 1
            if not visited[j]:
                visited[j] = True
                labels[j] = cluster_id
                if is_core[j]:
                    for cand in neighborhoods[j]:
                        if cand not in queue:
                            queue.append(cand)
            elif labels[j] == -1:
                labels[j] = cluster_id
        cluster_id += 1

    return labels, is_core


def _weighted_centroid(
    pts: List[Dict[str, Any]],
    *,
    time_window_hours: float,
) -> Tuple[float, float]:
    """
    Compute trust × severity × recency weighted centroid.
    Falls back to simple average if total weight is zero.
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    half_life = max(1.0, float(time_window_hours) * 3600 / 2)
    total_w = 0.0
    w_lat = 0.0
    w_lon = 0.0
    for p in pts:
        trust_w = float(p.get("trust", 100.0)) / 100.0
        sev_w = _get_severity(p.get("incident_type_name", ""))
        rt = p.get("reported_at")
        age = 0.0
        if rt:
            try:
                age = max(0.0, now_ts - rt.timestamp())
            except Exception:
                pass
        recency = math.exp(-age / half_life)
        w = trust_w * sev_w * recency
        w_lat += p["lat"] * w
        w_lon += p["lon"] * w
        total_w += w
    if total_w > 0:
        return w_lat / total_w, w_lon / total_w
    n = len(pts)
    return (sum(p["lat"] for p in pts) / n, sum(p["lon"] for p in pts) / n)


def _temporal_intensity(pts: List[Dict[str, Any]]) -> float:
    """Incidents per hour within the cluster's own time span."""
    ts_list = []
    for p in pts:
        rt = p.get("reported_at")
        if rt:
            try:
                ts_list.append(rt.timestamp())
            except Exception:
                pass
    if len(ts_list) < 2:
        return float(len(pts))
    span_hours = (max(ts_list) - min(ts_list)) / 3600.0
    return len(pts) / max(0.1, span_hours)


def _trend_direction(pts: List[Dict[str, Any]]) -> str:
    """Compare recent vs older half of cluster time span."""
    ts_list = sorted(
        p["reported_at"].timestamp()
        for p in pts
        if p.get("reported_at")
    )
    if len(ts_list) < 4:
        return "stable"
    mid = (ts_list[0] + ts_list[-1]) / 2.0
    recent = sum(1 for t in ts_list if t >= mid)
    older  = sum(1 for t in ts_list if t < mid)
    if older == 0:
        return "stable"
    ratio = recent / older
    if ratio >= 1.35:
        return "rising"
    if ratio <= 0.65:
        return "falling"
    return "stable"


def _lifecycle_state(
    db: Session,
    center_lat: float,
    center_long: float,
    incident_count: int,
    eps_meters: float,
    time_window_hours: float,
) -> str:
    """
    Determine cluster lifecycle by comparing with the most recent previous
    hotspot in the same geographic vicinity.
    """
    deg_tol = max(0.005, (eps_meters * 2) / 111_000)
    prev = (
        db.query(Hotspot)
        .filter(
            Hotspot.center_lat.between(center_lat - deg_tol, center_lat + deg_tol),
            Hotspot.center_long.between(center_long - deg_tol, center_long + deg_tol),
            Hotspot.detected_at < datetime.now(timezone.utc) - timedelta(minutes=5),
            Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=time_window_hours * 3),
        )
        .order_by(Hotspot.detected_at.desc())
        .first()
    )
    if prev is None:
        return "emerging"
    ratio = incident_count / max(1, prev.incident_count or 1)
    if ratio >= 1.4:
        return "escalating"
    if ratio <= 0.6:
        return "declining"
    if ratio > 1.1:
        return "active"
    return "stable"


def _cluster_confidence(pts: List[Dict[str, Any]]) -> float:
    """0–1 confidence combining core ratio, avg trust, and size."""
    n = len(pts)
    core_ratio = sum(1 for p in pts if p.get("is_core")) / max(1, n)
    avg_trust  = sum(float(p.get("trust", 100.0)) for p in pts) / max(1, n) / 100.0
    size_score = min(1.0, n / 10.0)
    return round(core_ratio * 0.35 + avg_trust * 0.45 + size_score * 0.20, 4)


def _convex_hull_points(latlon: List[Tuple[float, float]]) -> List[List[float]]:
    """Monotone-chain convex hull. Input/output: [(lat, lon)] / [[lat, lon]]."""
    if len(latlon) < 3:
        return [[lat, lon] for lat, lon in latlon]
    pts = sorted(latlon, key=lambda p: (p[1], p[0]))  # sort by lon, lat

    def cross(o, a, b):
        return (a[1] - o[1]) * (b[0] - o[0]) - (a[0] - o[0]) * (b[1] - o[1])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    return [[lat, lon] for lat, lon in hull]


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
    require_leader_confirmation: Optional[bool] = None,
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
            # Only confirmed/verified reports — rejected ones must never appear on the map
            Report.status != "rejected",
            Report.verification_status != "rejected",
            Report.rule_status != "rejected",
        )
        .options(
            selectinload(Report.ml_predictions),
            joinedload(Report.incident_type),
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
        if not _is_report_eligible(
            r, require_leader_confirmation=require_leader_confirmation
        ):
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
            "incident_type_name": r.incident_type.type_name if r.incident_type else "",
            "reported_at": r.reported_at,
            "village_location_id": r.village_location_id,
        })

    if len(eligible_reports) < max(1, int(min_incidents)):
        return 0

    created = _create_geographic_hotspots(
        db,
        eligible_reports,
        radius_meters,
        min_incidents,
        effective_time_window_hours,
        enforce_time_span=not analyze_all_reports,
    )
    print(
        f"Created {created} DBSCAN hotspots "
        f"from {len(eligible_reports)} eligible reports in {effective_time_window_hours}h"
    )
    
    return created


def ensure_hotspots_materialized(
    db: Session,
    *,
    time_window_hours: int = 8760,
) -> int:
    """
    Build hotspots when the table is empty (e.g. first Safety Map load or after
    a manual clear).  Uses a PostgreSQL advisory lock so concurrent requests
    never race and create duplicates.

    For real-time pickup of new reports, use the /hotspots/recompute endpoint
    which clears + rebuilds safely with an explicit user action.
    """
    from sqlalchemy import text as _text

    # Fast path: table already has data — nothing to do.
    existing = db.execute(_text("SELECT 1 FROM hotspots LIMIT 1")).scalar()
    if existing is not None:
        return 0

    # Acquire a session-level advisory lock (id=7654321) so only ONE concurrent
    # request runs the build; others skip and return 0.
    acquired = db.execute(
        _text("SELECT pg_try_advisory_lock(7654321)")
    ).scalar()
    if not acquired:
        return 0  # another request is already building — skip

    try:
        # Double-check after acquiring lock (another request may have built
        # while we waited for the lock).
        existing2 = db.execute(_text("SELECT 1 FROM hotspots LIMIT 1")).scalar()
        if existing2 is not None:
            return 0

        tw, mi, rm = get_hotspot_params_from_db(
            db,
            time_window_hours=time_window_hours,
            min_incidents=DEFAULT_MIN_INCIDENTS,
            radius_meters=DEFAULT_RADIUS_METERS,
        )
        trust_min = get_hotspot_trust_min_from_db(db, DEFAULT_TRUST_MIN)
        created = create_hotspots_from_reports(
            db,
            time_window_hours=max(int(tw), int(time_window_hours)),
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=True,
            require_leader_confirmation=False,
        )
        if created > 0:
            db.commit()
        return created
    finally:
        db.execute(_text("SELECT pg_advisory_unlock(7654321)"))


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
    time_window_hours: int,
    *,
    enforce_time_span: bool = True,
) -> int:
    """
    Enhanced ST-DBSCAN clustering pipeline:

    1. Group eligible reports by broad crime category (violent/property/drug/…).
    2. Run ST-DBSCAN per group — unrelated crime types cannot merge.
    3. For each cluster: compute weighted centroid, severity, temporal intensity,
       lifecycle state, trend direction, convex-hull polygon.
    4. Persist clusters with full metadata.
    """
    eps_m   = max(50.0, float(radius_meters))
    # Temporal epsilon: incidents must be within (window / 4) of each other.
    # Minimum 6 h, maximum 72 h so very wide query windows don't disable ST.
    raw_eps_t = float(time_window_hours) * 3600 / 4
    eps_t     = max(6 * 3600, min(72 * 3600, raw_eps_t))
    dbscan_min_pts = max(2, int(min_incidents))
    # Severity override allows a single very high-severity point to be a core.

    # ── 1. Group by crime category ─────────────────────────────────────────
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in reports:
        grp = _get_crime_group(r.get("incident_type_name", ""))
        groups.setdefault(grp, []).append(r)

    created = 0

    def _create_solo_hotspot(db, group_name, p, radius_meters, time_window_hours):
        """Create a single-incident hotspot for each DBSCAN noise / under-sized cluster point.

        Each report gets its own hotspot row so that two reports at the same location
        both appear on the map. Idempotency is achieved by checking whether a hotspot
        already exists that links to *this specific report* (re-run safety).
        """
        nonlocal created
        solo_lat  = p["lat"]
        solo_long = p["lon"]
        i_name    = p.get("incident_type_name", "Unknown")
        i_tid     = p.get("incident_type_id")
        solo_sev  = _get_severity(i_name)
        report_id_str = str(p["report"].report_id)

        # Idempotency: if a hotspot already links this exact report, skip creation.
        already = db.execute(
            text(
                "SELECT hr.hotspot_id FROM hotspot_reports hr "
                "JOIN hotspots h ON h.hotspot_id = hr.hotspot_id "
                "WHERE hr.report_id = :rid AND h.incident_count = 1"
            ),
            {"rid": report_id_str},
        ).fetchone()
        if already:
            return

        hotspot = Hotspot(
            center_lat          = Decimal(str(solo_lat)),
            center_long         = Decimal(str(solo_long)),
            radius_meters       = Decimal(str(radius_meters)),
            incident_count      = 1,
            risk_level          = "low",
            time_window_hours   = time_window_hours,
            incident_type_id    = int(i_tid) if i_tid else None,
            detected_at         = datetime.now(timezone.utc),
            lifecycle_state     = "emerging",
            composition         = json.dumps({i_name: 1}),
            temporal_intensity  = Decimal("0.0"),
            severity_score      = Decimal(str(round(solo_sev, 4))),
            trend_direction     = "stable",
            cluster_confidence  = Decimal("1.0"),
            polygon_points      = None,
            crime_group         = group_name,
        )
        db.add(hotspot)
        db.flush()
        created += 1

        db.execute(
            text(
                "INSERT INTO hotspot_reports (hotspot_id, report_id, is_core) "
                "VALUES (:hid, :rid, true) "
                "ON CONFLICT (hotspot_id, report_id) DO UPDATE SET is_core = true"
            ),
            {"hid": hotspot.hotspot_id, "rid": report_id_str},
        )

    for group_name, group_pts in groups.items():
        if len(group_pts) < dbscan_min_pts:
            # All points in a too-small group are effectively solo noise
            for p in group_pts:
                _create_solo_hotspot(db, group_name, p, radius_meters, time_window_hours)
            continue

        # ── 2. ST-DBSCAN ──────────────────────────────────────────────────
        labels, is_core_flags = _st_dbscan(group_pts, eps_m, eps_t, dbscan_min_pts)

        raw_clusters: Dict[int, List[Dict[str, Any]]] = {}
        for idx, label in enumerate(labels):
            if label < 0:
                continue
            tagged = {**group_pts[idx], "is_core": is_core_flags[idx]}
            raw_clusters.setdefault(label, []).append(tagged)

        for cluster_pts in raw_clusters.values():
            incident_count = len(cluster_pts)
            if incident_count < int(min_incidents):
                # Under-sized DBSCAN cluster — treat each point as a solo incident
                for p in cluster_pts:
                    _create_solo_hotspot(db, group_name, p, radius_meters, time_window_hours)
                continue

            # Time-span guard
            cluster_pts_sorted = sorted(
                cluster_pts,
                key=lambda p: p["reported_at"] if p.get("reported_at") else datetime.min.replace(tzinfo=timezone.utc),
            )
            if enforce_time_span:
                try:
                    span_h = (
                        cluster_pts_sorted[-1]["reported_at"] -
                        cluster_pts_sorted[0]["reported_at"]
                    ).total_seconds() / 3600
                    if span_h > float(time_window_hours):
                        continue
                except Exception:
                    pass

            # ── 3. Cluster analytics ──────────────────────────────────────
            center_lat, center_long = _weighted_centroid(cluster_pts, time_window_hours=time_window_hours)
            avg_trust   = sum(p.get("trust", 100.0) for p in cluster_pts) / incident_count
            sev_score   = sum(
                _get_severity(p.get("incident_type_name", "")) * float(p.get("trust", 100.0)) / 100.0
                for p in cluster_pts
            ) / incident_count
            t_intensity = _temporal_intensity(cluster_pts)
            trend       = _trend_direction(cluster_pts)
            conf        = _cluster_confidence(cluster_pts)
            lifecycle   = _lifecycle_state(db, center_lat, center_long, incident_count, eps_m, time_window_hours)

            # Composition breakdown
            composition: Dict[str, int] = {}
            for p in cluster_pts:
                t_name = p.get("incident_type_name") or "Unknown"
                composition[t_name] = composition.get(t_name, 0) + 1
            dominant_type_name = max(composition, key=composition.get)

            # Dominant incident_type_id (FK)
            type_id_counts: Dict[int, int] = {}
            for p in cluster_pts:
                tid = int(p.get("incident_type_id") or 0)
                if tid:
                    type_id_counts[tid] = type_id_counts.get(tid, 0) + 1
            dominant_type_id: Optional[int] = (
                max(type_id_counts, key=type_id_counts.get) if type_id_counts else None
            )

            # Convex hull polygon
            hull_pts_latlon = [(p["lat"], p["lon"]) for p in cluster_pts]
            hull = _convex_hull_points(hull_pts_latlon)
            polygon_json = json.dumps(hull) if hull else None

            # Risk classification
            area_sqkm = max(0.001, 3.14159 * (float(radius_meters) / 1000.0) ** 2)
            cluster_density = incident_count / area_sqkm
            classification_result = predict_cluster_classification(
                incident_count=incident_count,
                avg_trust=avg_trust,
                cluster_density=cluster_density,
                time_window_hours=time_window_hours,
            )
            risk_level = classification_to_risk_level(classification_result["classification"])

            # ── 4. Persist ────────────────────────────────────────────────
            existing = (
                db.query(Hotspot)
                .filter(
                    Hotspot.center_lat.between(center_lat - 0.01, center_lat + 0.01),
                    Hotspot.center_long.between(center_long - 0.01, center_long + 0.01),
                    Hotspot.crime_group == group_name,
                    Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24),
                )
                .order_by(Hotspot.detected_at.desc())
                .first()
            )

            if existing:
                hotspot = existing
                hotspot.center_lat          = Decimal(str(center_lat))
                hotspot.center_long         = Decimal(str(center_long))
                hotspot.radius_meters       = Decimal(str(radius_meters))
                hotspot.incident_count      = incident_count
                hotspot.risk_level          = risk_level
                hotspot.time_window_hours   = time_window_hours
                hotspot.incident_type_id    = dominant_type_id
                hotspot.detected_at         = datetime.now(timezone.utc)
                hotspot.lifecycle_state     = lifecycle
                hotspot.composition         = json.dumps(composition)
                hotspot.temporal_intensity  = Decimal(str(round(t_intensity, 4)))
                hotspot.severity_score      = Decimal(str(round(sev_score, 4)))
                hotspot.trend_direction     = trend
                hotspot.cluster_confidence  = Decimal(str(conf))
                hotspot.polygon_points      = polygon_json
                hotspot.crime_group         = group_name
                db.execute(
                    text("DELETE FROM hotspot_reports WHERE hotspot_id = :hid"),
                    {"hid": hotspot.hotspot_id},
                )
            else:
                hotspot = Hotspot(
                    center_lat          = Decimal(str(center_lat)),
                    center_long         = Decimal(str(center_long)),
                    radius_meters       = Decimal(str(radius_meters)),
                    incident_count      = incident_count,
                    risk_level          = risk_level,
                    time_window_hours   = time_window_hours,
                    incident_type_id    = dominant_type_id,
                    detected_at         = datetime.now(timezone.utc),
                    lifecycle_state     = lifecycle,
                    composition         = json.dumps(composition),
                    temporal_intensity  = Decimal(str(round(t_intensity, 4))),
                    severity_score      = Decimal(str(round(sev_score, 4))),
                    trend_direction     = trend,
                    cluster_confidence  = Decimal(str(conf)),
                    polygon_points      = polygon_json,
                    crime_group         = group_name,
                )
                db.add(hotspot)
                db.flush()
                created += 1

            for p in cluster_pts:
                db.execute(
                    text(
                        "INSERT INTO hotspot_reports (hotspot_id, report_id, is_core) "
                        "VALUES (:hid, :rid, :ic) "
                        "ON CONFLICT (hotspot_id, report_id) DO UPDATE SET is_core = EXCLUDED.is_core"
                    ),
                    {
                        "hid": hotspot.hotspot_id,
                        "rid": str(p["report"].report_id),
                        "ic": bool(p.get("is_core", False)),
                    },
                )

        # ── Solo incidents (DBSCAN noise points) ─────────────────────────────
        noise_indices = [i for i, lbl in enumerate(labels) if lbl < 0]
        for idx in noise_indices:
            _create_solo_hotspot(db, group_name, group_pts[idx], radius_meters, time_window_hours)

    return created
