"""Add local leaders and leader verification

Revision ID: add_local_leaders_and_leader_verification
Revises: drop_station_legacy_sector_columns
Create Date: 2026-05-07 19:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_local_leaders_and_leader_verification"
down_revision = "drop_station_legacy_sector_columns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "local_leaders",
        sa.Column("local_leader_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False, unique=True),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_local_leaders_phone_number", "local_leaders", ["phone_number"])
    op.create_index("ix_local_leaders_email", "local_leaders", ["email"])

    op.create_table(
        "local_leader_coverage_locations",
        sa.Column("local_leader_coverage_location_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("local_leader_id", sa.Integer(), sa.ForeignKey("local_leaders.local_leader_id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.location_id"), nullable=False),
        sa.UniqueConstraint("local_leader_id", "location_id", name="uq_local_leader_coverage_location"),
    )

    op.create_table(
        "local_leader_auth_codes",
        sa.Column("local_leader_auth_code_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("local_leader_id", sa.Integer(), sa.ForeignKey("local_leaders.local_leader_id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False, server_default="password_setup"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_local_leader_auth_codes_local_leader_id", "local_leader_auth_codes", ["local_leader_id"])
    op.create_index("ix_local_leader_auth_codes_phone_number", "local_leader_auth_codes", ["phone_number"])
    op.create_index(
        "ix_local_leader_coverage_locations_local_leader_id",
        "local_leader_coverage_locations",
        ["local_leader_id"],
    )
    op.create_index(
        "ix_local_leader_coverage_locations_location_id",
        "local_leader_coverage_locations",
        ["location_id"],
    )

    op.add_column(
        "reports",
        sa.Column("leader_verification_status", sa.String(length=20), server_default="pending"),
    )
    op.add_column("reports", sa.Column("leader_verified_by", sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("leader_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("leader_verification_note", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_reports_leader_verified_by",
        "reports",
        "local_leaders",
        ["leader_verified_by"],
        ["local_leader_id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_reports_leader_verified_by", "reports", type_="foreignkey")
    op.drop_column("reports", "leader_verification_note")
    op.drop_column("reports", "leader_verified_at")
    op.drop_column("reports", "leader_verified_by")
    op.drop_column("reports", "leader_verification_status")

    op.drop_index("ix_local_leader_coverage_locations_location_id", table_name="local_leader_coverage_locations")
    op.drop_index("ix_local_leader_coverage_locations_local_leader_id", table_name="local_leader_coverage_locations")
    op.drop_table("local_leader_coverage_locations")

    op.drop_index("ix_local_leader_auth_codes_phone_number", table_name="local_leader_auth_codes")
    op.drop_index("ix_local_leader_auth_codes_local_leader_id", table_name="local_leader_auth_codes")
    op.drop_table("local_leader_auth_codes")

    op.drop_index("ix_local_leaders_email", table_name="local_leaders")
    op.drop_index("ix_local_leaders_phone_number", table_name="local_leaders")
    op.drop_table("local_leaders")

