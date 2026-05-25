"""add clustering enhancement columns to hotspots

Revision ID: add_cluster_enhancements
Revises: add_is_core_hotspot_reports
Create Date: 2026-05-25
"""
from alembic import op

revision = "add_cluster_enhancements"
down_revision = "add_is_core_hotspot_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE hotspots
            ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(30),
            ADD COLUMN IF NOT EXISTS composition TEXT,
            ADD COLUMN IF NOT EXISTS temporal_intensity NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS severity_score NUMERIC(6,4),
            ADD COLUMN IF NOT EXISTS trend_direction VARCHAR(20),
            ADD COLUMN IF NOT EXISTS cluster_confidence NUMERIC(5,4),
            ADD COLUMN IF NOT EXISTS polygon_points TEXT,
            ADD COLUMN IF NOT EXISTS crime_group VARCHAR(30)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE hotspots
            DROP COLUMN IF EXISTS lifecycle_state,
            DROP COLUMN IF EXISTS composition,
            DROP COLUMN IF EXISTS temporal_intensity,
            DROP COLUMN IF EXISTS severity_score,
            DROP COLUMN IF EXISTS trend_direction,
            DROP COLUMN IF EXISTS cluster_confidence,
            DROP COLUMN IF EXISTS polygon_points,
            DROP COLUMN IF EXISTS crime_group
    """)
