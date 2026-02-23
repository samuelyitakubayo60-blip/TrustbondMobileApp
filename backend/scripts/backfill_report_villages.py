"""
One-off backfill of village_location_id for existing reports.

Reports created before we stored village (or with old data) may have
village_location_id = null. This script looks up the village for each
report's (latitude, longitude) using the locations table (point-in-polygon)
and sets village_location_id when the point falls inside a village.

Reports whose coordinates are outside all villages (e.g. outside Musanze)
are left unchanged. New reports are already rejected if outside Musanze.

  cd backend
  python scripts/backfill_report_villages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.report import Report
from app.core.village_lookup import get_village_location_id


def main() -> None:
    db = SessionLocal()
    try:
        # Reports with coordinates but no village set
        reports = (
            db.query(Report)
            .filter(
                Report.village_location_id.is_(None),
                Report.latitude.isnot(None),
                Report.longitude.isnot(None),
            )
            .all()
        )
        updated = 0
        outside = 0
        for r in reports:
            try:
                lat = float(r.latitude)
                lon = float(r.longitude)
            except (TypeError, ValueError):
                continue
            village_id = get_village_location_id(db, lat, lon)
            if village_id is not None:
                r.village_location_id = village_id
                updated += 1
            else:
                outside += 1
        db.commit()
        print(f"Reports checked: {len(reports)}")
        print(f"Updated (point inside a village): {updated}")
        print(f"Left unchanged (outside all villages): {outside}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
