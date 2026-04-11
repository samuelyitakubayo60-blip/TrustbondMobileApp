"""
Create an initial admin police user.

Run:
  cd backend
  python scripts/create_admin.py

You can edit the DEFAULT_* values below before running.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.orm import Session

# Ensure `backend/` is on PYTHONPATH so `import app` works
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.security import get_password_hash  # type: ignore
from app.database import SessionLocal  # type: ignore
from app.models.police_user import PoliceUser  # type: ignore


# EDIT THESE BEFORE RUNNING (or run multiple times with different values)
DEFAULT_EMAIL = "samuelyitakubayo60@gmail.com"
DEFAULT_PASSWORD = "Admin123!"
DEFAULT_FIRST_NAME = "System"
DEFAULT_LAST_NAME = "Admin"
DEFAULT_ROLE = "admin"  # admin, supervisor, officer


def main() -> None:
    db: Session = SessionLocal()
    try:
        existing = db.query(PoliceUser).filter(PoliceUser.email == DEFAULT_EMAIL).first()
        if existing:
            print(f"User with email {DEFAULT_EMAIL} already exists (id={existing.police_user_id}). No changes made.")
            return

        user = PoliceUser(
            first_name=DEFAULT_FIRST_NAME,
            middle_name=None,
            last_name=DEFAULT_LAST_NAME,
            email=DEFAULT_EMAIL,
            phone_number=None,
            password_hash=get_password_hash(DEFAULT_PASSWORD),
            badge_number="ADMIN-001",
            role=DEFAULT_ROLE,
            assigned_location_id=None,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print("✅ Created admin user:")
        print(f"   id={user.police_user_id}")
        print(f"   email={user.email}")
        print(f"   role={user.role}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

