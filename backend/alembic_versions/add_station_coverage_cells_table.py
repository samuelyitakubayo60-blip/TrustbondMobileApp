"""Add station coverage cells table

Revision ID: add_station_coverage_cells_table
Revises: add_enhanced_audit_log_fields
Create Date: 2026-05-07 07:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_station_coverage_cells_table"
down_revision = "add_enhanced_audit_log_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "station_coverage_cells",
        sa.Column("station_coverage_cell_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.station_id", ondelete="CASCADE"), nullable=False),
        sa.Column("cell_location_id", sa.Integer(), sa.ForeignKey("locations.location_id"), nullable=False),
        sa.UniqueConstraint("station_id", "cell_location_id", name="uq_station_coverage_cell"),
    )
    op.create_index(
        "ix_station_coverage_cells_station_id",
        "station_coverage_cells",
        ["station_id"],
    )
    op.create_index(
        "ix_station_coverage_cells_cell_location_id",
        "station_coverage_cells",
        ["cell_location_id"],
    )


def downgrade():
    op.drop_index("ix_station_coverage_cells_cell_location_id", table_name="station_coverage_cells")
    op.drop_index("ix_station_coverage_cells_station_id", table_name="station_coverage_cells")
    op.drop_table("station_coverage_cells")
