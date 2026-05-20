#!/usr/bin/env python3
"""
Regenerate plain-language AI narratives for existing reports.

Updates:
  - reports.ai_verification_reason
  - reports.ai_evidence_description
  - feature_vector.ai_analysis_snapshot (refreshed)

Does not re-run YOLO, TrustBond scoring, or change verification_status.

Usage (from backend/):
  python scripts/regenerate_report_narratives.py --dry-run
  python scripts/regenerate_report_narratives.py
  python scripts/regenerate_report_narratives.py --limit 50
  python scripts/regenerate_report_narratives.py --report-id <uuid>
  python scripts/regenerate_report_narratives.py --include-leaders
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload, selectinload  # noqa: E402

from app.api.v1.reports import (  # noqa: E402
    _build_ai_analysis_snapshot,
    _compose_ai_evidence_description,
    _compose_ai_verification_reason,
    _description_credibility_from_report,
    _human_location_chain_from_report,
    _persist_ai_analysis_snapshot,
    _rule_adjusted_trust_label,
)
from app.core.report_review import resolve_ml_prediction_for_report  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.evidence_file import EvidenceFile  # noqa: E402
from app.models.incident_type import IncidentType  # noqa: E402
from app.models.location import Location  # noqa: E402
from app.models.ml_prediction import MLPrediction  # noqa: E402
from app.models.report import Report  # noqa: E402


def _open_db(max_attempts: int = 5):
    """Open a DB session; retry on transient SSL / network errors (e.g. Render wake-up)."""
    last_err: Optional[Exception] = None
    for attempt in range(max_attempts):
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return db
        except OperationalError as exc:
            last_err = exc
            db.close()
            if attempt >= max_attempts - 1:
                raise
            wait = min(30, 2 ** attempt)
            print(f"DB connect failed (attempt {attempt + 1}/{max_attempts}), retry in {wait}s...")
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def _report_query(db):
    return (
        db.query(Report)
        .options(
            joinedload(Report.incident_type),
            joinedload(Report.village_location).joinedload(Location.parent),
            selectinload(Report.ml_predictions),
            selectinload(Report.evidence_files),
        )
        .order_by(Report.reported_at.desc())
    )


def _regenerate_report(report: Report) -> None:
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    ml_prediction = resolve_ml_prediction_for_report(report)
    ai_trust_score: Optional[float] = None
    ai_label: Optional[str] = None
    if ml_prediction is not None and getattr(ml_prediction, "trust_score", None) is not None:
        try:
            ai_trust_score = float(ml_prediction.trust_score)
        except (TypeError, ValueError):
            ai_trust_score = None
    ai_label = getattr(ml_prediction, "prediction_label", None)
    ai_trust_score, ai_label = _rule_adjusted_trust_label(report, ai_trust_score, ai_label)

    semantic_alignment = (
        fv.get("semantic_alignment") if isinstance(fv.get("semantic_alignment"), dict) else None
    )
    scorecard = (
        fv.get("threshold_scorecard")
        if isinstance(fv.get("threshold_scorecard"), dict)
        else None
    )
    unified_validation = (
        fv.get("unified_validation")
        if isinstance(fv.get("unified_validation"), dict)
        else None
    )
    evidence_validations = (
        fv.get("evidence_validations")
        if isinstance(fv.get("evidence_validations"), list)
        else []
    )
    incident_type_name = getattr(getattr(report, "incident_type", None), "type_name", None)
    context_tags = list(getattr(report, "context_tags", None) or [])
    location_label = _human_location_chain_from_report(report)
    description_credibility = _description_credibility_from_report(report)

    report.ai_verification_reason = _compose_ai_verification_reason(
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        is_flagged=report.is_flagged,
        flag_reason=report.flag_reason,
        ml_prediction_label=ai_label,
        trust_score=ai_trust_score,
        semantic_alignment=semantic_alignment,
        incident_type_name=incident_type_name,
        reporter_description=report.description,
        context_tags=context_tags,
        unified_validation=unified_validation,
        scorecard=scorecard,
        latitude=getattr(report, "latitude", None),
        longitude=getattr(report, "longitude", None),
        gps_accuracy=getattr(report, "gps_accuracy", None),
        location_label=location_label,
        description_credibility=description_credibility,
    )
    report.ai_evidence_description = _compose_ai_evidence_description(
        evidence_validations,
        incident_type_name=incident_type_name,
        reporter_description=report.description,
        context_tags=context_tags,
        evidence_file_count=len(evidence_validations) or len(getattr(report, "evidence_files", None) or []),
        unified_validation=unified_validation,
        scorecard=scorecard,
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        is_flagged=report.is_flagged,
        flag_reason=report.flag_reason,
        ml_prediction_label=ai_label,
        trust_score=ai_trust_score,
        semantic_alignment=semantic_alignment,
        latitude=getattr(report, "latitude", None),
        longitude=getattr(report, "longitude", None),
        gps_accuracy=getattr(report, "gps_accuracy", None),
        location_label=location_label,
    )
    snapshot = _build_ai_analysis_snapshot(
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        is_flagged=report.is_flagged,
        flag_reason=report.flag_reason,
        ml_prediction_label=ai_label,
        trust_score=ai_trust_score,
        semantic_alignment=semantic_alignment,
        incident_type_name=incident_type_name,
        reporter_description=report.description,
        context_tags=context_tags,
        unified_validation=unified_validation,
        scorecard=scorecard,
        evidence_validations=evidence_validations,
        evidence_file_count=len(evidence_validations) or len(getattr(report, "evidence_files", None) or []),
        latitude=getattr(report, "latitude", None),
        longitude=getattr(report, "longitude", None),
        gps_accuracy=getattr(report, "gps_accuracy", None),
        location_label=location_label,
        description_credibility=description_credibility,
    )
    _persist_ai_analysis_snapshot(report, snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate report AI narratives in the database.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing to the database.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max reports to process.")
    parser.add_argument("--report-id", type=str, default=None, help="Single report UUID.")
    parser.add_argument(
        "--include-leaders",
        action="store_true",
        help="Also regenerate leader-submitted reports (default: skip).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Commit every N reports (default 25).",
    )
    args = parser.parse_args()

    db = _open_db()
    updated = 0
    skipped_leader = 0
    errors = 0

    try:
        query = _report_query(db)
        if args.report_id:
            try:
                rid = UUID(args.report_id.strip())
            except ValueError:
                print(f"Invalid --report-id: {args.report_id}", file=sys.stderr)
                return 1
            query = query.filter(Report.report_id == rid)
        if args.limit:
            query = query.limit(args.limit)

        reports = query.all()
        total = len(reports)
        print(f"Found {total} report(s) to process.")

        for idx, report in enumerate(reports, start=1):
            ref = getattr(report, "report_number", None) or str(report.report_id)[:8]
            if report.submitted_by_local_leader_id is not None and not args.include_leaders:
                skipped_leader += 1
                print(f"[{idx}/{total}] skip leader-submitted {ref}")
                continue

            if args.dry_run:
                print(f"[{idx}/{total}] would regenerate {ref} ({report.verification_status})")
                updated += 1
                continue

            try:
                _regenerate_report(report)
                updated += 1
                if updated % max(1, args.batch_size) == 0:
                    db.commit()
                    print(f"  committed batch ({updated} updated so far)")
            except Exception as exc:
                errors += 1
                db.rollback()
                print(f"[{idx}/{total}] ERROR {ref}: {exc}", file=sys.stderr)

        if not args.dry_run and updated > 0:
            db.commit()

        print(
            f"Done. updated={updated} skipped_leader={skipped_leader} errors={errors} dry_run={args.dry_run}"
        )
        return 1 if errors else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
