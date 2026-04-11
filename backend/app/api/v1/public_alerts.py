from datetime import datetime, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.cluster_classifier import predict_cluster_classification
from app.database import get_db
from app.models.hotspot import Hotspot
from app.models.report import Report


router = APIRouter(prefix="/public/alerts", tags=["public"])


def _severity_from_risk(risk_level: str) -> str:
    risk = (risk_level or "").strip().lower()
    if risk == "high":
        return "high"
    if risk == "medium":
        return "medium"
    if risk == "low":
        return "low"
    return "info"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _latest_ml_trust(report: Report) -> Optional[float]:
    preds = list(getattr(report, "ml_predictions", None) or [])
    if not preds:
        return None
    finals = [p for p in preds if getattr(p, "is_final", False)]
    src = finals if finals else preds
    src.sort(
        key=lambda p: p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    top = src[0]
    try:
        if top.trust_score is None:
            return None
        return float(top.trust_score)
    except Exception:
        return None


def _avg_cluster_trust(reports: List[Report]) -> float:
    if not reports:
        return 50.0
    vals: List[float] = []
    for r in reports:
        t = _latest_ml_trust(r)
        vals.append(t if t is not None else 50.0)
    return sum(vals) / len(vals)


def _prediction_narrative(classification: str, incident_name: str, distance_km: float) -> str:
    crime = incident_name.lower()
    if classification == "critical":
        return (
            f"AI analysis indicates a critical {crime} cluster about {distance_km:.1f} km from you. "
            "Avoid isolated routes and stay in well-lit areas."
        )
    if classification == "active":
        return (
            f"AI analysis shows an active {crime} cluster about {distance_km:.1f} km from your location. "
            "Use caution and monitor local updates."
        )
    if classification == "emerging":
        return (
            f"AI detected an emerging {crime} pattern about {distance_km:.1f} km away. "
            "Remain alert and report suspicious activity quickly."
        )
    return (
        f"AI detected low activity related to {crime} about {distance_km:.1f} km from you. "
        "No immediate action needed, but stay aware."
    )


@router.get("/", response_model=List[Dict[str, Any]])
def list_public_alerts(
    latitude: float = Query(..., description="User latitude for proximity filtering."),
    longitude: float = Query(..., description="User longitude for proximity filtering."),
    radius_km: float = Query(10.0, ge=0.5, le=50.0, description="Max alert distance from user."),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """AI-derived public alerts within radius of user location (default 10km)."""
    hotspots = (
        db.query(Hotspot)
        .options(
            joinedload(Hotspot.incident_type),
            selectinload(Hotspot.reports).selectinload(Report.ml_predictions),
        )
        .order_by(Hotspot.detected_at.desc())
        .all()
    )

    alerts: List[Dict[str, Any]] = []
    for h in hotspots:
        try:
            h_lat = float(h.center_lat)
            h_lon = float(h.center_long)
        except Exception:
            continue

        distance_km = _haversine_km(latitude, longitude, h_lat, h_lon)
        if distance_km > float(radius_km):
            continue

        incident_count = int(h.incident_count or 0)
        time_window_hours = int(h.time_window_hours or 24)
        radius_meters = float(h.radius_meters or 500.0)
        area_sqkm = max(0.001, 3.14159 * (radius_meters / 1000.0) ** 2)
        cluster_density = incident_count / area_sqkm
        avg_trust = _avg_cluster_trust(list(getattr(h, "reports", None) or []))
        ai = predict_cluster_classification(
            incident_count=incident_count,
            avg_trust=avg_trust,
            cluster_density=cluster_density,
            time_window_hours=time_window_hours,
        )

        incident_name = h.incident_type.type_name if h.incident_type else "Incident"
        risk = (h.risk_level or "unknown").lower()
        alerts.append(
            {
                "alert_id": f"hotspot-{h.hotspot_id}",
                "title": f"{incident_name} safety alert",
                "message": _prediction_narrative(
                    str(ai.get("classification") or "low_activity"),
                    incident_name,
                    distance_km,
                ),
                "severity": _severity_from_risk(risk),
                "risk_level": risk,
                "location_name": "Nearby Musanze area",
                "area": "Musanze",
                "created_at": h.detected_at.isoformat() if h.detected_at else None,
                "hotspot_id": h.hotspot_id,
                "incident_type_name": incident_name,
                "incident_count": h.incident_count,
                "radius_meters": radius_meters,
                "distance_km": round(distance_km, 2),
                "classification": ai.get("classification"),
                "classification_confidence": ai.get("confidence"),
                "classification_source": ai.get("source"),
                "hotspot_score": ai.get("hotspot_score"),
            }
        )

        if len(alerts) >= limit:
            break

    return alerts
