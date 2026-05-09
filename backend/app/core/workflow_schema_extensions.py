"""Idempotent DDL for workflow / leader / incident-type columns.

Used on startup (so production matches ORM) and by scripts/ensure_workflow_leader_extensions.py.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Keep in sync with SQLAlchemy models (reports, cases, local_leaders, incident_types).
DDL_STATEMENTS: tuple[str, ...] = (
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
    ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handover_prerequisites_acknowledged BOOLEAN NOT NULL DEFAULT FALSE;
    """,
    """
    ALTER TABLE local_leaders ADD COLUMN IF NOT EXISTS fcm_device_token VARCHAR(512);
    """,
    """
    ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS default_special_assignment_unit VARCHAR(80);
    """,
)

# One-time-style data fix; run from the ensure script, not every app startup.
LEADER_VERIFIED_BACKFILL_SQL = """
UPDATE reports
SET leader_verification_status = 'confirmed'
WHERE verification_status = 'verified'
  AND (leader_verification_status IS NULL OR leader_verification_status = 'pending');
"""


def apply_workflow_schema_ddl(engine: Engine) -> None:
    """Add missing columns/indexes. Safe to call on every deploy."""
    with engine.begin() as conn:
        for stmt in DDL_STATEMENTS:
            conn.execute(text(stmt))


def apply_leader_verified_backfill(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(LEADER_VERIFIED_BACKFILL_SQL))
