"""Add AI description and verification reason columns to reports.

Revision ID: 010
Revises: 8249aed786d3
Create Date: 2026-04-27 23:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "8249aed786d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = inspector.get_columns(table_name)
    return any(c.get("name") == column_name for c in cols)


def upgrade() -> None:
    if not _has_column("reports", "ai_evidence_description"):
        op.add_column("reports", sa.Column("ai_evidence_description", sa.Text(), nullable=True))
    if not _has_column("reports", "ai_verification_reason"):
        op.add_column("reports", sa.Column("ai_verification_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("reports", "ai_verification_reason"):
        op.drop_column("reports", "ai_verification_reason")
    if _has_column("reports", "ai_evidence_description"):
        op.drop_column("reports", "ai_evidence_description")

