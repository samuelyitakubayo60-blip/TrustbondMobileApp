"""Add deployment value to notification_type enum.

Revision ID: add_notification_type_deployment
Revises: add_deployment_decisions_table
Create Date: 2026-05-29
"""

from alembic import op

revision = "add_notification_type_deployment"
down_revision = "add_deployment_decisions_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'deployment'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
