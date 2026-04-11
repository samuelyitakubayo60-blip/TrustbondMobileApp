"""
Seed initial incident types.

Run:
  python scripts/seed_incident_types.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from decimal import Decimal
from typing import Iterable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Ensure `backend/` is on PYTHONPATH so `import app` works even when executing
# `python scripts/seed_incident_types.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.models.incident_type import IncidentType


DEFAULT_INCIDENT_TYPES: list[dict] = [
    {
        "type_name": "Theft",
        "description": "Stealing of property (e.g., phone, money, livestock).",
        "severity_weight": Decimal("1.20"),
    },
    {
        "type_name": "Assault",
        "description": "Physical attack or violence against a person.",
        "severity_weight": Decimal("1.60"),
    },
    {
        "type_name": "Vandalism",
        "description": "Damage or destruction of public/private property.",
        "severity_weight": Decimal("1.10"),
    },
    {
        "type_name": "Suspicious Activity",
        "description": "Unusual behavior or suspicious movement in the area.",
        "severity_weight": Decimal("1.00"),
    },
    {
        "type_name": "Domestic Violence",
        "description": "Threats or violence within a household/family.",
        "severity_weight": Decimal("1.70"),
    },
    {
        "type_name": "Drug Activity",
        "description": "Suspected selling/using of illegal drugs.",
        "severity_weight": Decimal("1.40"),
    },
    {
        "type_name": "Fraud/Scam",
        "description": "Deception to gain money/property (mobile money scam, etc.).",
        "severity_weight": Decimal("1.30"),
    },
    {
        "type_name": "Harassment",
        "description": "Repeated threats, stalking, or intimidation.",
        "severity_weight": Decimal("1.20"),
    },
    {
        "type_name": "Traffic Incident",
        "description": "Non-emergency road incident affecting safety.",
        "severity_weight": Decimal("1.00"),
    },
]


def seed_incident_types(rows: Iterable[dict] = DEFAULT_INCIDENT_TYPES) -> tuple[int, int]:
    """
    Returns (inserted_count, skipped_count)
    """
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    inserted = 0
    skipped = 0
    try:
        for row in rows:
            existing = db.execute(
                select(IncidentType).where(IncidentType.type_name == row["type_name"])
            ).scalar_one_or_none()
            if existing:
                skipped += 1
                continue
            db.add(
                IncidentType(
                    type_name=row["type_name"],
                    description=row.get("description"),
                    severity_weight=row.get("severity_weight", Decimal("1.00")),
                    is_active=True,
                )
            )
            inserted += 1
        db.commit()
        return inserted, skipped
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    inserted, skipped = seed_incident_types()
    print(f"✅ Incident types seeded. Inserted={inserted}, Skipped(existing)={skipped}")

