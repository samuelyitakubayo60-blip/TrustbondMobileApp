"""
Automatic hotspot creation: when many reports of the same place AND the same
incident type are submitted, a hotspot is created. No manual creation.
Links each hotspot to its contributing reports via hotspot_reports table.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.report import Report


# Same place + same type: 2+ reports in last 24h in one area bucket, same incident_type_id
DEFAULT_TIME_WINDOW_HOURS = 24
DEFAULT_MIN_INCIDENTS = 2
DEFAULT_RADIUS_METERS = 500
LAT_LONG_PRECISION = 3  # ~111m


def _risk_level_from_count(count: int) -> str:
    if count >= 10:
        return "high"
    if count >= 5:
        return "medium"
    return "low"


def create_hotspots_from_reports(
    db: Session,
    time_window_hours: int = DEFAULT_TIME_WINDOW_HOURS,
    min_incidents: int = DEFAULT_MIN_INCIDENTS,
    radius_meters: float = DEFAULT_RADIUS_METERS,
) -> int:
    """
    Group reports by same place (lat/long bucket) AND same incident_type_id.
    For each (place, type) with count >= 2, create a hotspot if not already present.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

    q = text("""
        SELECT
            ROUND(latitude::numeric, :precision) AS lat_bucket,
            ROUND(longitude::numeric, :precision) AS long_bucket,
            incident_type_id,
            COUNT(*) AS cnt,
            AVG(latitude) AS center_lat,
            AVG(longitude) AS center_long
        FROM reports
        WHERE reported_at >= :since
        GROUP BY ROUND(latitude::numeric, :precision), ROUND(longitude::numeric, :precision), incident_type_id
        HAVING COUNT(*) >= :min_incidents
    """)
    rows = db.execute(
        q,
        {
            "precision": LAT_LONG_PRECISION,
            "since": since,
            "min_incidents": min_incidents,
        },
    ).fetchall()

    created = 0
    for row in rows:
        center_lat = Decimal(str(round(float(row.center_lat), LAT_LONG_PRECISION)))
        center_long = Decimal(str(round(float(row.center_long), LAT_LONG_PRECISION)))
        incident_type_id = int(row.incident_type_id)
        incident_count = int(row.cnt)

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
            risk_level=_risk_level_from_count(incident_count),
            time_window_hours=time_window_hours,
            incident_type_id=incident_type_id,
        )
        db.add(hotspot)
        db.flush()  # get hotspot_id

        # Link this hotspot to its contributing report IDs (for drill-down)
        q_reports = text("""
            SELECT report_id
            FROM reports
            WHERE reported_at >= :since
              AND ROUND(latitude::numeric, :precision) = :lat_bucket
              AND ROUND(longitude::numeric, :precision) = :long_bucket
              AND incident_type_id = :incident_type_id
        """)
        report_rows = db.execute(
            q_reports,
            {
                "since": since,
                "precision": LAT_LONG_PRECISION,
                "lat_bucket": center_lat,
                "long_bucket": center_long,
                "incident_type_id": incident_type_id,
            },
        ).fetchall()
        if report_rows:
            db.execute(
                insert(hotspot_reports_table),
                [{"hotspot_id": hotspot.hotspot_id, "report_id": row[0]} for row in report_rows],
            )
        created += 1

    if created > 0:
        db.commit()
    return created
