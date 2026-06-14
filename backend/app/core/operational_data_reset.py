"""Clear operational data while preserving reference / configuration tables."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.report import Report

_log = logging.getLogger(__name__)

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

TABLES_TO_CLEAR = (
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


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :name LIMIT 1
            """
        ),
        {"name": table},
    ).first()
    return row is not None


def find_preserved_report_ids(
    db: Session,
    *,
    preserve_count: int = 2,
    preserve_tomorrow: bool = True,
) -> list[UUID]:
    """
    Keep up to `preserve_count` reports:
    1) Prefer reports dated tomorrow (UTC) — real submissions to keep across reseed.
    2) Fallback: the most recent reports by reported_at.
    """
    ids: list[UUID] = []
    if preserve_tomorrow and preserve_count > 0:
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        rows = (
            db.query(Report.report_id)
            .filter(func.date(Report.reported_at) == tomorrow)
            .order_by(Report.reported_at.desc())
            .limit(preserve_count)
            .all()
        )
        ids = [r[0] for r in rows]

    if len(ids) < preserve_count:
        existing = {str(x) for x in ids}
        rows = (
            db.query(Report.report_id)
            .order_by(Report.reported_at.desc())
            .limit(preserve_count * 3)
            .all()
        )
        for row in rows:
            if str(row[0]) in existing:
                continue
            ids.append(row[0])
            if len(ids) >= preserve_count:
                break
    return ids[:preserve_count]


def _delete_except_reports(db: Session, table: str, preserve_ids: list[str]) -> int:
    if not _table_exists(db, table):
        return 0
    if preserve_ids:
        result = db.execute(
            text(f"DELETE FROM {table} WHERE report_id::text != ALL(:pids)"),
            {"pids": preserve_ids},
        )
    else:
        result = db.execute(text(f"DELETE FROM {table}"))
    return int(result.rowcount or 0)


def clear_operational_data(
    db: Session,
    *,
    preserve_report_ids: list[UUID] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete operational rows; optional report IDs are kept (and their devices)."""
    preserve_report_ids = preserve_report_ids or []
    preserve_str = [str(x) for x in preserve_report_ids]

    if dry_run:
        counts = {}
        for table in TABLES_TO_CLEAR:
            if not _table_exists(db, table):
                counts[table] = 0
                continue
            counts[table] = int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
        return counts

    cleared: dict[str, int] = {}

    report_child_tables = (
        "deployment_decisions",
        "hotspot_reports",
        "case_reports",
        "ml_predictions",
        "evidence_files",
        "report_assignments",
    )
    for table in report_child_tables:
        cleared[table] = _delete_except_reports(db, table, preserve_str)

    if _table_exists(db, "suspect_victim_tracking"):
        cleared["suspect_victim_tracking"] = int(
            (db.execute(text("DELETE FROM suspect_victim_tracking")).rowcount or 0)
        )

    for table in ("hotspot_events", "notifications", "audit_logs"):
        if _table_exists(db, table):
            cleared[table] = int((db.execute(text(f"DELETE FROM {table}")).rowcount or 0))
        else:
            cleared[table] = 0

    if _table_exists(db, "cases"):
        case_queries = []
        if _table_exists(db, "case_reports"):
            case_queries.append("SELECT case_id::text FROM case_reports WHERE case_id IS NOT NULL")
        if _table_exists(db, "deployment_decisions"):
            case_queries.append("SELECT case_id::text FROM deployment_decisions WHERE case_id IS NOT NULL")
        
        if case_queries:
            union_str = " UNION ".join(case_queries)
            cleared["cases"] = int((db.execute(text(f"DELETE FROM cases WHERE case_id::text NOT IN ({union_str})")).rowcount or 0))
        else:
            cleared["cases"] = int((db.execute(text("DELETE FROM cases")).rowcount or 0))
    else:
        cleared["cases"] = 0

    if _table_exists(db, "hotspots"):
        if _table_exists(db, "hotspot_reports"):
            cleared["hotspots"] = int((db.execute(text("DELETE FROM hotspots WHERE hotspot_id NOT IN (SELECT hotspot_id FROM hotspot_reports WHERE hotspot_id IS NOT NULL)")).rowcount or 0))
        else:
            cleared["hotspots"] = int((db.execute(text("DELETE FROM hotspots")).rowcount or 0))
    else:
        cleared["hotspots"] = 0

    if preserve_str:
        cleared["reports"] = int(
            (
                db.execute(
                    text("DELETE FROM reports WHERE report_id::text != ALL(:pids)"),
                    {"pids": preserve_str},
                ).rowcount
                or 0
            )
        )
    else:
        cleared["reports"] = int((db.execute(text("DELETE FROM reports")).rowcount or 0))

    if _table_exists(db, "devices"):
        cleared["devices"] = int(
            (
                db.execute(
                    text(
                        "DELETE FROM devices WHERE device_id NOT IN "
                        "(SELECT DISTINCT device_id FROM reports WHERE device_id IS NOT NULL)"
                    )
                ).rowcount
                or 0
            )
        )
    else:
        cleared["devices"] = 0

    for table in ("user_sessions", "mfa_codes", "password_reset_codes", "local_leader_auth_codes"):
        if _table_exists(db, table):
            cleared[table] = int((db.execute(text(f"DELETE FROM {table}")).rowcount or 0))
        else:
            cleared[table] = 0

    db.commit()
    _log.info("Operational clear done (preserved %d reports): %s", len(preserve_str), cleared)
    return cleared
