"""Hotspot auto-creation using ST-DBSCAN over trusted incident reports."""

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload, selectinload

logger = logging.getLogger(__name__)

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
from app.core.websocket import refresh_entity


DEFAULT_TIME_WINDOW_HOURS = 720   # 30 days — wide enough to include sparse report data
DEFAULT_MIN_INCIDENTS = 4         # minimum 4 incidents to form a cluster
# 500 m is realistic for Rwandan village-level reporting where homes and farms
# spread across several hundred metres. 300 m was too tight, causing many
# geographically co-located incidents to scatter into separate noise points.
DEFAULT_RADIUS_METERS = 500
# Trust ≥ 30 admits all reports except those with no score at all. The computed
# floor for unverified/pending reports is 35 (> 30), so every non-rejected report
# effectively enters the pipeline. Raise to 50 to require at least rule-passed
# status (rule_passed → trust=65). Configurable via dbscan.trust_min system key.
DEFAULT_TRUST_MIN = 30

# ─── Crime taxonomy ──────────────────────────────────────────────────────────

#: Groups of related crime types that may co-cluster.
#: Keys are group names; values are lowercase substrings to match against.
#:
#: Design rules:
#:  • Each group covers a *behavioural* category so that incidents
#:    sharing the same criminal modus operandi can form hotspots together.
#:  • "robbery" intentionally lives in property (it is primarily a property
#:    offence); "robbery with violence" and "armed robbery" live in violent.
#:  • "harassment" is only in sexual — non-sexual harassment should be
#:    reported as "public disturbance" or "threats".
#:  • Unknown / miscellaneous types map to "other" and can still cluster
#:    spatially with each other but not across groups.
CRIME_GROUPS: Dict[str, List[str]] = {
    "violent":      ["assault", "domestic violence", "threat", "threats",
                     "murder", "robbery with violence", "armed robbery",
                     "gbv", "gender-based violence", "bodily harm",
                     "manslaughter", "fighting", "mob justice",
                     "unlawful wounding"],
    "property":     ["theft", "robbery", "burglary", "vandalism",
                     "property damage", "breaking and entering",
                     "shoplifting", "motor vehicle theft", "pickpocketing",
                     "vehicle theft", "stolen", "arson"],
    "drug":         ["drug activity", "drug trafficking", "substance abuse",
                     "narcotics", "drug possession", "drug use",
                     "illicit brew", "illegal alcohol"],
    "fraud":        ["fraud", "scam", "cybercrime", "identity theft",
                     "forgery", "corruption", "bribery", "financial crime",
                     "extortion", "money laundering", "fake documents"],
    "sexual":       ["sexual assault", "harassment", "rape", "indecent",
                     "sexual harassment", "defilement", "sexual violence",
                     "indecent exposure"],
    "traffic":      ["traffic", "accident", "hit and run", "dui",
                     "road accident", "reckless driving", "drunk driving"],
    "public_order": ["suspicious", "public disturbance", "trespass",
                     "loitering", "illegal gathering", "riot",
                     "noise", "curfew", "unlawful assembly",
                     "prohibited gathering"],
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
    # Unmapped type — goes into the "other" catch-all cluster.
    # If this type is common, add it to CRIME_GROUPS above to improve grouping.
    logger.debug("[hotspot] unmapped crime type %r → group=other", type_name)
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

    # ── Step 3: absorb noise points near any cluster member ───────────────
    # Standard DBSCAN only absorbs border points near core points.
    # This pass catches points that are within eps of border points
    # (transitively reachable but missed because border points don't expand).
    changed = True
    while changed:
        changed = False
        for i in range(n):
            if labels[i] != -1:
                continue  # already in a cluster
            for j in neighborhoods[i]:
                if labels[j] != -1:
                    labels[i] = labels[j]
                    changed = True
                    break

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


# ─── Improvement 1: Corroboration ────────────────────────────────────────────

def _count_unique_reporters(pts: List[Dict[str, Any]]) -> int:
    """
    Return the number of distinct people who submitted reports in this cluster.

    Uses ``reported_by_user_id`` on the Report object when available, falling
    back to the report's UUID so that guest/anonymous reports each count once.
    """
    reporter_ids: set = set()
    for p in pts:
        r = p.get("report")
        if r is None:
            continue
        uid = (
            getattr(r, "reported_by_user_id", None)
            or getattr(r, "reporter_id", None)
        )
        if uid is not None:
            reporter_ids.add(str(uid))
        else:
            # Anonymous/guest report — count each report as its own reporter
            reporter_ids.add(str(getattr(r, "report_id", id(r))))
    return max(1, len(reporter_ids))


def _corroboration_score(pts: List[Dict[str, Any]], min_reporters: int = 2) -> float:
    """
    Composite corroboration score 0.0–1.0.

    Three sub-scores:
      reporter_diversity : fraction of independent reporters relative to target
      trust_consistency  : 1 − normalized variance of trust scores
      time_spread        : spread of report timestamps (full score at 24 h+)

    A perfectly corroborated cluster (many reporters, consistent trust,
    spread over 24 h) approaches 1.0.  A cluster where one person filed all
    reports minutes apart approaches 0.0.
    """
    n = len(pts)
    unique_reporters = _count_unique_reporters(pts)

    reporter_diversity = min(1.0, unique_reporters / max(1, min_reporters * 2))

    trusts = [float(p.get("trust", 100.0)) for p in pts]
    avg_trust = sum(trusts) / max(1, n)
    variance = sum((t - avg_trust) ** 2 for t in trusts) / max(1, n)
    trust_consistency = 1.0 - min(1.0, variance / (25.0 ** 2))

    ts_list = [p["reported_at"].timestamp() for p in pts if p.get("reported_at")]
    if len(ts_list) >= 2:
        span_h = (max(ts_list) - min(ts_list)) / 3600.0
        time_spread = min(1.0, span_h / 24.0)
    else:
        time_spread = 0.0

    return round(
        reporter_diversity * 0.50 + trust_consistency * 0.25 + time_spread * 0.25,
        4,
    )


# ─── Improvement 3: Adaptive clustering radius ────────────────────────────────

def _adaptive_radius_meters(
    pts: List[Dict[str, Any]],
    *,
    base_radius: float = DEFAULT_RADIUS_METERS,
) -> float:
    """
    Derive a clustering radius suited to the geographic density of the input
    points.  The user-provided base_radius is always respected as a floor —
    adaptive logic can only *widen* beyond the user's explicit choice, never
    shrink below it.

    Heuristic:
      - Sample pairwise distances across up to 25 points.
      - If the median pair-distance < 200 m  → dense; use base_radius (user floor).
      - If the median pair-distance > 800 m  → sparse; widen proportionally.
      - Otherwise                            → keep base_radius.

    The result is clamped to [base_radius, 10 000 m].
    """
    n = len(pts)
    if n < 3:
        return base_radius

    sample = pts[: min(25, n)]
    dists: List[float] = []
    for i, p in enumerate(sample):
        for j in range(i + 1, len(sample)):
            q = sample[j]
            dists.append(_haversine_meters(p["lat"], p["lon"], q["lat"], q["lon"]))

    if not dists:
        return base_radius

    dists.sort()
    median_d = dists[len(dists) // 2]

    if median_d > 800:
        # Sparse points — widen slightly but cap at 1.25x base to prevent
        # district-wide mega-clusters when points are uniformly scattered.
        adaptive = max(base_radius, min(base_radius * 1.25, median_d * 0.8))
    else:
        adaptive = base_radius

    # Never go below the user's requested radius
    adaptive = max(base_radius, adaptive)
    # Upper safety cap at 10 km
    adaptive = min(10000.0, adaptive)

    return round(adaptive, 0)


# ─── Improvement 11: Anomaly / abuse detection ────────────────────────────────

_ANOMALY_FLAG_THRESHOLD = 0.55   # abuse_flag=True when anomaly_score >= this


def _compute_anomaly_score(pts: List[Dict[str, Any]]) -> float:
    """
    Detect coordinated false-report injection.  Returns 0.0–1.0.

    Checked patterns:
      P1 – Time burst   : ≥ 3 reports within 5 minutes → +0.35; ≥ 5 in 30 min → +0.20
      P2 – GPS cloning  : all points identical to 4 d.p. → +0.40
      P3 – Reporter bias: one user > 70 % of reports → +0.25
      P4 – Trust clone  : all trust scores identical (≥ 4 pts) → +0.10
    """
    n = len(pts)
    if n < 2:
        return 0.0

    score = 0.0

    # P1 — time burst
    ts = sorted(p["reported_at"].timestamp() for p in pts if p.get("reported_at"))
    if len(ts) >= 2:
        span_min = (ts[-1] - ts[0]) / 60.0
        if span_min < 5 and n >= 3:
            score += 0.35
        elif span_min < 30 and n >= 5:
            score += 0.20

    # P2 — GPS cloning (same location to 4 decimal places ≈ 11 m)
    lats_r = [round(p["lat"], 4) for p in pts]
    lons_r = [round(p["lon"], 4) for p in pts]
    if len(set(zip(lats_r, lons_r))) == 1 and n >= 3:
        score += 0.40

    # P3 — single reporter dominates
    reporter_counts: Dict[str, int] = {}
    for p in pts:
        r = p.get("report")
        uid = str(
            getattr(r, "reported_by_user_id", None)
            or getattr(r, "reporter_id", None)
            or id(r)
        )
        reporter_counts[uid] = reporter_counts.get(uid, 0) + 1
    if n >= 3 and reporter_counts:
        max_share = max(reporter_counts.values()) / n
        if max_share > 0.70:
            score += 0.25

    # P4 — uniform trust (automated injection signal)
    trusts_r = [round(float(p.get("trust", 100.0)), 1) for p in pts]
    if len(set(trusts_r)) == 1 and n >= 4:
        score += 0.10

    return round(min(1.0, score), 4)


# ─── Improvement 9: Explainability ───────────────────────────────────────────

def _build_explanation(
    *,
    incident_count: int,
    avg_trust: float,
    sev_score: float,
    trend: str,
    lifecycle: str,
    classification: str,
    conf: float,
    t_intensity: float,
    composition: Dict[str, int],
    unique_reporters: int,
    corroboration_score: float,
    anomaly_score: float,
    is_multi_crime_zone: bool = False,
) -> Dict[str, Any]:
    """
    Return a structured JSON-serialisable explanation for every numeric score
    this hotspot carries.  Stored in ``hotspot.explanation_json`` and surfaced
    on the law enforcement dashboard.
    """
    factors: List[Dict[str, Any]] = []

    # Severity
    if sev_score >= 8.0:
        sev_level, sev_note = "high", f"Average severity {sev_score:.1f}/10 — serious crimes dominate this cluster"
    elif sev_score >= 5.0:
        sev_level, sev_note = "medium", f"Moderate severity {sev_score:.1f}/10 — mix of serious and minor incidents"
    else:
        sev_level, sev_note = "low", f"Low severity {sev_score:.1f}/10 — minor incident types"
    factors.append({"factor": "severity", "level": sev_level, "note": sev_note})

    # Trend
    trend_notes = {
        "rising":  "Incident rate is INCREASING — more reports in the recent half of the window than the earlier half",
        "falling": "Incident rate is DECLINING — fewer reports in the recent half; current measures may be working",
        "stable":  "Incident rate is STABLE — consistent volume throughout the observation window",
    }
    factors.append({"factor": "trend", "direction": trend, "note": trend_notes.get(trend, "Unknown trend")})

    # Lifecycle
    lifecycle_notes = {
        "emerging":   "NEW cluster — no prior hotspot detected in this geographic area",
        "active":     "ESTABLISHED cluster — incident count close to the previous detection in this area",
        "escalating": "ESCALATING — incident count ≥ 40 % higher than last detection — immediate attention needed",
        "stable":     "STABLE cluster — volume matching prior detection; sustained patrol recommended",
        "declining":  "DECLINING — incident count ≥ 40 % lower than last detection — current response appears effective",
    }
    factors.append({"factor": "lifecycle", "state": lifecycle, "note": lifecycle_notes.get(lifecycle, "")})

    # Corroboration
    if corroboration_score >= 0.70:
        corr_level = "strong"
        corr_note = f"{unique_reporters} unique reporter(s) — high independent corroboration"
    elif corroboration_score >= 0.40:
        corr_level = "moderate"
        corr_note = f"{unique_reporters} unique reporter(s) — moderate corroboration"
    else:
        corr_level = "weak"
        corr_note = f"Only {unique_reporters} unique reporter(s) — low independent corroboration; treat with caution"
    factors.append({"factor": "corroboration", "level": corr_level, "score": corroboration_score, "note": corr_note})

    # Confidence breakdown
    factors.append({
        "factor": "confidence",
        "score": conf,
        "note": (
            f"Cluster confidence {conf:.0%} = "
            "core-point ratio × 0.35 + avg-trust × 0.45 + cluster-size-score × 0.20"
        ),
    })

    # Anomaly warning
    if anomaly_score >= _ANOMALY_FLAG_THRESHOLD:
        factors.append({
            "factor": "anomaly",
            "score": anomaly_score,
            "level": "high",
            "warning": (
                "High anomaly score — pattern consistent with coordinated false reporting "
                "(time burst, GPS cloning, or single-reporter dominance). "
                "Verify reports independently before acting."
            ),
        })
    elif anomaly_score > 0.20:
        factors.append({
            "factor": "anomaly",
            "score": anomaly_score,
            "level": "low",
            "warning": "Slight anomaly signal — monitoring suggested",
        })

    # Multi-crime zone
    if is_multi_crime_zone:
        factors.append({
            "factor": "multi_crime_zone",
            "note": "This hotspot overlaps with hotspots of different crime categories — composite risk zone requiring coordinated multi-unit response",
        })

    return {
        "classification_factors": factors,
        "score_breakdown": {
            "severity_score": round(sev_score, 3),
            "trust_average": round(avg_trust, 1),
            "temporal_intensity": round(t_intensity, 4),
            "cluster_confidence": round(conf, 4),
            "corroboration_score": corroboration_score,
            "anomaly_score": anomaly_score,
        },
        "top_crime_types": sorted(composition.items(), key=lambda x: x[1], reverse=True)[:5],
        "incident_count": incident_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Improvement 8: Prediction ───────────────────────────────────────────────

def _predict_next_state(lifecycle: str, trend: str) -> str:
    """
    Rule-based prediction of the next lifecycle state.

    This prediction is stored on the hotspot and checked against the actual
    state on the next clustering run so prediction accuracy can be measured.

    Transition table
    ────────────────
    current / trend       rising          stable          falling
    ──────────────────────────────────────────────────────────────
    emerging              escalating      active          declining
    active                escalating      active          stable
    escalating            escalating      active          stable
    stable                active          stable          declining
    declining             active          declining       declining
    """
    t = (trend or "stable").lower()
    s = (lifecycle or "active").lower()

    table: Dict[str, Dict[str, str]] = {
        "emerging":   {"rising": "escalating", "stable": "active",    "falling": "declining"},
        "active":     {"rising": "escalating", "stable": "active",    "falling": "stable"},
        "escalating": {"rising": "escalating", "stable": "active",    "falling": "stable"},
        "stable":     {"rising": "active",     "stable": "stable",    "falling": "declining"},
        "declining":  {"rising": "active",     "stable": "declining", "falling": "declining"},
    }
    return table.get(s, {}).get(t, "active")


# ─── Improvement 12: Audit trail helper ──────────────────────────────────────

def _record_hotspot_event(
    db: Session,
    hotspot_id: int,
    event_type: str,
    *,
    previous_state: Optional[str] = None,
    new_state: Optional[str] = None,
    event_data: Optional[Dict[str, Any]] = None,
    note: Optional[str] = None,
    created_by_user_id: Optional[int] = None,
) -> None:
    """
    Append an immutable event to hotspot_events for the given hotspot.
    Failures are logged and swallowed — event logging must never abort the
    clustering pipeline.
    """
    try:
        from app.models.hotspot_event import HotspotEvent
        event = HotspotEvent(
            hotspot_id=hotspot_id,
            event_type=event_type,
            previous_state=previous_state,
            new_state=new_state,
            event_data=json.dumps(event_data) if event_data else None,
            note=note,
            created_by_user_id=created_by_user_id,
        )
        db.add(event)
        db.flush()
    except Exception as _e:
        logger.warning("[hotspot_event] failed to record %s for hotspot %s: %s", event_type, hotspot_id, _e)


# ─── Improvement 2: Multi-crime zone detection ────────────────────────────────

def detect_multi_crime_zones(db: Session, eps_meters: float) -> int:
    """
    Post-clustering pass: mark hotspots that overlap with hotspots of a
    *different* crime group within ``eps_meters``.

    Called once after ``_create_geographic_hotspots`` completes all groups.
    Returns the number of hotspots flagged.
    """
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    recent = (
        db.query(Hotspot)
        .filter(Hotspot.detected_at >= recent_cutoff)
        .all()
    )
    if len(recent) < 2:
        return 0

    flagged = 0
    for h in recent:
        if not h.crime_group or h.crime_group == "other":
            h.is_multi_crime_zone = False
            h.multi_crime_groups = None
            continue

        lat = float(h.center_lat)
        lon = float(h.center_long)
        nearby_groups: set = set()

        for other in recent:
            if other.hotspot_id == h.hotspot_id:
                continue
            if (not other.crime_group) or other.crime_group == h.crime_group:
                continue
            if _haversine_meters(lat, lon, float(other.center_lat), float(other.center_long)) <= eps_meters:
                nearby_groups.add(other.crime_group)

        if nearby_groups:
            all_groups = sorted([h.crime_group] + list(nearby_groups))
            was_flagged = bool(h.is_multi_crime_zone)
            h.is_multi_crime_zone = True
            h.multi_crime_groups = json.dumps(all_groups)
            flagged += 1
            if not was_flagged:
                _record_hotspot_event(
                    db,
                    h.hotspot_id,
                    "multi_crime_flagged",
                    new_state=h.lifecycle_state,
                    event_data={"crime_groups": all_groups},
                    note=f"Overlaps with {', '.join(nearby_groups)} hotspot(s) within {int(eps_meters)} m",
                )
        else:
            h.is_multi_crime_zone = False
            h.multi_crime_groups = None

    logger.info("[hotspot] multi-crime zone pass: %d hotspot(s) flagged", flagged)
    return flagged


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

    logger.info(
        "[hotspot] pipeline start — window=%dh (%s → %s), "
        "raw_reports_queried=%d, min_incidents=%d, radius_m=%.0f, trust_min=%.0f",
        effective_time_window_hours, window_start.isoformat(), window_end.isoformat(),
        len(reports), min_incidents, radius_meters, trust_min,
    )

    # Filter eligible reports
    excluded_not_eligible = 0
    excluded_no_coords = 0
    excluded_type_filter = 0
    excluded_low_trust = 0
    eligible_reports = []
    for r in reports:
        if not _is_report_eligible(
            r, require_leader_confirmation=require_leader_confirmation
        ):
            excluded_not_eligible += 1
            continue
        if incident_type_id is not None and int(r.incident_type_id) != int(incident_type_id):
            excluded_type_filter += 1
            continue

        try:
            lat = float(r.latitude)
            lon = float(r.longitude)
        except (TypeError, ValueError):
            excluded_no_coords += 1
            continue

        trust = _report_trust_score(r)
        if trust < float(trust_min):
            excluded_low_trust += 1
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

    logger.info(
        "[hotspot] filtering: eligible=%d  excluded(not_eligible=%d, no_coords=%d, "
        "type_filter=%d, low_trust=%d)",
        len(eligible_reports), excluded_not_eligible, excluded_no_coords,
        excluded_type_filter, excluded_low_trust,
    )

    if len(eligible_reports) < max(1, int(min_incidents)):
        logger.warning(
            "[hotspot] too few eligible reports (%d) for min_incidents=%d — skipping clustering",
            len(eligible_reports), min_incidents,
        )
        return 0

    created = _create_geographic_hotspots(
        db,
        eligible_reports,
        radius_meters,
        min_incidents,
        effective_time_window_hours,
        enforce_time_span=not analyze_all_reports,
    )
    logger.info(
        "[hotspot] pipeline complete — created=%d hotspots from %d eligible reports "
        "(window=%dh, radius=%.0fm)",
        created, len(eligible_reports), effective_time_window_hours, radius_meters,
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
    time_window_hours: int,
    radius_meters: float = DEFAULT_RADIUS_METERS,
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
    
    merged = _merge_nearby_hotspots_by_distance(db, max(50.0, float(radius_meters)))
    if merged:
        print(f"Merged {merged} nearby hotspot group(s) into multi-report clusters")
    if created or merged:
        refresh_entity("hotspot", action="clustered", created=created, merged=merged)
    return created


def _merge_nearby_hotspots_by_distance(db: Session, eps_meters: float) -> int:
    """Fuse hotspot rows whose centers fall within eps_meters (same-area clusters)."""
    rows = db.query(Hotspot).order_by(Hotspot.hotspot_id.asc()).all()
    if len(rows) < 2:
        return 0

    consumed: set[int] = set()
    merged_groups = 0
    for i, primary in enumerate(rows):
        if primary.hotspot_id in consumed:
            continue
        lat1 = float(primary.center_lat)
        lon1 = float(primary.center_long)
        group = [primary]
        for other in rows[i + 1 :]:
            if other.hotspot_id in consumed:
                continue
            if _haversine_meters(
                lat1,
                lon1,
                float(other.center_lat),
                float(other.center_long),
            ) <= eps_meters:
                group.append(other)
        if len(group) < 2:
            continue
        _absorb_hotspot_group(db, group)
        merged_groups += 1
        for h in group:
            consumed.add(h.hotspot_id)
    return merged_groups


def _absorb_hotspot_group(db: Session, hotspots: List[Hotspot]) -> None:
    """Combine multiple hotspot rows into one multi-report cluster."""
    primary = hotspots[0]
    all_report_ids: List[str] = []
    composition: Dict[str, int] = {}
    lat_sum = 0.0
    lon_sum = 0.0
    weight_sum = 0.0

    for h in hotspots:
        try:
            comp = json.loads(h.composition) if h.composition else {}
            for k, v in comp.items():
                composition[k] = composition.get(k, 0) + int(v)
        except Exception:
            pass
        w = max(1, int(h.incident_count or 1))
        lat_sum += float(h.center_lat) * w
        lon_sum += float(h.center_long) * w
        weight_sum += w
        links = db.execute(
            text("SELECT report_id FROM hotspot_reports WHERE hotspot_id = :hid"),
            {"hid": h.hotspot_id},
        ).fetchall()
        for (rid,) in links:
            all_report_ids.append(str(rid))

    all_report_ids = list(dict.fromkeys(all_report_ids))
    incident_count = len(all_report_ids) if all_report_ids else sum(
        int(h.incident_count or 0) for h in hotspots
    )
    center_lat = lat_sum / weight_sum if weight_sum else float(primary.center_lat)
    center_long = lon_sum / weight_sum if weight_sum else float(primary.center_long)
    tw = int(primary.time_window_hours or DEFAULT_TIME_WINDOW_HOURS)
    radius_m = float(primary.radius_meters or DEFAULT_RADIUS_METERS)
    area_sqkm = max(0.001, 3.14159 * (radius_m / 1000.0) ** 2)
    avg_trust = 75.0
    classification_result = predict_cluster_classification(
        incident_count=incident_count,
        avg_trust=avg_trust,
        cluster_density=incident_count / area_sqkm,
        time_window_hours=tw,
    )
    risk_level = classification_to_risk_level(classification_result["classification"])

    primary.center_lat = Decimal(str(center_lat))
    primary.center_long = Decimal(str(center_long))
    primary.incident_count = incident_count
    primary.risk_level = risk_level
    primary.lifecycle_state = classification_result["classification"]
    primary.composition = json.dumps(composition) if composition else primary.composition
    primary.detected_at = datetime.now(timezone.utc)
    primary.crime_group = primary.crime_group or "mixed"
    db.flush()

    db.execute(
        text("DELETE FROM hotspot_reports WHERE hotspot_id = :hid"),
        {"hid": primary.hotspot_id},
    )
    for rid in all_report_ids:
        db.execute(
            text(
                "INSERT INTO hotspot_reports (hotspot_id, report_id, is_core) "
                "VALUES (:hid, :rid, true) "
                "ON CONFLICT (hotspot_id, report_id) DO UPDATE SET is_core = true"
            ),
            {"hid": primary.hotspot_id, "rid": rid},
        )

    for h in hotspots[1:]:
        db.execute(
            text("DELETE FROM hotspot_reports WHERE hotspot_id = :hid"),
            {"hid": h.hotspot_id},
        )
        db.delete(h)
    db.flush()


def _try_append_report_to_nearby_hotspot(
    db: Session,
    p: Dict[str, Any],
    eps_m: float,
    group_name: str,
) -> bool:
    """Link a report to an existing hotspot when it falls within clustering radius."""
    lat = float(p["lat"])
    lon = float(p["lon"])
    delta = max(0.001, float(eps_m) / 111000.0)
    candidates = (
        db.query(Hotspot)
        .filter(
            Hotspot.center_lat.between(lat - delta, lat + delta),
            Hotspot.center_long.between(lon - delta, lon + delta),
        )
        .all()
    )
    report_id_str = str(p["report"].report_id)
    for h in candidates:
        if _haversine_meters(lat, lon, float(h.center_lat), float(h.center_long)) > eps_m:
            continue
        exists = db.execute(
            text(
                "SELECT 1 FROM hotspot_reports WHERE hotspot_id = :hid AND report_id = :rid"
            ),
            {"hid": h.hotspot_id, "rid": report_id_str},
        ).fetchone()
        if exists:
            return True
        i_name = p.get("incident_type_name") or "Unknown"
        composition: Dict[str, int] = {}
        try:
            composition = json.loads(h.composition) if h.composition else {}
        except Exception:
            composition = {}
        composition[i_name] = composition.get(i_name, 0) + 1
        new_count = int(h.incident_count or 0) + 1
        h.incident_count = new_count
        h.composition = json.dumps(composition)
        h.detected_at = datetime.now(timezone.utc)
        if h.crime_group and h.crime_group != group_name:
            h.crime_group = "mixed"
        db.execute(
            text(
                "INSERT INTO hotspot_reports (hotspot_id, report_id, is_core) "
                "VALUES (:hid, :rid, true) "
                "ON CONFLICT (hotspot_id, report_id) DO NOTHING"
            ),
            {"hid": h.hotspot_id, "rid": report_id_str},
        )
        db.flush()
        return True
    return False


def _merge_overlapping_hotspots(db: Session, eps_m: float) -> int:
    """Merge hotspots whose centroids are within eps_m of each other.

    Keeps the larger cluster and absorbs the smaller one's reports.
    Returns the number of hotspots removed by merging.
    """
    all_hotspots = (
        db.query(Hotspot)
        .filter(Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=1))
        .order_by(Hotspot.incident_count.desc())
        .all()
    )
    if len(all_hotspots) < 2:
        return 0

    removed_ids: set = set()
    merged = 0

    for i, primary in enumerate(all_hotspots):
        if primary.hotspot_id in removed_ids:
            continue
        for j in range(i + 1, len(all_hotspots)):
            secondary = all_hotspots[j]
            if secondary.hotspot_id in removed_ids:
                continue
            dist = _haversine_meters(
                float(primary.center_lat), float(primary.center_long),
                float(secondary.center_lat), float(secondary.center_long),
            )
            if dist > eps_m:
                continue

            # Merge: move secondary's reports to primary
            db.execute(
                text(
                    "UPDATE hotspot_reports SET hotspot_id = :pid "
                    "WHERE hotspot_id = :sid AND report_id NOT IN "
                    "(SELECT report_id FROM hotspot_reports WHERE hotspot_id = :pid)"
                ),
                {"pid": primary.hotspot_id, "sid": secondary.hotspot_id},
            )
            db.execute(
                text("DELETE FROM hotspot_reports WHERE hotspot_id = :sid"),
                {"sid": secondary.hotspot_id},
            )

            # Update primary's incident count and composition
            sec_composition = {}
            try:
                sec_composition = json.loads(secondary.composition) if secondary.composition else {}
            except Exception:
                pass
            pri_composition = {}
            try:
                pri_composition = json.loads(primary.composition) if primary.composition else {}
            except Exception:
                pass
            for k, v in sec_composition.items():
                pri_composition[k] = pri_composition.get(k, 0) + v

            new_count = (
                db.execute(
                    text("SELECT COUNT(*) FROM hotspot_reports WHERE hotspot_id = :hid"),
                    {"hid": primary.hotspot_id},
                ).scalar() or 0
            )
            primary.incident_count = new_count
            primary.composition = json.dumps(pri_composition)

            # Delete secondary
            db.delete(secondary)
            removed_ids.add(secondary.hotspot_id)
            merged += 1
            logger.info(
                "[hotspot] merged hotspot #%d into #%d (dist=%.0fm, eps=%.0fm)",
                secondary.hotspot_id, primary.hotspot_id, dist, eps_m,
            )

    if merged:
        db.flush()
    return merged


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
    Enhanced ST-DBSCAN clustering pipeline (v2).

    1. Compute adaptive clustering radius from report density (Improvement 3).
    2. Group eligible reports by broad crime category (violent/property/drug/…).
    3. Run ST-DBSCAN per group — unrelated crime types cannot merge.
    4. For each cluster:
       a. Require ≥ 2 unique reporters (Improvement 1 — corroboration gate).
       b. Compute corroboration score, anomaly score, explainability (Impr. 1, 9, 11).
       c. Compute weighted centroid, severity, temporal intensity, lifecycle,
          trend, convex-hull polygon.
       d. Predict next lifecycle state (Improvement 8).
    5. Persist clusters with full metadata.
    6. Post-processing: detect multi-crime zones (Improvement 2).
    7. Record lifecycle events in hotspot_events (Improvement 12).
    """
    # ── Improvement 3: adaptive radius ──────────────────────────────────────
    # Compute a density-aware radius from the report point cloud.
    # Falls back to radius_meters when too few points for meaningful sampling.
    eps_m = _adaptive_radius_meters(reports, base_radius=max(50.0, float(radius_meters)))
    if abs(eps_m - float(radius_meters)) > 50:
        logger.info(
            "[hotspot] adaptive radius: requested=%.0fm → adaptive=%.0fm "
            "(density-adjusted for %d reports)",
            radius_meters, eps_m, len(reports),
        )
    # Temporal epsilon scaling:
    #   < 168 h  (< 1 week):  eps_t = window/4, clamped 6 h – 72 h
    #   168–720 h (1 wk–1 mo): eps_t = window/4, no 72 h cap — proportional
    #   > 720 h  (> 1 month):  eps_t = 0.0 → purely spatial (pattern detection)
    if int(time_window_hours) > 720:
        eps_t = 0.0          # month+ → full spatial history, no time gate
    elif int(time_window_hours) >= 168:
        # 1 week → 1 month: proportional, no hard 72 h cap
        eps_t = float(time_window_hours) * 3600 / 4
    else:
        raw_eps_t = float(time_window_hours) * 3600 / 4
        eps_t = max(6 * 3600, min(72 * 3600, raw_eps_t))
    dbscan_min_pts = max(4, int(min_incidents))

    logger.info(
        "[hotspot] DBSCAN params — eps_m=%.0fm, eps_t=%.1fh, min_pts=%d, "
        "time_window=%dh, n_reports=%d",
        eps_m, eps_t / 3600 if eps_t else 0.0, dbscan_min_pts,
        time_window_hours, len(reports),
    )
    # Severity override allows a single very high-severity point to be a core.

    # ── 1. Cluster all incident types together ─────────────────────────────
    # Geographic proximity — not crime type — defines a cluster.  A theft and an
    # assault reported at the same corner belong in the same hotspot; separating
    # them by category hid mixed-crime zones and inflated the noise rate.
    # The dominant type is still derived from the cluster members after DBSCAN.
    groups: Dict[str, List[Dict[str, Any]]] = {"mixed": reports}

    created = 0

    # A single isolated report is NOT a hotspot.  Only try to attach it to an
    # already-existing cluster within the clustering radius.  If no such cluster
    # exists the report is silently skipped — it will be re-evaluated the next
    # time clustering runs once more nearby reports arrive.
    def _try_attach_isolated(p: Dict[str, Any]) -> None:
        _try_append_report_to_nearby_hotspot(db, p, eps_m, group_name)

    total_noise = 0
    total_clusters = 0

    for group_name, group_pts in groups.items():
        if len(group_pts) < dbscan_min_pts:
            # Whole group is too small to cluster — try to merge each point into
            # an existing nearby hotspot but do NOT create new single-point hotspots.
            logger.debug(
                "[hotspot] group=%s: only %d report(s) — below min_pts=%d, "
                "trying to attach to existing hotspot",
                group_name, len(group_pts), dbscan_min_pts,
            )
            for p in group_pts:
                _try_attach_isolated(p)
            continue

        # ── 2. ST-DBSCAN ──────────────────────────────────────────────────
        labels, is_core_flags = _st_dbscan(group_pts, eps_m, eps_t, dbscan_min_pts)
        n_noise_pts = sum(1 for l in labels if l < 0)
        n_raw_clusters = len(set(l for l in labels if l >= 0))
        total_noise += n_noise_pts
        total_clusters += n_raw_clusters
        logger.info(
            "[hotspot] group=%s: reports=%d → clusters=%d, noise=%d (%.0f%%)",
            group_name, len(group_pts), n_raw_clusters, n_noise_pts,
            100 * n_noise_pts / max(1, len(group_pts)),
        )

        raw_clusters: Dict[int, List[Dict[str, Any]]] = {}
        for idx, label in enumerate(labels):
            if label < 0:
                continue
            tagged = {**group_pts[idx], "is_core": is_core_flags[idx]}
            raw_clusters.setdefault(label, []).append(tagged)

        for cluster_pts in raw_clusters.values():
            incident_count = len(cluster_pts)
            if incident_count < int(min_incidents):
                # Under-sized DBSCAN cluster — try to attach each point to an
                # existing nearby hotspot; never create a new single-point hotspot.
                for p in cluster_pts:
                    _try_attach_isolated(p)
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

            # ── Improvement 1: corroboration gate ─────────────────────────
            # Require at least 2 unique independent reporters before creating
            # or updating a hotspot.  A single person repeatedly filing the
            # same location does NOT constitute a corroborated hotspot — it is
            # either a technical issue or a potential abuse vector.
            unique_reporters = _count_unique_reporters(cluster_pts)
            MIN_UNIQUE_REPORTERS = 2
            if unique_reporters < MIN_UNIQUE_REPORTERS:
                logger.info(
                    "[hotspot] group=%s cluster skipped — %d unique reporter(s) "
                    "< min_required=%d (corroboration gate)",
                    group_name, unique_reporters, MIN_UNIQUE_REPORTERS,
                )
                for p in cluster_pts:
                    _try_attach_isolated(p)
                continue

            corroboration = _corroboration_score(cluster_pts, MIN_UNIQUE_REPORTERS)

            # ── Improvement 11: anomaly detection ─────────────────────────
            anomaly = _compute_anomaly_score(cluster_pts)
            is_abuse_flagged = anomaly >= _ANOMALY_FLAG_THRESHOLD
            if is_abuse_flagged:
                logger.warning(
                    "[hotspot] group=%s cluster ABUSE FLAG — anomaly_score=%.2f "
                    "(reporters=%d, size=%d); hotspot will be created but flagged",
                    group_name, anomaly, unique_reporters, incident_count,
                )

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

            # ── Improvement 8: prediction ─────────────────────────────────
            predicted_state = _predict_next_state(lifecycle, trend)

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

            # Convex hull polygon (safe — fallback to None on any geometry error)
            hull_pts_latlon = [(p["lat"], p["lon"]) for p in cluster_pts]
            try:
                hull = _convex_hull_points(hull_pts_latlon)
                polygon_json = json.dumps(hull) if hull else None
            except Exception as _hull_err:
                logger.warning(
                    "[hotspot] convex hull failed for cluster of %d points: %s",
                    len(cluster_pts), _hull_err,
                )
                polygon_json = None

            # Risk classification
            area_sqkm = max(0.001, 3.14159 * (float(radius_meters) / 1000.0) ** 2)
            cluster_density = incident_count / area_sqkm
            classification_result = predict_cluster_classification(
                incident_count=incident_count,
                avg_trust=avg_trust,
                cluster_density=cluster_density,
                time_window_hours=time_window_hours,
            )
            # Override risk level with incident-count-based criteria:
            #   HIGH: >4 new incidents in last 7 days, OR 12+ in last 7 days, OR 15+ total
            #   MEDIUM: everything else (cluster already has ≥4 incidents from min_pts)
            _week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            _recent_count = 0
            for p in cluster_pts:
                _rat = p.get("reported_at")
                if _rat is None:
                    continue
                if _rat.tzinfo is None:
                    _rat = _rat.replace(tzinfo=timezone.utc)
                if _rat >= _week_ago:
                    _recent_count += 1
            if incident_count >= 15 or _recent_count >= 12 or _recent_count > 4:
                risk_level = "critical" if _recent_count >= 12 or incident_count >= 15 else "high"
                classification_result["classification"] = "critical" if risk_level == "critical" else "active"
            else:
                risk_level = "medium"
                classification_result["classification"] = "emerging"

            # ── 4. Persist ────────────────────────────────────────────────
            _dedup_deg = max(0.001, eps_m / 111000.0)
            existing = (
                db.query(Hotspot)
                .filter(
                    Hotspot.center_lat.between(center_lat - _dedup_deg, center_lat + _dedup_deg),
                    Hotspot.center_long.between(center_long - _dedup_deg, center_long + _dedup_deg),
                    Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24),
                )
                .order_by(Hotspot.detected_at.desc())
                .first()
            )

            # ── Improvement 9: explainability ─────────────────────────────
            explanation = _build_explanation(
                incident_count=incident_count,
                avg_trust=avg_trust,
                sev_score=sev_score,
                trend=trend,
                lifecycle=lifecycle,
                classification=classification_result["classification"],
                conf=conf,
                t_intensity=t_intensity,
                composition=composition,
                unique_reporters=unique_reporters,
                corroboration_score=corroboration,
                anomaly_score=anomaly,
            )

            now_utc = datetime.now(timezone.utc)

            if existing:
                prev_lifecycle = existing.lifecycle_state
                hotspot = existing
                hotspot.center_lat             = Decimal(str(center_lat))
                hotspot.center_long            = Decimal(str(center_long))
                hotspot.radius_meters          = Decimal(str(eps_m))
                hotspot.incident_count         = incident_count
                hotspot.risk_level             = risk_level
                hotspot.time_window_hours      = time_window_hours
                hotspot.incident_type_id       = dominant_type_id
                hotspot.detected_at            = now_utc
                hotspot.lifecycle_state        = lifecycle
                hotspot.composition            = json.dumps(composition)
                hotspot.temporal_intensity     = Decimal(str(round(t_intensity, 4)))
                hotspot.severity_score         = Decimal(str(round(sev_score, 4)))
                hotspot.trend_direction        = trend
                hotspot.cluster_confidence     = Decimal(str(conf))
                hotspot.polygon_points         = polygon_json
                hotspot.crime_group            = _get_crime_group(dominant_type_name)
                # Improvements 1 & 11
                hotspot.unique_reporter_count  = unique_reporters
                hotspot.corroboration_score    = Decimal(str(corroboration))
                hotspot.anomaly_score          = Decimal(str(anomaly))
                hotspot.abuse_flag             = is_abuse_flagged
                # Improvement 8: verify previous prediction
                if (
                    hotspot.predicted_next_state
                    and hotspot.prediction_verified_at is None
                    and hotspot.predicted_at is not None
                ):
                    was_accurate = (hotspot.predicted_next_state == lifecycle)
                    hotspot.prediction_was_accurate = was_accurate
                    hotspot.prediction_verified_at = now_utc
                    _record_hotspot_event(
                        db, hotspot.hotspot_id, "prediction_verified",
                        previous_state=prev_lifecycle,
                        new_state=lifecycle,
                        event_data={
                            "predicted": hotspot.predicted_next_state,
                            "actual": lifecycle,
                            "accurate": was_accurate,
                        },
                    )
                hotspot.predicted_next_state   = predicted_state
                hotspot.predicted_at           = now_utc
                hotspot.prediction_verified_at = None
                hotspot.prediction_was_accurate = None
                # Improvement 9
                hotspot.explanation_json       = json.dumps(explanation)
                # Improvement 10: cache invalidation
                hotspot.cache_version          = (hotspot.cache_version or 0) + 1
                # Clear cached advisory so the API regenerates it with fresh incident data.
                hotspot.llm_citizen_advisory   = None
                hotspot.llm_generated_at       = None
                db.execute(
                    text("DELETE FROM hotspot_reports WHERE hotspot_id = :hid"),
                    {"hid": hotspot.hotspot_id},
                )
                # Improvement 12: audit event for lifecycle change
                if prev_lifecycle != lifecycle:
                    event_name = (
                        "escalated" if lifecycle == "escalating"
                        else "stabilized" if lifecycle == "stable"
                        else "declining" if lifecycle == "declining"
                        else "updated"
                    )
                    _record_hotspot_event(
                        db, hotspot.hotspot_id, event_name,
                        previous_state=prev_lifecycle,
                        new_state=lifecycle,
                        event_data={
                            "incident_count": incident_count,
                            "trend": trend,
                            "anomaly_score": anomaly,
                        },
                    )
                else:
                    _record_hotspot_event(
                        db, hotspot.hotspot_id, "updated",
                        previous_state=prev_lifecycle,
                        new_state=lifecycle,
                        event_data={"incident_count": incident_count, "trend": trend},
                    )
                logger.debug(
                    "[hotspot] updated existing hotspot_id=%d — group=%s, "
                    "incidents=%d, risk=%s, lifecycle=%s→%s, trend=%s, "
                    "corr=%.2f, anomaly=%.2f, center=(%.5f, %.5f)",
                    hotspot.hotspot_id, group_name, incident_count, risk_level,
                    prev_lifecycle, lifecycle, trend, corroboration, anomaly,
                    center_lat, center_long,
                )
            else:
                hotspot = Hotspot(
                    center_lat             = Decimal(str(center_lat)),
                    center_long            = Decimal(str(center_long)),
                    radius_meters          = Decimal(str(eps_m)),
                    incident_count         = incident_count,
                    risk_level             = risk_level,
                    time_window_hours      = time_window_hours,
                    incident_type_id       = dominant_type_id,
                    detected_at            = now_utc,
                    lifecycle_state        = lifecycle,
                    composition            = json.dumps(composition),
                    temporal_intensity     = Decimal(str(round(t_intensity, 4))),
                    severity_score         = Decimal(str(round(sev_score, 4))),
                    trend_direction        = trend,
                    cluster_confidence     = Decimal(str(conf)),
                    polygon_points         = polygon_json,
                    crime_group            = _get_crime_group(dominant_type_name),
                    # Improvements 1 & 11
                    unique_reporter_count  = unique_reporters,
                    corroboration_score    = Decimal(str(corroboration)),
                    anomaly_score          = Decimal(str(anomaly)),
                    abuse_flag             = is_abuse_flagged,
                    # Improvement 8
                    predicted_next_state   = predicted_state,
                    predicted_at           = now_utc,
                    # Improvement 9
                    explanation_json       = json.dumps(explanation),
                    # Improvement 10
                    cache_version          = 1,
                )
                db.add(hotspot)
                db.flush()
                created += 1
                # Improvement 12: creation event
                _record_hotspot_event(
                    db, hotspot.hotspot_id, "created",
                    new_state=lifecycle,
                    event_data={
                        "incident_count": incident_count,
                        "group": group_name,
                        "corroboration_score": corroboration,
                        "anomaly_score": anomaly,
                        "unique_reporters": unique_reporters,
                        "predicted_next_state": predicted_state,
                    },
                )
                logger.info(
                    "[hotspot] NEW hotspot_id=%d — group=%s, incidents=%d, "
                    "risk=%s, lifecycle=%s, trend=%s, conf=%.2f, "
                    "corr=%.2f, reporters=%d, anomaly=%.2f, "
                    "center=(%.5f, %.5f), dominant_crime=%s",
                    hotspot.hotspot_id, group_name, incident_count, risk_level,
                    lifecycle, trend, conf, corroboration, unique_reporters, anomaly,
                    center_lat, center_long, dominant_type_name,
                )

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

        # ── Noise points: spatial-only re-cluster, then attach leftovers ──────
        noise_indices = [i for i, lbl in enumerate(labels) if lbl < 0]
        noise_pts = [group_pts[i] for i in noise_indices]
        leftover_noise: List[Dict[str, Any]] = []
        if len(noise_pts) >= 2:
            logger.debug(
                "[hotspot] group=%s: re-clustering %d noise points (spatial-only)",
                group_name, len(noise_pts),
            )
            n_labels, n_core = _st_dbscan(noise_pts, eps_m, 0.0, max(2, dbscan_min_pts))
            n_clusters: Dict[int, List[Dict[str, Any]]] = {}
            for ni, nlbl in enumerate(n_labels):
                if nlbl < 0:
                    leftover_noise.append(noise_pts[ni])
                    continue
                tagged = {**noise_pts[ni], "is_core": n_core[ni]}
                n_clusters.setdefault(nlbl, []).append(tagged)

            noise_clusters_created = 0
            noise_clusters_attached = 0
            for cluster_pts in n_clusters.values():
                if len(cluster_pts) < 2:
                    leftover_noise.extend(cluster_pts)
                    continue
                incident_count = len(cluster_pts)
                center_lat, center_long = _weighted_centroid(
                    cluster_pts, time_window_hours=time_window_hours
                )

                # ── Deduplication: check for an existing nearby hotspot ────────
                # Without this, noise reclustering creates duplicate overlapping
                # hotspots for the same geographic area.
                _deg_tol = max(0.001, eps_m / 111000.0)
                noise_existing = (
                    db.query(Hotspot)
                    .filter(
                        Hotspot.center_lat.between(center_lat - _deg_tol, center_lat + _deg_tol),
                        Hotspot.center_long.between(center_long - _deg_tol, center_long + _deg_tol),
                        Hotspot.detected_at >= datetime.now(timezone.utc) - timedelta(hours=24),
                    )
                    .order_by(Hotspot.detected_at.desc())
                    .first()
                )
                if noise_existing:
                    # Attach all points to the existing cluster instead of creating a duplicate
                    for pt in cluster_pts:
                        _try_append_report_to_nearby_hotspot(db, pt, eps_m, group_name)
                    noise_clusters_attached += 1
                    continue

                avg_trust = sum(p.get("trust", 100.0) for p in cluster_pts) / incident_count
                area_sqkm = max(0.001, 3.14159 * (float(radius_meters) / 1000.0) ** 2)
                classification_result = predict_cluster_classification(
                    incident_count=incident_count,
                    avg_trust=avg_trust,
                    cluster_density=incident_count / area_sqkm,
                    time_window_hours=time_window_hours,
                )
                risk_level = classification_to_risk_level(
                    classification_result["classification"]
                )
                noise_composition: Dict[str, int] = {}
                for pt in cluster_pts:
                    t_name = pt.get("incident_type_name") or "Unknown"
                    noise_composition[t_name] = noise_composition.get(t_name, 0) + 1
                noise_type_id_counts: Dict[int, int] = {}
                for pt in cluster_pts:
                    tid = int(pt.get("incident_type_id") or 0)
                    if tid:
                        noise_type_id_counts[tid] = noise_type_id_counts.get(tid, 0) + 1
                noise_dominant_type_id = (
                    max(noise_type_id_counts, key=noise_type_id_counts.get)
                    if noise_type_id_counts else None
                )
                hull_pts_latlon = [(pt["lat"], pt["lon"]) for pt in cluster_pts]
                try:
                    hull = _convex_hull_points(hull_pts_latlon)
                    polygon_json = json.dumps(hull) if hull else None
                except Exception:
                    polygon_json = None
                t_intensity_n = _temporal_intensity(cluster_pts)
                sev_score_n = sum(
                    _get_severity(pt.get("incident_type_name", "")) * float(pt.get("trust", 100.0)) / 100.0
                    for pt in cluster_pts
                ) / incident_count
                conf_n = _cluster_confidence(cluster_pts)
                hotspot = Hotspot(
                    center_lat=Decimal(str(center_lat)),
                    center_long=Decimal(str(center_long)),
                    radius_meters=Decimal(str(radius_meters)),
                    incident_count=incident_count,
                    risk_level=risk_level,
                    time_window_hours=time_window_hours,
                    incident_type_id=noise_dominant_type_id,
                    detected_at=datetime.now(timezone.utc),
                    lifecycle_state=classification_result["classification"],
                    composition=json.dumps(noise_composition),
                    temporal_intensity=Decimal(str(round(t_intensity_n, 4))),
                    severity_score=Decimal(str(round(sev_score_n, 4))),
                    trend_direction=_trend_direction(cluster_pts),
                    cluster_confidence=Decimal(str(conf_n)),
                    polygon_points=polygon_json,
                    crime_group=_get_crime_group(max(noise_composition, key=noise_composition.get) if noise_composition else ""),
                )
                db.add(hotspot)
                db.flush()
                created += 1
                noise_clusters_created += 1
                for pt in cluster_pts:
                    db.execute(
                        text(
                            "INSERT INTO hotspot_reports (hotspot_id, report_id, is_core) "
                            "VALUES (:hid, :rid, true) "
                            "ON CONFLICT (hotspot_id, report_id) DO UPDATE SET is_core = true"
                        ),
                        {
                            "hid": hotspot.hotspot_id,
                            "rid": str(pt["report"].report_id),
                        },
                    )
                logger.info(
                    "[hotspot] noise cluster → NEW hotspot_id=%d — group=%s, "
                    "incidents=%d, risk=%s, center=(%.5f, %.5f)",
                    hotspot.hotspot_id, group_name, incident_count, risk_level,
                    center_lat, center_long,
                )

            logger.debug(
                "[hotspot] group=%s noise re-cluster: created=%d, attached=%d, leftover=%d",
                group_name, noise_clusters_created, noise_clusters_attached, len(leftover_noise),
            )
        else:
            leftover_noise = noise_pts

        # Leftover noise: try to attach each point to an existing nearby hotspot.
        # Never create a new single-point hotspot — skip if no cluster is available.
        attached = sum(
            1 for p in leftover_noise
            if _try_append_report_to_nearby_hotspot(db, p, eps_m, group_name)
        )
        discarded = len(leftover_noise) - attached
        if leftover_noise:
            # Log every discarded report_id so operators can trace which reports
            # are awaiting a future clustering partner. These reports remain in
            # the `reports` table and will be re-evaluated on the next run when
            # additional nearby reports may have arrived.
            discarded_ids = [
                str(p["report"].report_id)
                for i, p in enumerate(leftover_noise)
                if i >= attached  # rough ordering — use debug only
            ]
            logger.debug(
                "[hotspot] group=%s leftover noise=%d: attached=%d, "
                "retained_for_future_run=%d (report_ids_sample=%s)",
                group_name, len(leftover_noise), attached, discarded,
                discarded_ids[:5],   # log up to 5 for brevity
            )

    # ── Post-processing: merge overlapping clusters ──────────────────────────
    # Clusters whose centroids are within eps_m of each other should be merged
    # into one to prevent visual overlap on the map.
    merged = 0
    try:
        merged = _merge_overlapping_hotspots(db, eps_m)
    except Exception as _merge_err:
        logger.warning("[hotspot] overlapping merge failed: %s", _merge_err)

    # ── Improvement 2: multi-crime zone post-processing ─────────────────────
    # After all crime groups are processed, mark hotspots whose geographic
    # footprint overlaps with hotspots of a different crime group.
    try:
        flagged_multi = detect_multi_crime_zones(db, eps_m)
    except Exception as _mce:
        logger.warning("[hotspot] multi-crime zone detection failed: %s", _mce)
        flagged_multi = 0

    logger.info(
        "[hotspot] _create_geographic_hotspots done — created=%d, merged=%d, "
        "total_raw_clusters=%d, total_noise_pts=%d, multi_crime_zones=%d",
        created, merged, total_clusters, total_noise, flagged_multi,
    )
    return created - merged
