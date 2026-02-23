"""
Initialize database:
  1) Run Alembic migrations (create all tables)
  2) Seed incident types
  3) Populate Musanze locations (sectors/cells/villages + geometry)

Run:
  cd backend
  python scripts/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure `backend/` is on PYTHONPATH so `import app` works even when executing
# `python scripts/init_db.py` (where sys.path[0] becomes `backend/scripts`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from scripts.seed_incident_types import seed_incident_types
from scripts.populate_locations import populate_locations


def _ensure_postgis():
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()


def _locations_already_populated() -> bool:
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        count = db.execute(text("SELECT COUNT(*) FROM locations")).scalar() or 0
        return int(count) > 0
    finally:
        db.close()


def main():
    print("== TrustBond DB init ==")
    print("1) Ensuring PostGIS extension…")
    _ensure_postgis()

    print("2) Running migrations (alembic upgrade head)…")
    subprocess.run(["alembic", "upgrade", "head"], check=True)

    print("3) Seeding incident types…")
    inserted, skipped = seed_incident_types()
    print(f"   Incident types: inserted={inserted}, skipped={skipped}")

    print("4) Populating Musanze locations…")
    # Always run population; script is resumable and skips existing rows safely.
    populate_locations()

    print("✅ Done.")


if __name__ == "__main__":
    main()

