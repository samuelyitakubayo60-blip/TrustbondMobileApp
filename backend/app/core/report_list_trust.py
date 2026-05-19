"""Trust score shown on police report list — shared with dashboard recent reports."""

from __future__ import annotations

from typing import Any, Optional

from app.models.report import Report
from app.core.report_review import resolve_ml_prediction_for_report


def _community_votes_from_report(report: Report) -> dict[str, int]:
    community_votes = {"real": 0, "false": 0, "unknown": 0}
    fv = getattr(report, "feature_vector", None)
    if isinstance(fv, dict):
        votes_dict = fv.get("community_votes", {})
        if isinstance(votes_dict, dict):
            for _device_key, v in votes_dict.items():
                k = str(v)
                if k in community_votes:
                    community_votes[k] += 1
    return community_votes


def resolve_report_list_trust_score(report: Report) -> Optional[float]:
    """
    Same number as GET /api/v1/reports list items (ReportResponse.trust_score):
    ML baseline → rule adjustment → threshold scorecard total when available.
    """
    ml_prediction = resolve_ml_prediction_for_report(report)
    trust_score: Optional[float] = None
    if ml_prediction is not None and ml_prediction.trust_score is not None:
        trust_score = float(ml_prediction.trust_score)

    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()

    # Lazy import: reports module is large; stats must not duplicate list logic.
    from app.api.v1.reports import (
        _headline_trust_score_from_factors,
        _resolve_trust_factors,
        _rule_adjusted_trust_label,
    )

    _, ml_prediction_label = _rule_adjusted_trust_label(
        report, trust_score, ml_prediction_label
    )
    trust_factors = _resolve_trust_factors(
        report,
        ml_prediction,
        evidence_count=len(getattr(report, "evidence_files", None) or []),
        community_votes=_community_votes_from_report(report),
    )
    return _headline_trust_score_from_factors(trust_factors, trust_score)
