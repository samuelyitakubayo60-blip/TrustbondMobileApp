"""Add cases and case_reports tables

Revision ID: 006
Revises: 005
Create Date: 2025-01-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_number", sa.String(20)),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.location_id")),
        sa.Column("incident_type_id", sa.SmallInteger(), sa.ForeignKey("incident_types.incident_type_id")),
        sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("police_users.police_user_id")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("police_users.police_user_id")),
        sa.Column("report_count", sa.Integer(), default=0),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cases_case_number", "cases", ["case_number"], unique=True)
    op.create_index("ix_cases_status", "cases", ["status"])

    # gen_random_uuid() is built-in in PostgreSQL 13+
    op.execute("ALTER TABLE cases ALTER COLUMN case_id SET DEFAULT gen_random_uuid()")

    op.create_table(
        "case_reports",
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.case_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.report_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_case_reports_case_id", "case_reports", ["case_id"])
    op.create_index("ix_case_reports_report_id", "case_reports", ["report_id"])


def downgrade() -> None:
    op.drop_table("case_reports")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_case_number", table_name="cases")
    op.drop_table("cases")
