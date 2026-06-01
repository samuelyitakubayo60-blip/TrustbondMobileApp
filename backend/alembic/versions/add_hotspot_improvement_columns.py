"""Add hotspot improvement columns (corroboration, prediction, explainability).

Revision ID: add_hotspot_improvement_columns
Revises: add_police_user_rank
Create Date: 2026-06-01
"""

from alembic import op

revision = "add_hotspot_improvement_columns"
down_revision = "add_police_user_rank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE hotspots
            ADD COLUMN IF NOT EXISTS unique_reporter_count INTEGER,
            ADD COLUMN IF NOT EXISTS corroboration_score NUMERIC(5, 4),
            ADD COLUMN IF NOT EXISTS is_multi_crime_zone BOOLEAN,
            ADD COLUMN IF NOT EXISTS multi_crime_groups TEXT,
            ADD COLUMN IF NOT EXISTS predicted_next_state VARCHAR(30),
            ADD COLUMN IF NOT EXISTS predicted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS prediction_verified_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS prediction_was_accurate BOOLEAN,
            ADD COLUMN IF NOT EXISTS explanation_json TEXT,
            ADD COLUMN IF NOT EXISTS cache_version INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS abuse_flag BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS anomaly_score NUMERIC(5, 4)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE hotspots
            DROP COLUMN IF EXISTS unique_reporter_count,
            DROP COLUMN IF EXISTS corroboration_score,
            DROP COLUMN IF EXISTS is_multi_crime_zone,
            DROP COLUMN IF EXISTS multi_crime_groups,
            DROP COLUMN IF EXISTS predicted_next_state,
            DROP COLUMN IF EXISTS predicted_at,
            DROP COLUMN IF EXISTS prediction_verified_at,
            DROP COLUMN IF EXISTS prediction_was_accurate,
            DROP COLUMN IF EXISTS explanation_json,
            DROP COLUMN IF EXISTS cache_version,
            DROP COLUMN IF EXISTS abuse_flag,
            DROP COLUMN IF EXISTS anomaly_score
        """
    )
