"""Idempotent DDL for workflow / leader / incident-type columns.

Used on startup (so production matches ORM) and by scripts/ensure_workflow_leader_extensions.py.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Keep in sync with SQLAlchemy models (reports, cases, local_leaders, local_leader_auth_codes, incident_types).
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
    """,
    """
    ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handed_over_at TIMESTAMPTZ;
    """,
    """
    ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handover_summary TEXT;
    """,
    """
    ALTER TABLE cases ADD COLUMN IF NOT EXISTS rib_handover_prerequisites_acknowledged BOOLEAN NOT NULL DEFAULT FALSE;
    """,
    """
    ALTER TABLE local_leaders ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'executive_of_cell';
    ALTER TABLE local_leaders ALTER COLUMN phone_number DROP NOT NULL;
    """,
    """
    ALTER TABLE local_leader_auth_codes ALTER COLUMN phone_number DROP NOT NULL;
    """,
    """
    ALTER TABLE local_leaders ADD COLUMN IF NOT EXISTS fcm_device_token VARCHAR(512);
    """,
    """
    ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS default_special_assignment_unit VARCHAR(80);
    """,
    """
    CREATE TABLE IF NOT EXISTS special_assignment_units (
      unit_id SERIAL PRIMARY KEY,
      unit_code VARCHAR(50) NOT NULL UNIQUE,
      unit_name VARCHAR(100) NOT NULL,
      description VARCHAR(500),
      is_active BOOLEAN NOT NULL DEFAULT TRUE,
      requires_commander_approval BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    ALTER TABLE special_assignment_units
      ADD COLUMN IF NOT EXISTS commander_user_id INTEGER REFERENCES police_users(police_user_id);
    """,
    """
    INSERT INTO special_assignment_units (unit_code, unit_name, description)
    VALUES
      ('RIB', 'RIB — Investigation Bureau', 'Serious crime / investigation handover'),
      ('TRAFFIC', 'Traffic Police', 'Road traffic incidents and enforcement'),
      ('COUNTER_TERROR', 'Counter Terror Unit', 'Terrorism-related deployments'),
      ('FIRE_RESCUE', 'Fire & Rescue', 'Fire and rescue response'),
      ('QUICK_RESPONSE', 'Quick Response Team', 'Rapid deployment to active incidents'),
      ('GENERAL_PATROL', 'General Patrol', 'Routine patrol and community response')
    ON CONFLICT (unit_code) DO NOTHING;
    """,
)
_log = logging.getLogger(__name__)

# One-time-style data fix; run from the ensure script, not every app startup.
LEADER_VERIFIED_BACKFILL_SQL = """
UPDATE reports
SET leader_verification_status = 'confirmed'
WHERE verification_status = 'verified'
  AND (leader_verification_status IS NULL OR leader_verification_status = 'pending');
"""


def apply_workflow_schema_ddl(engine: Engine) -> None:
    """Add missing columns/indexes. Safe to call on every deploy."""
    for stmt in DDL_STATEMENTS:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as exc:
            # Best-effort startup alignment: continue so one timeout/lock does not block other fixes.
            _log.warning("Workflow DDL statement failed: %s", exc)


def apply_leader_verified_backfill(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(LEADER_VERIFIED_BACKFILL_SQL))
