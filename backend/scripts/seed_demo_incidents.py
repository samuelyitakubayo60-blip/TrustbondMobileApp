"""
Seed demo incidents for hotspot/cluster visualization.

Usage:
  cd backend
  python scripts/seed_demo_incidents.py --reports 60 --recompute --clear-hotspots
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from math import cos, radians
from pathlib import Path
from uuid import uuid4

# Ensure backend root is importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.database import SessionLocal
from app.models.device import Device
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.incident_type import IncidentType
from app.models.report import Report
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from scripts.seed_incident_types import seed_incident_types


CLUSTER_BLUEPRINTS = [
    {
        "name": "Muhoza Market",
        "center": (-1.4988, 29.6352),
        "count": 12,
        "dominant": "Theft",
    },
    {
        "name": "Kinigi Bus Terminal",
        "center": (-1.4658, 29.5820),
        "count": 10,
        "dominant": "Vandalism",
    },
    {
        "name": "Cyuve Night Zone",
        "center": (-1.5326, 29.6122),
        "count": 9,
        "dominant": "Suspicious Activity",
    },
    {
        "name": "Nyange Gorilla Road",
        "center": (-1.4829, 29.5623),
        "count": 8,
        "dominant": "Traffic Incident",
    },
    {
        "name": "Ruhengeri Bus Park",
        "center": (-1.5043, 29.6267),
        "count": 8,
        "dominant": "Assault",
    },
    {
        "name": "Shingiro Border Road",
        "center": (-1.4459, 29.6578),
        "count": 7,
        "dominant": "Drug Activity",
    },
]

NOISE_POINTS = [
    (-1.5150, 29.6500),
    (-1.4780, 29.6800),
    (-1.5400, 29.5900),
    (-1.4550, 29.6200),
    (-1.5200, 29.5700),
    (-1.4900, 29.7000),
]


def _jitter_point(lat: float, lon: float, radius_m: float) -> tuple[float, float]:
    # Convert meter jitter to lat/lon jitter.
    d_lat = (random.uniform(-radius_m, radius_m)) / 111111.0
    lon_scale = 111111.0 * max(0.2, cos(radians(lat)))
    d_lon = (random.uniform(-radius_m, radius_m)) / lon_scale
    return lat + d_lat, lon + d_lon


def _ensure_incident_types(db) -> dict[str, int]:
    rows = db.query(IncidentType).filter(IncidentType.is_active.is_(True)).all()
    if not rows:
        seed_incident_types()
        rows = db.query(IncidentType).filter(IncidentType.is_active.is_(True)).all()
    return {r.type_name.lower(): int(r.incident_type_id) for r in rows}


def _ensure_devices(db, count: int = 20) -> list[Device]:
    devices = (
        db.query(Device)
        .filter(Device.device_hash.like("seed-demo-device-%"))
        .order_by(Device.first_seen_at.asc())
        .all()
    )
    if len(devices) >= count:
        return devices[:count]

    to_create = count - len(devices)
    for i in range(to_create):
        idx = len(devices) + i + 1
        d = Device(
            device_id=uuid4(),
            device_hash=f"seed-demo-device-{idx:02d}",
            total_reports=0,
            trusted_reports=0,
            flagged_reports=0,
            spam_flags=0,
            is_blacklisted=False,
            is_banned=False,
        )
        db.add(d)
        devices.append(d)

    db.commit()
    return devices


def seed_incidents(total_reports: int) -> tuple[int, int]:
    db = SessionLocal()
    try:
        random.seed(42)
        type_map = _ensure_incident_types(db)
        devices = _ensure_devices(db, count=20)

        default_type_id = next(iter(type_map.values()))
        now = datetime.now(timezone.utc)

        incident_rows: list[Report] = []
        created = 0

        for bp in CLUSTER_BLUEPRINTS:
            dominant_id = type_map.get(bp["dominant"].lower(), default_type_id)
            for _ in range(bp["count"]):
                if created >= total_reports:
                    break
                lat, lon = _jitter_point(bp["center"][0], bp["center"][1], 250)

                # 70% dominant type, 30% random active type.
                if random.random() <= 0.7:
                    incident_type_id = dominant_id
                else:
                    incident_type_id = random.choice(list(type_map.values()))

                reported_at = now - timedelta(hours=random.uniform(0.5, 20.0))
                device = random.choice(devices)

                incident_rows.append(
                    Report(
                        report_id=uuid4(),
                        device_id=device.device_id,
                        incident_type_id=incident_type_id,
                        description=(
                            f"[SEED-DEMO] Incident near {bp['name']} for hotspot visualization"
                        ),
                        latitude=lat,
                        longitude=lon,
                        reported_at=reported_at,
                        status="verified",
                        rule_status="passed",
                        verification_status="verified",
                        priority="high" if bp["count"] >= 10 else "medium",
                        app_version="seed-script-1.0",
                        network_type=random.choice(["4g", "wifi", "3g"]),
                    )
                )
                device.total_reports = int(device.total_reports or 0) + 1
                device.trusted_reports = int(device.trusted_reports or 0) + 1
                created += 1

        # Add noise/isolated incidents across other locations.
        noise_created = 0
        while created < total_reports:
            lat0, lon0 = random.choice(NOISE_POINTS)
            lat, lon = _jitter_point(lat0, lon0, 120)
            incident_type_id = random.choice(list(type_map.values()))
            reported_at = now - timedelta(hours=random.uniform(1.0, 22.0))
            device = random.choice(devices)

            incident_rows.append(
                Report(
                    report_id=uuid4(),
                    device_id=device.device_id,
                    incident_type_id=incident_type_id,
                    description="[SEED-DEMO] Isolated incident (noise candidate)",
                    latitude=lat,
                    longitude=lon,
                    reported_at=reported_at,
                    status="verified",
                    rule_status="passed",
                    verification_status="verified",
                    priority="low",
                    app_version="seed-script-1.0",
                    network_type=random.choice(["4g", "wifi", "3g"]),
                )
            )
            device.total_reports = int(device.total_reports or 0) + 1
            device.trusted_reports = int(device.trusted_reports or 0) + 1
            created += 1
            noise_created += 1

        db.add_all(incident_rows)
        db.commit()
        return created, noise_created
    finally:
        db.close()


def recompute_hotspots(clear_hotspots: bool) -> int:
    db = SessionLocal()
    try:
        if clear_hotspots:
            db.execute(hotspot_reports_table.delete())
            db.query(Hotspot).delete()
            db.commit()

        tw, mi, rm = get_hotspot_params_from_db(db)
        trust_min = get_hotspot_trust_min_from_db(db)
        created = create_hotspots_from_reports(
            db,
            time_window_hours=tw,
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
        )
        return created
    finally:
        db.close()


def purge_seeded_data(recompute_after: bool) -> tuple[int, int, int]:
    """Delete seeded demo data only and optionally rebuild hotspots.

    Returns:
        (deleted_reports, deleted_devices, recomputed_hotspots)
    """
    db = SessionLocal()
    try:
        # Identify seeded reports by explicit markers written by this script.
        seeded_reports = (
            db.query(Report.report_id)
            .filter(
                (Report.app_version == "seed-script-1.0")
                | (Report.description.like("[SEED-DEMO]%"))
            )
            .all()
        )
        seeded_report_ids = [r[0] for r in seeded_reports]

        deleted_reports = 0
        if seeded_report_ids:
            # Remove dependent rows first to satisfy FK constraints.
            db.execute(
                text("DELETE FROM ml_predictions WHERE report_id = ANY(:ids)"),
                {"ids": seeded_report_ids},
            )
            db.execute(
                text("DELETE FROM evidence_files WHERE report_id = ANY(:ids)"),
                {"ids": seeded_report_ids},
            )
            db.execute(
                text("DELETE FROM police_reviews WHERE report_id = ANY(:ids)"),
                {"ids": seeded_report_ids},
            )
            db.execute(
                text("DELETE FROM report_assignments WHERE report_id = ANY(:ids)"),
                {"ids": seeded_report_ids},
            )
            db.execute(
                text("DELETE FROM case_reports WHERE report_id = ANY(:ids)"),
                {"ids": seeded_report_ids},
            )

            # Remove hotspot links pointing to seeded reports first.
            db.execute(
                hotspot_reports_table.delete().where(
                    hotspot_reports_table.c.report_id.in_(seeded_report_ids)
                )
            )
            deleted_reports = (
                db.query(Report)
                .filter(Report.report_id.in_(seeded_report_ids))
                .delete(synchronize_session=False)
            )

        # Remove demo devices if they no longer own any reports.
        demo_devices = (
            db.query(Device)
            .filter(Device.device_hash.like("seed-demo-device-%"))
            .all()
        )
        deleted_devices = 0
        for d in demo_devices:
            has_reports = db.query(Report).filter(Report.device_id == d.device_id).first()
            if has_reports is None:
                db.delete(d)
                deleted_devices += 1

        # Hotspots may still include stale counts/links after report deletion.
        # Rebuild from genuine data for consistency.
        recomputed_hotspots = 0
        if recompute_after:
            db.execute(hotspot_reports_table.delete())
            db.query(Hotspot).delete()
            db.commit()

            tw, mi, rm = get_hotspot_params_from_db(db)
            trust_min = get_hotspot_trust_min_from_db(db)
            recomputed_hotspots = create_hotspots_from_reports(
                db,
                time_window_hours=tw,
                min_incidents=mi,
                radius_meters=rm,
                trust_min=trust_min,
                analyze_all_reports=True,
            )

        db.commit()
        return deleted_reports, deleted_devices, recomputed_hotspots
    finally:
        db.close()


def purge_outside_musanze_reports(recompute_after: bool) -> tuple[int, int]:
    """Remove reports outside covered village polygons and fix in-area village mapping.

    Strategy:
    - Resolve each report coordinate to an active village polygon (if any).
    - Keep in-area reports and normalize village_location_id/location_id.
    - Delete only reports with no containing village (out of covered region).

    Returns:
        (deleted_reports, recomputed_hotspots)
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    r.report_id,
                    v.location_id AS resolved_village_id
                FROM reports r
                LEFT JOIN LATERAL (
                    SELECT l.location_id
                    FROM locations l
                    WHERE l.location_type = 'village'
                      AND l.is_active = true
                      AND l.geometry IS NOT NULL
                      AND ST_Contains(
                          l.geometry,
                          ST_SetSRID(
                              ST_MakePoint(
                                  CAST(r.longitude AS DOUBLE PRECISION),
                                  CAST(r.latitude AS DOUBLE PRECISION)
                              ),
                              4326
                          )
                      )
                    LIMIT 1
                ) v ON TRUE
                """
            )
        ).fetchall()

        in_area_updates = []
        out_ids = []
        for row in rows:
            report_id = row[0]
            resolved_village_id = row[1]
            if resolved_village_id is None:
                out_ids.append(report_id)
            else:
                in_area_updates.append(
                    {
                        "report_id": report_id,
                        "village_location_id": int(resolved_village_id),
                        "location_id": int(resolved_village_id),
                    }
                )

        if in_area_updates:
            db.execute(
                text(
                    """
                    UPDATE reports
                    SET village_location_id = :village_location_id,
                        location_id = :location_id
                    WHERE report_id = :report_id
                    """
                ),
                in_area_updates,
            )

        deleted_reports = 0
        if out_ids:
            db.execute(
                text("DELETE FROM ml_predictions WHERE report_id = ANY(:ids)"),
                {"ids": out_ids},
            )
            db.execute(
                text("DELETE FROM evidence_files WHERE report_id = ANY(:ids)"),
                {"ids": out_ids},
            )
            db.execute(
                text("DELETE FROM police_reviews WHERE report_id = ANY(:ids)"),
                {"ids": out_ids},
            )
            db.execute(
                text("DELETE FROM report_assignments WHERE report_id = ANY(:ids)"),
                {"ids": out_ids},
            )
            db.execute(
                text("DELETE FROM case_reports WHERE report_id = ANY(:ids)"),
                {"ids": out_ids},
            )
            db.execute(
                hotspot_reports_table.delete().where(
                    hotspot_reports_table.c.report_id.in_(out_ids)
                )
            )
            deleted_reports = (
                db.query(Report)
                .filter(Report.report_id.in_(out_ids))
                .delete(synchronize_session=False)
            )

        recomputed_hotspots = 0
        if recompute_after:
            db.execute(hotspot_reports_table.delete())
            db.query(Hotspot).delete()
            db.commit()

            tw, mi, rm = get_hotspot_params_from_db(db)
            trust_min = get_hotspot_trust_min_from_db(db)
            recomputed_hotspots = create_hotspots_from_reports(
                db,
                time_window_hours=tw,
                min_incidents=mi,
                radius_meters=rm,
                trust_min=trust_min,
                analyze_all_reports=True,
            )

        db.commit()
        return deleted_reports, recomputed_hotspots
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo incidents for hotspot visualization")
    parser.add_argument("--reports", type=int, default=60, help="Total reports to create (default: 60)")
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="Recompute hotspots after inserting incidents",
    )
    parser.add_argument(
        "--clear-hotspots",
        action="store_true",
        help="Delete existing hotspots before recompute",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete seeded demo reports/devices created by this script",
    )
    parser.add_argument(
        "--purge-outside-musanze",
        action="store_true",
        help="Delete reports outside covered Musanze village polygons and recompute hotspots",
    )
    args = parser.parse_args()

    if args.purge:
        deleted_reports, deleted_devices, recomputed_hotspots = purge_seeded_data(
            recompute_after=args.recompute or True
        )
        print(
            "Purged seeded data: "
            f"reports={deleted_reports}, devices={deleted_devices}, "
            f"hotspots_recomputed={recomputed_hotspots}"
        )
        return

    if args.purge_outside_musanze:
        deleted_reports, recomputed_hotspots = purge_outside_musanze_reports(
            recompute_after=args.recompute or True
        )
        print(
            "Purged outside-Musanze reports: "
            f"reports={deleted_reports}, hotspots_recomputed={recomputed_hotspots}"
        )
        return

    reports_target = max(50, int(args.reports))
    created, noise_created = seed_incidents(reports_target)
    print(f"Seeded incidents: {created} (noise candidates: {noise_created})")

    if args.recompute:
        hotspot_count = recompute_hotspots(clear_hotspots=args.clear_hotspots)
        print(f"Hotspots created/recomputed: {hotspot_count}")


if __name__ == "__main__":
    main()
