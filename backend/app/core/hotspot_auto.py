"""
Automatic hotspot creation: when many reports of the same place AND the same
incident type are submitted, a hotspot is created. No manual creation.
Links each hotspot to its contributing reports via hotspot_reports table.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Tuple, Any

from sqlalchemy import insert
from sqlalchemy.orm import Session, selectinload

from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.report import Report
from app.models.ml_prediction import MLPrediction


# Same place + same type: 2+ reports in last 24h in one area (village or lat/long bucket), same incident_type_id
DEFAULT_TIME_WINDOW_HOURS = 24
DEFAULT_MIN_INCIDENTS = 2
DEFAULT_RADIUS_METERS = 500
LAT_LONG_PRECISION = 3  # ~111m, used when we have no village


def _weight_for_report(report: Report) -> Tuple[float, bool]:
    """
    Compute a numeric weight and whether this report has a confirmed police review.

    Base rule-based weight:
    - rule_status passed     -> 1.0
    - rule_status pending    -> 0.6
    - rule_status flagged    -> 0.3
    - rule_status rejected   -> 0.0
    - bonus for confirmed review: +0.7

    If an ML prediction exists, its trust_score (0–100) is converted to a
    trust_weight in [0, 1] and blended with the rule-based score to give
    more influence to high-credibility reports.
    """
    status = (report.rule_status or "").lower()
    if status == "passed":
        base = 1.0
    elif status == "pending":
        base = 0.6
    elif status == "flagged":
        base = 0.3
    elif status == "rejected":
        base = 0.0
    else:
        base = 0.5

    has_confirmed = any((rv.decision or "").lower() == "confirmed" for rv in (report.police_reviews or []))
    if has_confirmed:
        base += 0.7

    # Blend in ML trust_score if available
    ml_preds = getattr(report, "ml_predictions", None) or []
    if ml_preds:
        # Prefer final predictions, then latest by evaluated_at
        final_preds = [p for p in ml_preds if p.is_final]
        if final_preds:
            ml_source = final_preds
        else:
            ml_source = ml_preds
        ml_source.sort(
            key=lambda p: (p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )
        latest: MLPrediction = ml_source[0]
        trust_score = latest.trust_score
        try:
            trust_score_f = float(trust_score) if trust_score is not None else None
        except Exception:
            trust_score_f = None
        if trust_score_f is not None:
            trust_weight = max(0.0, min(1.0, trust_score_f / 100.0))
            # Blend: 60% ML trust, 40% rule-based
            base = trust_weight * 1.5 + base * 0.4

    return base, has_confirmed


def _risk_level_from_score(score: float, confirmed_reports: int) -> str:
    """
    Derive hotspot risk:
    - high:   strong score OR multiple confirmed reports
    - medium: some confirmations OR moderate score
    - low:    weak, mostly provisional
    """
    if confirmed_reports >= 2 or score >= 6.0:
        return "high"
    if confirmed_reports >= 1 or score >= 3.0:
        return "medium"
    return "low"


def create_hotspots_from_reports(
    db: Session,
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    min_incidents: int = DEFAULT_MIN_INCIDENTS,
    radius_meters: float = DEFAULT_RADIUS_METERS,
) -> int:
    """
    Group reports by:
    - village_location_id + incident_type_id when village is known, OR
    - lat/long bucket + incident_type_id when village is unknown.

    For each group with at least min_incidents, compute a weighted score
    using rule_status and police reviews, then create a hotspot if none exists.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

    reports = (
        db.query(Report)
        .options(
            selectinload(Report.police_reviews),
            selectinload(Report.ml_predictions),
        )
        .filter(Report.reported_at >= since)
        .all()
    )

    clusters: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

    for r in reports:
        try:
            lat = float(r.latitude)
            lon = float(r.longitude)
        except (TypeError, ValueError):
            continue

        if r.village_location_id is not None:
            key = ("village", int(r.village_location_id), int(r.incident_type_id))
        else:
            lat_bucket = round(lat, LAT_LONG_PRECISION)
            lon_bucket = round(lon, LAT_LONG_PRECISION)
            key = ("bucket", lat_bucket, lon_bucket, int(r.incident_type_id))

        cluster = clusters.setdefault(
            key,
            {
                "reports": [],
                "score": 0.0,
                "confirmed_reports": 0,
                "lats": [],
                "lons": [],
            },
        )
        w, has_confirmed = _weight_for_report(r)
        cluster["reports"].append(r)
        cluster["score"] += w
        if has_confirmed:
            cluster["confirmed_reports"] += 1
        cluster["lats"].append(lat)
        cluster["lons"].append(lon)

    created = 0
    for key, info in clusters.items():
        reports_in_cluster = info["reports"]
        incident_count = len(reports_in_cluster)
        if incident_count < min_incidents:
            continue

        score = float(info["score"])
        confirmed_reports = int(info["confirmed_reports"])

        avg_lat = sum(info["lats"]) / incident_count
        avg_lon = sum(info["lons"]) / incident_count
        center_lat = Decimal(str(round(avg_lat, LAT_LONG_PRECISION)))
        center_long = Decimal(str(round(avg_lon, LAT_LONG_PRECISION)))

        if key[0] == "village":
            incident_type_id = key[2]
        else:
            incident_type_id = key[3]

        existing = (
            db.query(Hotspot)
            .filter(
                Hotspot.center_lat == center_lat,
                Hotspot.center_long == center_long,
                Hotspot.incident_type_id == incident_type_id,
                Hotspot.time_window_hours == time_window_hours,
            )
            .first()
        )
        if existing:
            continue

        hotspot = Hotspot(
            center_lat=center_lat,
            center_long=center_long,
            radius_meters=Decimal(str(radius_meters)),
            incident_count=incident_count,
            risk_level=_risk_level_from_score(score, confirmed_reports),
            time_window_hours=time_window_hours,
            incident_type_id=incident_type_id,
        )
        db.add(hotspot)
        db.flush()  # get hotspot_id

        db.execute(
            insert(hotspot_reports_table),
            [{"hotspot_id": hotspot.hotspot_id, "report_id": r.report_id} for r in reports_in_cluster],
        )
        created += 1

    if created > 0:
        db.commit()
    return created
