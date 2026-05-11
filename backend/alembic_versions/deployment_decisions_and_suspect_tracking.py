"""Add deployment decisions and suspect/victim tracking

Revision ID: deployment_decisions_and_suspect_tracking
Revises: workflow_leader_gates_and_case_rib
Create Date: 2024-01-15 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'deployment_decisions_and_suspect_tracking'
down_revision = 'workflow_leader_gates_and_case_rib'
branch_labels = None
depends_on = None


def upgrade():
    # Create deployment_decisions table
    op.create_table('deployment_decisions',
        sa.Column('decision_id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=True),
        sa.Column('decided_by', sa.Integer(), nullable=False),
        sa.Column('deployment_status', sa.String(length=20), nullable=True),
        sa.Column('assigned_unit', sa.String(length=80), nullable=True),
        sa.Column('deployment_priority', sa.String(length=20), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('leader_confirmation_weight', sa.Integer(), nullable=True),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('estimated_arrival', sa.DateTime(timezone=True), nullable=True),
        sa.Column('actual_arrival', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deployment_outcome', sa.String(length=50), nullable=True),
        sa.Column('outcome_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ),
        sa.ForeignKeyConstraint(['decided_by'], ['police_users.police_user_id'], ),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id'], ),
        sa.PrimaryKeyConstraint('decision_id')
    )
    op.create_index(op.f('ix_deployment_decisions_decision_id'), 'deployment_decisions', ['decision_id'], unique=False)

    # Create suspect_victim_tracking table
    op.create_table('suspect_victim_tracking',
        sa.Column('tracking_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('person_type', sa.String(length=20), nullable=False),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('national_id', sa.String(length=30), nullable=True),
        sa.Column('phone_number', sa.String(length=20), nullable=True),
        sa.Column('age', sa.Integer(), nullable=True),
        sa.Column('gender', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('status_note', sa.Text(), nullable=True),
        sa.Column('rib_case_number', sa.String(length=50), nullable=True),
        sa.Column('rib_handover_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rib_officer_name', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['case_id'], ['cases.case_id'], ),
        sa.PrimaryKeyConstraint('tracking_id')
    )
    op.create_index(op.f('ix_suspect_victim_tracking_tracking_id'), 'suspect_victim_tracking', ['tracking_id'], unique=False)

    # Add indexes for performance
    op.create_index('ix_deployment_decisions_report_id', 'deployment_decisions', ['report_id'], unique=False)
    op.create_index('ix_deployment_decisions_decided_by', 'deployment_decisions', ['decided_by'], unique=False)
    op.create_index('ix_deployment_decisions_deployment_status', 'deployment_decisions', ['deployment_status'], unique=False)
    op.create_index('ix_suspect_victim_tracking_case_id', 'suspect_victim_tracking', ['case_id'], unique=False)
    op.create_index('ix_suspect_victim_tracking_person_type', 'suspect_victim_tracking', ['person_type'], unique=False)
    op.create_index('ix_suspect_victim_tracking_status', 'suspect_victim_tracking', ['status'], unique=False)


def downgrade():
    # Drop indexes
    op.drop_index('ix_suspect_victim_tracking_status', table_name='suspect_victim_tracking')
    op.drop_index('ix_suspect_victim_tracking_person_type', table_name='suspect_victim_tracking')
    op.drop_index('ix_suspect_victim_tracking_case_id', table_name='suspect_victim_tracking')
    op.drop_index('ix_deployment_decisions_deployment_status', table_name='deployment_decisions')
    op.drop_index('ix_deployment_decisions_decided_by', table_name='deployment_decisions')
    op.drop_index('ix_deployment_decisions_report_id', table_name='deployment_decisions')
    
    # Drop tables
    op.drop_table('suspect_victim_tracking')
    op.drop_table('deployment_decisions')
