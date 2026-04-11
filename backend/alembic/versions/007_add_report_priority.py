"""Add priority column to reports table

Revision ID: 007
Revises: 006
Create Date: 2026-03-17 18:22:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add priority column to reports table
    op.add_column('reports', sa.Column('priority', sa.String(20), nullable=False, server_default='medium'))


def downgrade() -> None:
    # Remove priority column from reports table
    op.drop_column('reports', 'priority')
