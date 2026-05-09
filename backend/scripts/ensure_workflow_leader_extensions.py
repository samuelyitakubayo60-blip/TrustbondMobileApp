"""
Add workflow columns (leader submit FK, case RIB fields) if missing.

From repo root:
  python -m scripts.ensure_workflow_leader_extensions
(from the backend directory, same as other scripts under scripts/)

Or with explicit path (still resolves imports):
  python scripts/ensure_workflow_leader_extensions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from sqlalchemy import create_engine, text

from app.config import settings


def main() -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    stmts = [
        """
        ALTER TABLE reports
          ADD COLUMN IF NOT EXISTS submitted_by_local_leader_id INTEGER
          REFERENCES local_leaders(local_leader_id) ON DELETE SET NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_reports_submitted_by_local_leader_id
          ON reports (submitted_by_local_leader_id);
        """,
        """
        ALTER TABLE cases ADD COLUMN IF NOT EXISTS special_assignment_unit VARCHAR(80);
        ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handed_over_at TIMESTAMPTZ;
        ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handover_summary TEXT;
        """,
        """
        ALTER TABLE local_leaders ADD COLUMN IF NOT EXISTS fcm_device_token VARCHAR(512);
        """,
        """
        ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS default_special_assignment_unit VARCHAR(80);
        """,
        """
        UPDATE reports
        SET leader_verification_status = 'confirmed'
        WHERE verification_status = 'verified'
          AND (leader_verification_status IS NULL OR leader_verification_status = 'pending');
        """,
    ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))


if __name__ == "__main__":
    main()
