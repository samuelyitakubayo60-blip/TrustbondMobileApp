"""Add MFA fields to police_users and mfa_codes table.

Revision ID: add_mfa_fields
Revises: add_hotspot_improvement_columns
Create Date: 2026-06-03
"""

from alembic import op

revision = "add_mfa_fields"
down_revision = "add_hotspot_improvement_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE police_users
            ADD COLUMN IF NOT EXISTS last_password_change TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS mfa_method VARCHAR(20) DEFAULT 'email';
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mfa_codes (
            id SERIAL PRIMARY KEY,
            police_user_id INTEGER NOT NULL REFERENCES police_users(police_user_id) ON DELETE CASCADE,
            code VARCHAR(6) NOT NULL,
            purpose VARCHAR(20) NOT NULL DEFAULT 'login',
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS ix_mfa_codes_user_purpose
            ON mfa_codes (police_user_id, purpose, expires_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mfa_codes;")
    op.execute(
        """
        ALTER TABLE police_users
            DROP COLUMN IF EXISTS last_password_change,
            DROP COLUMN IF EXISTS mfa_enabled,
            DROP COLUMN IF EXISTS mfa_method;
        """
    )
