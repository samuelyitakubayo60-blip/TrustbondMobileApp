from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import joinedload

# Ensure backend root is importable when running as a script.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api.v1.reports import _compose_ai_evidence_description, _compose_ai_verification_reason
from app.core.report_review import resolve_ml_prediction_for_report
from app.database import SessionLocal
from app.models.report import Report


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def main() -> None:
    db = SessionLocal()
    try:
        reports = (
            db.query(Report)
            .options(
                joinedload(Report.incident_type),
                joinedload(Report.ml_predictions),
                joinedload(Report.evidence_files),
            )
            .all()
        )

        updated = 0
        evidence_updated = 0
        reason_updated = 0

        for report in reports:
            feature_vector = _safe_dict(report.feature_vector)
            evidence_validations = _safe_list(feature_vector.get("evidence_validations"))
            semantic_alignment = feature_vector.get("semantic_alignment")
            if not isinstance(semantic_alignment, dict):
                semantic_alignment = None

            incident_type_name = getattr(getattr(report, "incident_type", None), "type_name", None)
            context_tags = _safe_list(report.context_tags)

            touched = False
            evidence_file_count = len(getattr(report, "evidence_files", []) or [])
            evidence_media_types = [
                str(getattr(ev, "file_type", "")).strip()
                for ev in (getattr(report, "evidence_files", []) or [])
                if str(getattr(ev, "file_type", "")).strip()
            ]
            report.ai_evidence_description = _compose_ai_evidence_description(
                evidence_validations,
                incident_type_name=incident_type_name,
                reporter_description=report.description,
                context_tags=context_tags,
                evidence_file_count=evidence_file_count,
                evidence_media_types=evidence_media_types,
            )
            evidence_updated += 1
            touched = True

            # Always refresh decision reason to keep wording consistent with current logic.
            ml_prediction = resolve_ml_prediction_for_report(report)
            trust_score = None
            if ml_prediction is not None and getattr(ml_prediction, "trust_score", None) is not None:
                trust_score = float(ml_prediction.trust_score)

            report.ai_verification_reason = _compose_ai_verification_reason(
                verification_status=report.verification_status,
                rule_status=report.rule_status,
                is_flagged=report.is_flagged,
                flag_reason=report.flag_reason,
                ml_prediction_label=(
                    getattr(ml_prediction, "prediction_label", None) if ml_prediction is not None else None
                ),
                trust_score=trust_score,
                semantic_alignment=semantic_alignment,
                incident_type_name=incident_type_name,
                reporter_description=report.description,
                context_tags=context_tags,
            )
            reason_updated += 1
            touched = True

            if touched:
                updated += 1

        db.commit()
        print(
            f"Backfill complete: updated_reports={updated} "
            f"ai_evidence_description={evidence_updated} ai_verification_reason={reason_updated}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
