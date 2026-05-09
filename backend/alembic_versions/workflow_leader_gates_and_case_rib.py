"""Report leader submit FK; case RIB/special unit; grandfather leader confirmation

Revision ID: workflow_leader_gates_and_case_rib
Revises: local_leader_role_email_otp
"""

from alembic import op
import sqlalchemy as sa


revision = "workflow_leader_gates_and_case_rib"
down_revision = "local_leader_role_email_otp"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reports",
        sa.Column(
            "submitted_by_local_leader_id",
            sa.Integer(),
            sa.ForeignKey("local_leaders.local_leader_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_reports_submitted_by_local_leader_id",
        "reports",
        ["submitted_by_local_leader_id"],
    )

    op.add_column("cases", sa.Column("special_assignment_unit", sa.String(length=80), nullable=True))
    op.add_column("cases", sa.Column("rib_handed_over_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("rib_handover_summary", sa.Text(), nullable=True))

    # Existing police-verified reports: treat as community-cleared for workflow continuity
    op.execute(
        """
        UPDATE reports
        SET leader_verification_status = 'confirmed'
        WHERE verification_status = 'verified'
          AND (leader_verification_status IS NULL OR leader_verification_status = 'pending')
        """
    )


def downgrade():
    op.drop_index("ix_reports_submitted_by_local_leader_id", table_name="reports")
    op.drop_column("reports", "submitted_by_local_leader_id")
    op.drop_column("cases", "rib_handover_summary")
    op.drop_column("cases", "rib_handed_over_at")
    op.drop_column("cases", "special_assignment_unit")
