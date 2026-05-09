"""
Ensure local leader tables and report leader-verification columns exist.

This is a hotfix helper for environments without Alembic applied.

Run:
  python -m scripts.ensure_local_leaders_tables
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from app.config import settings


def main() -> None:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    create_local_leaders = """
    CREATE TABLE IF NOT EXISTS local_leaders (
        local_leader_id SERIAL PRIMARY KEY,
        full_name VARCHAR(200) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'executive_of_cell',
        phone_number VARCHAR(20) UNIQUE,
        email VARCHAR(255) UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now(),
        last_login_at TIMESTAMPTZ
    );
    CREATE INDEX IF NOT EXISTS ix_local_leaders_phone_number ON local_leaders (phone_number);
    CREATE INDEX IF NOT EXISTS ix_local_leaders_email ON local_leaders (email);
    """
    migrate_local_leaders_cols = """
    ALTER TABLE local_leaders ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'executive_of_cell';
    ALTER TABLE local_leaders ALTER COLUMN phone_number DROP NOT NULL;
    ALTER TABLE local_leader_auth_codes ALTER COLUMN phone_number DROP NOT NULL;
    """

    create_coverage = """
    CREATE TABLE IF NOT EXISTS local_leader_coverage_locations (
        local_leader_coverage_location_id SERIAL PRIMARY KEY,
        local_leader_id INTEGER NOT NULL REFERENCES local_leaders(local_leader_id) ON DELETE CASCADE,
        location_id INTEGER NOT NULL REFERENCES locations(location_id),
        CONSTRAINT uq_local_leader_coverage_location UNIQUE (local_leader_id, location_id)
    );
    CREATE INDEX IF NOT EXISTS ix_local_leader_coverage_locations_local_leader_id
      ON local_leader_coverage_locations (local_leader_id);
    CREATE INDEX IF NOT EXISTS ix_local_leader_coverage_locations_location_id
      ON local_leader_coverage_locations (location_id);
    """

    create_auth_codes = """
    CREATE TABLE IF NOT EXISTS local_leader_auth_codes (
        local_leader_auth_code_id SERIAL PRIMARY KEY,
        local_leader_id INTEGER NOT NULL REFERENCES local_leaders(local_leader_id) ON DELETE CASCADE,
        phone_number VARCHAR(20),
        code VARCHAR(10) NOT NULL,
        purpose VARCHAR(30) NOT NULL DEFAULT 'password_setup',
        expires_at TIMESTAMPTZ NOT NULL,
        used_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_local_leader_auth_codes_local_leader_id
      ON local_leader_auth_codes (local_leader_id);
    CREATE INDEX IF NOT EXISTS ix_local_leader_auth_codes_phone_number
      ON local_leader_auth_codes (phone_number);
    """

    alter_reports = """
    ALTER TABLE reports
      ADD COLUMN IF NOT EXISTS leader_verification_status VARCHAR(20) DEFAULT 'pending';
    ALTER TABLE reports
      ADD COLUMN IF NOT EXISTS leader_verified_by INTEGER;
    ALTER TABLE reports
      ADD COLUMN IF NOT EXISTS leader_verified_at TIMESTAMPTZ;
    ALTER TABLE reports
      ADD COLUMN IF NOT EXISTS leader_verification_note TEXT;
    """

    fk_reports = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_reports_leader_verified_by'
        ) THEN
            ALTER TABLE reports
              ADD CONSTRAINT fk_reports_leader_verified_by
              FOREIGN KEY (leader_verified_by) REFERENCES local_leaders(local_leader_id)
              ON DELETE SET NULL;
        END IF;
    END $$;
    """

    with engine.begin() as conn:
        conn.execute(text(create_local_leaders))
        conn.execute(text(create_coverage))
        conn.execute(text(create_auth_codes))
        conn.execute(text(alter_reports))
        conn.execute(text(fk_reports))
        conn.execute(text(migrate_local_leaders_cols))

        ok = conn.execute(text("SELECT to_regclass('local_leaders') IS NOT NULL AS ok;")).mappings().first()
        if not ok or not bool(ok.get("ok", False)):
            raise RuntimeError("local_leaders table still missing after creation attempt.")

    print("OK: local leader tables/columns are present.")


if __name__ == "__main__":
    main()

