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
    ALTER TABLE police_users ADD COLUMN IF NOT EXISTS rank VARCHAR(80) NOT NULL DEFAULT 'Police Constable';
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
    # Hotspots before heavy local_leaders ALTER so map/alerts work even if leader DDL times out
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
    ALTER TABLE hotspots
      ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(30),
      ADD COLUMN IF NOT EXISTS composition TEXT,
      ADD COLUMN IF NOT EXISTS temporal_intensity NUMERIC(10,4),
      ADD COLUMN IF NOT EXISTS severity_score NUMERIC(6,4),
      ADD COLUMN IF NOT EXISTS trend_direction VARCHAR(20),
      ADD COLUMN IF NOT EXISTS cluster_confidence NUMERIC(5,4),
      ADD COLUMN IF NOT EXISTS polygon_points TEXT,
      ADD COLUMN IF NOT EXISTS crime_group VARCHAR(30),
      ADD COLUMN IF NOT EXISTS llm_narrative TEXT,
      ADD COLUMN IF NOT EXISTS llm_recommendation TEXT,
      ADD COLUMN IF NOT EXISTS llm_status VARCHAR(60),
      ADD COLUMN IF NOT EXISTS llm_citizen_advisory TEXT,
      ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(40),
      ADD COLUMN IF NOT EXISTS llm_generated_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS unique_reporter_count INTEGER,
      ADD COLUMN IF NOT EXISTS corroboration_score NUMERIC(5,4),
      ADD COLUMN IF NOT EXISTS is_multi_crime_zone BOOLEAN DEFAULT FALSE,
      ADD COLUMN IF NOT EXISTS multi_crime_groups TEXT,
      ADD COLUMN IF NOT EXISTS predicted_next_state VARCHAR(30),
      ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS prediction_verified_at TIMESTAMPTZ,
      ADD COLUMN IF NOT EXISTS prediction_was_accurate BOOLEAN,
      ADD COLUMN IF NOT EXISTS explanation_json TEXT,
      ADD COLUMN IF NOT EXISTS cache_version INTEGER DEFAULT 0,
      ADD COLUMN IF NOT EXISTS abuse_flag BOOLEAN DEFAULT FALSE,
      ADD COLUMN IF NOT EXISTS anomaly_score NUMERIC(5,4);
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
    ALTER TABLE incident_types ADD COLUMN IF NOT EXISTS semantic_definition TEXT;
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
    CREATE TABLE IF NOT EXISTS station_coverage_cells (
      station_coverage_cell_id SERIAL PRIMARY KEY,
      station_id INTEGER NOT NULL REFERENCES stations(station_id) ON DELETE CASCADE,
      cell_location_id INTEGER NOT NULL REFERENCES locations(location_id),
      UNIQUE (station_id, cell_location_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS deployment_decisions (
      decision_id SERIAL PRIMARY KEY,
      report_id UUID NOT NULL REFERENCES reports(report_id),
      case_id UUID REFERENCES cases(case_id),
      decided_by INTEGER NOT NULL REFERENCES police_users(police_user_id),
      deployment_status VARCHAR(20) DEFAULT 'pending',
      assigned_unit VARCHAR(80),
      deployment_priority VARCHAR(20) DEFAULT 'medium',
      decision_note TEXT,
      leader_confirmation_weight INTEGER DEFAULT 0,
      deployed_at TIMESTAMPTZ,
      estimated_arrival TIMESTAMPTZ,
      actual_arrival TIMESTAMPTZ,
      deployment_outcome VARCHAR(50),
      outcome_note TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_deployment_decisions_report_id
      ON deployment_decisions (report_id);
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
    """Run idempotent DDL on startup. Uses per-statement transactions and longer timeouts for heavy ALTERs."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET lock_timeout = '120s'"))
            conn.execute(text("SET statement_timeout = '120s'"))
            conn.commit()
    except Exception as exc:
        _log.warning("Could not set session timeouts for DDL: %s", exc)

    for i, stmt in enumerate(DDL_STATEMENTS):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            _log.info("Workflow DDL statement %s/%s applied.", i + 1, len(DDL_STATEMENTS))
        except Exception as exc:
            _log.warning("Workflow DDL statement %s/%s failed: %s", i + 1, len(DDL_STATEMENTS), exc)


def ensure_hotspot_cluster_columns(engine: Engine) -> list[str]:
    """Verify hotspot clustering columns exist; return names still missing (for logs)."""
    required = (
        "lifecycle_state",
        "composition",
        "temporal_intensity",
        "severity_score",
        "trend_direction",
        "cluster_confidence",
        "polygon_points",
        "crime_group",
        "llm_narrative",
        "llm_recommendation",
        "llm_status",
        "llm_citizen_advisory",
        "llm_provider",
        "llm_generated_at",
        "assigned_unit_code",
        "controlled_by_user_id",
        "deployed_at",
        "deployment_note",
    )
    missing: list[str] = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'hotspots'
                    """
                )
            ).fetchall()
            present = {r[0] for r in rows}
            missing = [c for c in required if c not in present]
    except Exception as exc:
        _log.warning("Could not verify hotspot columns: %s", exc)
        return required
    if missing:
        _log.error(
            "Hotspots table is missing columns after DDL: %s. "
            "Re-run apply_workflow_schema_ddl or execute alembic upgrade head.",
            ", ".join(missing),
        )
    else:
        _log.info("Hotspots table has all expected workflow/cluster columns.")
    return missing


def apply_leader_verified_backfill(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(LEADER_VERIFIED_BACKFILL_SQL))
