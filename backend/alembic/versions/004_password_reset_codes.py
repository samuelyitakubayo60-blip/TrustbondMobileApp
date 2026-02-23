"""Add password_reset_codes table for forgot-password flow

Revision ID: 004
Revises: 003
Create Date: 2026-02-17 00:00:02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_reset_codes_email", "password_reset_codes", ["email"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_codes_email", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")
