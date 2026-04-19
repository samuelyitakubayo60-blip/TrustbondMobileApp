"""Add enhanced audit log fields

Revision ID: add_enhanced_audit_log_fields
Revises: 
Create Date: 2026-04-19 11:17:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_enhanced_audit_log_fields'
down_revision = None  # This will be set by Alembic
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to audit_logs table
    op.add_column('audit_logs', sa.Column('actor_role', sa.String(length=50), nullable=True))
    op.add_column('audit_logs', sa.Column('masked_details', sa.JSON(), nullable=True))
    op.add_column('audit_logs', sa.Column('sensitivity_level', sa.String(length=20), nullable=True))
    
    # Add indexes for better performance
    op.create_index('ix_audit_logs_actor_role', 'audit_logs', ['actor_role'])
    op.create_index('ix_audit_logs_sensitivity_level', 'audit_logs', ['sensitivity_level'])


def downgrade():
    # Remove indexes
    op.drop_index('ix_audit_logs_sensitivity_level', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_role', table_name='audit_logs')
    
    # Remove columns
    op.drop_column('audit_logs', 'sensitivity_level')
    op.drop_column('audit_logs', 'masked_details')
    op.drop_column('audit_logs', 'actor_role')
