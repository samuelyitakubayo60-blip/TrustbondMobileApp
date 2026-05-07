"""Drop legacy station sector columns

Revision ID: drop_station_legacy_sector_columns
Revises: add_station_coverage_cells_table
Create Date: 2026-05-07 08:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "drop_station_legacy_sector_columns"
down_revision = "add_station_coverage_cells_table"
branch_labels = None
depends_on = None


def upgrade():
    # CASCADE handles foreign key constraints on these columns.
    op.execute("ALTER TABLE stations DROP COLUMN IF EXISTS location_id CASCADE;")
    op.execute("ALTER TABLE stations DROP COLUMN IF EXISTS sector2_id CASCADE;")


def downgrade():
    # Re-add columns as nullable.
    op.add_column("stations", sa.Column("location_id", sa.Integer(), nullable=True))
    op.add_column("stations", sa.Column("sector2_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_stations_location_id_locations",
        "stations",
        "locations",
        ["location_id"],
        ["location_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stations_sector2_id_locations",
        "stations",
        "locations",
        ["sector2_id"],
        ["location_id"],
        ondelete="SET NULL",
    )

