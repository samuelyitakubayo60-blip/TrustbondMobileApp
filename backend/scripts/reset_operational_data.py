#!/usr/bin/env python3
"""
Reset operational data and seed fresh demo records.

PRESERVED (not deleted):
  police_users, incident_types, locations, stations, station_coverage_cells,
  local_leaders, local_leader_coverage_locations, system_config,
  special_assignment_units

CLEARED:
  reports (+ evidence, ML predictions, assignments, case links),
  cases, hotspots, devices, notifications, audit_logs, user_sessions,
  MFA/password-reset codes, deployment_decisions

Then seeds at least 300 new reports (default), devices, cases, and recomputes hotspots.

Usage (from backend directory or container):
  python scripts/reset_operational_data.py --yes
  python scripts/reset_operational_data.py --yes --count 500
  python scripts/reset_operational_data.py --dry-run
  python scripts/reset_operational_data.py --clear-only --yes
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.hotspot_auto import create_hotspots_from_reports
from app.core.operational_data_reset import (
    TABLES_PRESERVED,
    TABLES_TO_CLEAR,
    clear_operational_data,
    count_operational_rows,
)
from app.database import SessionLocal
from simulate_reports import seed_operational_data

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reset_operational_data")


def _print_plan(counts: dict[str, int]) -> None:
    total = sum(counts.values())
    logger.info("Tables to CLEAR (%d rows total):", total)
    for table in TABLES_TO_CLEAR:
        n = counts.get(table, 0)
        if n:
            logger.info("  - %s: %d", table, n)
    logger.info("Tables PRESERVED: %s", ", ".join(TABLES_PRESERVED))


def recompute_hotspots(db) -> int:
    """Build hotspot clusters from all non-rejected seeded reports."""
    return create_hotspots_from_reports(
        db,
        analyze_all_reports=True,
        time_window_hours=8760,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear operational data and reseed TrustBond demo records.")
    parser.add_argument(
        "--count",
        type=int,
        default=300,
        help="Number of reports to seed (minimum 300). Default: 300",
    )
    parser.add_argument(
        "--devices",
        type=int,
        default=None,
        help="Number of devices to create (default: max(50, count/5))",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=45,
        help="Spread report dates over this many days (default: 45)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row counts that would be deleted; do not change data",
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Only clear operational tables; do not seed or recompute hotspots",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Skip clear step; only seed and recompute hotspots",
    )
    parser.add_argument(
        "--skip-hotspots",
        action="store_true",
        help="Do not run hotspot DBSCAN recompute after seeding",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Confirm destructive reset without interactive prompt",
    )
    args = parser.parse_args()

    if args.count < 300:
        parser.error("--count must be at least 300")

    db = SessionLocal()
    try:
        counts = count_operational_rows(db)
        _print_plan(counts)

        if args.dry_run:
            logger.info("Dry run — no changes made.")
            return 0

        if not args.seed_only:
            if not args.yes:
                answer = input(
                    "\nThis will DELETE all operational data listed above. Type RESET to continue: "
                ).strip()
                if answer != "RESET":
                    logger.info("Aborted.")
                    return 1
            cleared = clear_operational_data(db)
            logger.info("Cleared rows: %s", cleared)

        if args.clear_only:
            logger.info("Clear-only complete.")
            return 0

        stats = seed_operational_data(
            db,
            num_reports=args.count,
            num_devices=args.devices,
            days_back=args.days,
        )
        logger.info("Seeded: %s", stats)

        hotspots_created = 0
        if not args.skip_hotspots:
            hotspots_created = recompute_hotspots(db)
            logger.info("Hotspots recomputed: %d clusters", hotspots_created)

        logger.info(
            "Done. Preserved reference data; seeded %d reports, %d devices, %d cases, %d hotspots.",
            stats["reports"],
            stats["devices"],
            stats["cases"],
            hotspots_created,
        )
        return 0
    except Exception:
        db.rollback()
        logger.exception("Reset failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
