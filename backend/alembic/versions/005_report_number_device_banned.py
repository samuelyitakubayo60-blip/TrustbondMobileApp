"""Add report_number to reports, is_banned to devices

Revision ID: 005
Revises: 004
Create Date: 2025-01-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("report_number", sa.String(20)))
    op.execute("""
        WITH num AS (
            SELECT report_id,
                   TO_CHAR(COALESCE(reported_at, NOW()) AT TIME ZONE 'UTC', 'YYYY') AS yr,
                   ROW_NUMBER() OVER (PARTITION BY TO_CHAR(COALESCE(reported_at, NOW()) AT TIME ZONE 'UTC', 'YYYY') ORDER BY reported_at NULLS LAST, report_id) AS rn
            FROM reports
        )
        UPDATE reports r
        SET report_number = 'RPT-' || n.yr || '-' || LPAD(n.rn::TEXT, 4, '0')
        FROM num n WHERE r.report_id = n.report_id
    """)
    op.alter_column("reports", "report_number", nullable=False)
    op.create_index("ix_reports_report_number", "reports", ["report_number"], unique=True)

    op.add_column("devices", sa.Column("is_banned", sa.Boolean(), server_default="false"))


def downgrade() -> None:
    op.drop_index("ix_reports_report_number", table_name="reports")
    op.drop_column("reports", "report_number")
    op.drop_column("devices", "is_banned")
