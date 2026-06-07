"""Ensure deployment_decisions table exists for hotspot unit deploy.

Revision ID: add_deployment_decisions_table
Revises: add_hotspot_improvement_columns
Create Date: 2026-06-07
"""

from alembic import op

revision = "add_deployment_decisions_table"
down_revision = "add_hotspot_improvement_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_decisions (
          decision_id SERIAL PRIMARY KEY,
          report_id UUID NOT NULL REFERENCES reports(report_id),
          case_id UUID REFERENCES cases(case_id),
          decided_by INTEGER NOT NULL REFERENCES police_users(police_user_id),
          deployment_status VARCHAR(20) DEFAULT 'pending',
          assigned_unit VARCHAR(80),
          deployment_priority VARCHAR(20) DEFAULT 'medium',
          decision_note TEXT,
          leader_confirmation_weight INTEGER DEFAULT 0,
          deployed_at TIMESTAMPTZ,
          estimated_arrival TIMESTAMPTZ,
          actual_arrival TIMESTAMPTZ,
          deployment_outcome VARCHAR(50),
          outcome_note TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW(),
          updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_deployment_decisions_report_id
          ON deployment_decisions (report_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_deployment_decisions_report_id")
    op.execute("DROP TABLE IF EXISTS deployment_decisions")
