"""
Optional: one-off backfill of hotspots from existing reports. The app normally
creates hotspots automatically on each new report (no cron or manual run).

Use this script only to backfill hotspots from data that existed before
auto-creation was enabled.

  cd backend
  python scripts/create_hotspots.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure `backend/` is on PYTHONPATH so `import app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # type: ignore
from app.core.hotspot_auto import create_hotspots_from_reports  # type: ignore


# Requirements: min_incidents reports within time_window_hours in same area (bucket)
TIME_WINDOW_HOURS = 24
MIN_INCIDENTS = 2
RADIUS_METERS = 500


def main() -> None:
    db = SessionLocal()
    try:
        created = create_hotspots_from_reports(
            db,
            time_window_hours=TIME_WINDOW_HOURS,
            min_incidents=MIN_INCIDENTS,
            radius_meters=RADIUS_METERS,
        )
        print(f"Created {created} hotspot(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
