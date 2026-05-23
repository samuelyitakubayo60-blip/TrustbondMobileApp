"""Idempotent DDL for workflow / leader / incident-type / station columns."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

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
    ALTER TABLE cases ADD COLUMN IF NOT EXISTS station_id INTEGER REFERENCES stations(station_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_cases_station_id ON cases (station_id);
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
    ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS assigned_unit_code VARCHAR(80);
    """,
    """
    ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS controlled_by_user_id INTEGER REFERENCES police_users(police_user_id);
    """,
    """
    ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS deployed_at TIMESTAMPTZ;
    """,
    """
    ALTER TABLE hotspots ADD COLUMN IF NOT EXISTS deployment_note VARCHAR(500);
    """,
    """
    CREATE TABLE IF NOT EXISTS station_coverage_cells (
      station_coverage_cell_id SERIAL PRIMARY KEY,
      station_id INTEGER NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
      cell_location_id INTEGER NOT NULL REFERENCES locations(location_id),
      UNIQUE (station_id, cell_location_id)
    );
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

LEADER_VERIFIED_BACKFILL_SQL = """
UPDATE reports
SET leader_verification_status = 'confirmed'
WHERE verification_status = 'verified'
  AND (leader_verification_status IS NULL OR leader_verification_status = 'pending');
"""


def apply_workflow_schema_ddl(engine: Engine) -> None:
    for stmt in DDL_STATEMENTS:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as exc:
            _log.warning("Workflow DDL statement failed: %s", exc)


def apply_leader_verified_backfill(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(LEADER_VERIFIED_BACKFILL_SQL))
