"""Add incident_type_id to hotspots (same place + same type = hotspot)

Revision ID: 003
Revises: 002
Create Date: 2026-02-17 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hotspots",
        sa.Column("incident_type_id", sa.SmallInteger(), sa.ForeignKey("incident_types.incident_type_id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hotspots", "incident_type_id")
