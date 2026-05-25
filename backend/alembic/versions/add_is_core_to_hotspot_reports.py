"""add is_core column to hotspot_reports junction table

Revision ID: add_is_core_hotspot_reports
Revises: drop_police_reviews
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_is_core_hotspot_reports"
down_revision = "drop_police_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE hotspot_reports
        ADD COLUMN IF NOT EXISTS is_core BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE hotspot_reports
        DROP COLUMN IF EXISTS is_core
        """
    )
