"""drop police_reviews table

Revision ID: drop_police_reviews
Revises:
Create Date: 2026-05-23

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "drop_police_reviews"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS police_reviews CASCADE")


def downgrade() -> None:
    # Intentionally left empty — police review is permanently removed.
    pass
