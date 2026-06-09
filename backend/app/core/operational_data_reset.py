"""Clear operational data while preserving reference / configuration tables."""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)

# Kept intact: users, geography, leaders, incident taxonomy, system settings.
TABLES_PRESERVED = (
    "police_users",
    "incident_types",
    "locations",
    "stations",
    "station_coverage_cells",
    "local_leaders",
    "local_leader_coverage_locations",
    "system_config",
    "special_assignment_units",
    "alembic_version",
)

# Deleted in dependency-safe order (children before parents).
TABLES_TO_CLEAR: tuple[str, ...] = (
    "deployment_decisions",
    "suspect_victim_tracking",
    "hotspot_reports",
    "hotspot_events",
    "case_reports",
    "ml_predictions",
    "evidence_files",
    "report_assignments",
    "notifications",
    "audit_logs",
    "reports",
    "cases",
    "hotspots",
    "devices",
    "user_sessions",
    "mfa_codes",
    "password_reset_codes",
    "local_leader_auth_codes",
)

_OPTIONAL_TABLES = frozenset({"suspect_victim_tracking", "deployment_decisions"})


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :name
            LIMIT 1
            """
        ),
        {"name": table},
    ).first()
    return row is not None


def count_operational_rows(db: Session) -> dict[str, int]:
    """Return row counts for tables that will be cleared."""
    counts: dict[str, int] = {}
    for table in TABLES_TO_CLEAR:
        if not _table_exists(db, table):
            counts[table] = 0
            continue
        counts[table] = int(
            db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        )
    return counts


def clear_operational_data(db: Session, *, dry_run: bool = False) -> dict[str, int]:
    """
    Remove reports, hotspots, devices, sessions, audit logs, and related rows.
    Reference data (users, locations, stations, leaders, incident types, config) is untouched.
    """
    before = count_operational_rows(db)
    if dry_run:
        return before

    cleared: dict[str, int] = {}
    for table in TABLES_TO_CLEAR:
        if not _table_exists(db, table):
            if table not in _OPTIONAL_TABLES:
                _log.warning("Expected table missing (skipped): %s", table)
            cleared[table] = 0
            continue
        try:
            result = db.execute(text(f"DELETE FROM {table}"))
            cleared[table] = int(result.rowcount or 0)
        except Exception as exc:
            db.rollback()
            raise RuntimeError(f"Failed to clear table {table}: {exc}") from exc

    # Reset serial sequences for emptied tables (best-effort).
    _restart_serial_sequences(db, TABLES_TO_CLEAR)
    db.commit()
    _log.info("Operational data cleared: %s", cleared)
    return cleared


def _restart_serial_sequences(db: Session, tables: Iterable[str]) -> None:
    for table in tables:
        if not _table_exists(db, table):
            continue
        try:
            db.execute(
                text(
                    """
                    SELECT setval(
                        pg_get_serial_sequence(:tbl, a.attname),
                        1,
                        false
                    )
                    FROM pg_attribute a
                    JOIN pg_class c ON a.attrelid = c.oid
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    WHERE n.nspname = 'public'
                      AND c.relname = :tbl
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                      AND pg_get_serial_sequence(:tbl, a.attname) IS NOT NULL
                    LIMIT 1
                    """
                ),
                {"tbl": table},
            )
        except Exception:
            pass
