"""Change locations.geometry to MULTIPOLYGON

Revision ID: 002
Revises: 001
Create Date: 2026-02-17 00:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Convert POLYGON -> MULTIPOLYGON (safe even if already multipolygon)
    op.execute(
        """
        ALTER TABLE locations
        ALTER COLUMN geometry
        TYPE geometry(MULTIPOLYGON, 4326)
        USING ST_Multi(geometry);
        """
    )


def downgrade() -> None:
    # NOTE: Downgrade may fail if any row contains a true MultiPolygon.
    op.execute(
        """
        ALTER TABLE locations
        ALTER COLUMN geometry
        TYPE geometry(POLYGON, 4326)
        USING (ST_GeometryN(geometry, 1))::geometry(POLYGON, 4326);
        """
    )

