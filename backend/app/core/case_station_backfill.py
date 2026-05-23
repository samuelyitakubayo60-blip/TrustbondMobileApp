"""Backfill cases.station_id from report locations and cell coverage."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.station_assignment import resolve_station_id
from app.models.case import Case, CaseReport
from app.models.report import Report

_log = logging.getLogger(__name__)


def backfill_case_station_ids(db: Session, *, limit: int = 3000) -> dict:
    """
    Set station_id on cases that lack it, using case coordinates or linked reports.
    """
    cases = (
        db.query(Case)
        .filter(Case.station_id.is_(None))
        .order_by(Case.created_at.desc())
        .limit(limit)
        .all()
    )
    updated = 0
    for case in cases:
        sid = None
        if case.latitude is not None and case.longitude is not None:
            sid = resolve_station_id(
                db,
                latitude=float(case.latitude),
                longitude=float(case.longitude),
                location_id=case.location_id,
            )
        if sid is None:
            link = (
                db.query(Report)
                .join(CaseReport, CaseReport.report_id == Report.report_id)
                .filter(CaseReport.case_id == case.case_id)
                .first()
            )
            if link:
                sid = resolve_station_id(
                    db,
                    latitude=float(link.latitude) if link.latitude is not None else None,
                    longitude=float(link.longitude) if link.longitude is not None else None,
                    village_location_id=link.village_location_id,
                    location_id=link.location_id,
                )
                if sid is not None:
                    link.handling_station_id = sid
        if sid is not None:
            case.station_id = sid
            updated += 1
    if updated:
        db.commit()
    _log.info("Case station backfill: updated %s of %s scanned", updated, len(cases))
    return {"scanned": len(cases), "updated": updated}
