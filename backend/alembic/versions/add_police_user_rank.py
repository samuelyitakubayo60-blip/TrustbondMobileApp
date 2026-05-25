"""Add rank column to police_users."""

from alembic import op
import sqlalchemy as sa

revision = "add_police_user_rank"
down_revision = "add_cluster_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE police_users
          ADD COLUMN IF NOT EXISTS rank VARCHAR(80) NOT NULL DEFAULT 'Police Constable';
        """
    )


def downgrade() -> None:
    op.drop_column("police_users", "rank")
