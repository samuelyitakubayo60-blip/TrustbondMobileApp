"""Local leader role + nullable phone (email OTP)

Revision ID: local_leader_role_email_otp
Revises: add_local_leaders_and_leader_verification
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa


revision = "local_leader_role_email_otp"
down_revision = "add_local_leaders_and_leader_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "local_leaders",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="executive_of_cell"),
    )
    op.alter_column(
        "local_leaders",
        "phone_number",
        existing_type=sa.String(length=20),
        nullable=True,
    )
    op.alter_column(
        "local_leader_auth_codes",
        "phone_number",
        existing_type=sa.String(length=20),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "local_leader_auth_codes",
        "phone_number",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.alter_column(
        "local_leaders",
        "phone_number",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.drop_column("local_leaders", "role")
