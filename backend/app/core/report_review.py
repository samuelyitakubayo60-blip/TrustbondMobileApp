"""
Single source of truth for police-facing report review state.

- `needs_police_review_clause()` must match dashboard `pending` / `pending_review` counts
  in `app.api.v1.stats.get_dashboard_stats`.
- Trust display: prefer latest ML prediction trust, else device aggregate (same as list API).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, or_

from app.models.report import Report


def needs_police_review_clause():
    """SQLAlchemy filter: reports that still need police/verification attention."""
    return or_(
        Report.status == "pending",
        and_(
            Report.verification_status.in_(["pending", "under_review"]),
            or_(
                Report.status.is_(None),
                ~Report.status.in_(["verified", "flagged", "rejected"]),
            ),
        ),
    )


def apply_rules_to_prediction_label(report: Any, raw_label: Optional[str]) -> Optional[str]:
    """
    Match list/detail APIs: categorical label reflects rule state (no numeric caps here).
    """
    label = (raw_label or "").strip().lower() or None
    if label == "unknown":
        label = None
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))
    if rule_status == "rejected":
        return "fake"
    if rule_status == "flagged" or is_flagged:
        if label in (None, "likely_real"):
            return "suspicious"
    return label


def prediction_confidence_for_display(prediction: Any, raw_db_label: Optional[str]) -> Optional[float]:
    """
    MLPrediction.confidence is often max class probability (~1.0), which reads as
    '100% sure' next to a modest trust score. Omit when it adds no information.
    """
    if prediction is None or getattr(prediction, "confidence", None) is None:
        return None
    try:
        c = float(prediction.confidence)
    except (TypeError, ValueError):
        return None
    if not (c == c):
        return None
    cleaned = (raw_db_label or "").strip().lower()
    if cleaned in ("", "unknown", "none") and c >= 0.9:
        return None
    if c >= 0.995:
        return None
    return c


def infer_prediction_label_from_trust_score(
    trust_score: float,
    *,
    trust_threshold: float = 70.0,
    under_review_threshold: float = 45.0,
) -> str:
    """
    When DB row has trust_score but no prediction_label (legacy / partial writes),
    derive a label using the same banding as app.utils.ml_evaluator.MLEvaluator.
    """
    if trust_score >= trust_threshold:
        return "likely_real"
    if trust_score >= under_review_threshold:
        return "suspicious"
    return "fake"


def resolve_ml_prediction_label_for_display(report: Any) -> Optional[str]:
    """
    Label for the police "AI result" column.

    Prefer stored ML prediction (or infer from that row's trust_score).
    If there is no qualifying ML row, infer from the same trust the list/detail
    UI shows (`resolve_display_trust_score`: ML trust first, else device aggregate)
    so the badge matches the trust bar (avoids "No ML" next to a 70%+ bar).
    """
    ml = resolve_ml_prediction_for_report(report)
    if ml is not None:
        raw = getattr(ml, "prediction_label", None)
        if raw is not None and str(raw).strip():
            return str(raw).strip().lower()
        ts = getattr(ml, "trust_score", None)
        if ts is not None:
            try:
                return infer_prediction_label_from_trust_score(float(ts))
            except (TypeError, ValueError):
                pass
        if bool(getattr(ml, "is_final", False)):
            return "uncertain"
    display_ts = resolve_display_trust_score(report)
    if display_ts is not None:
        try:
            return infer_prediction_label_from_trust_score(float(display_ts))
        except (TypeError, ValueError):
            pass
    return None


def resolve_ml_prediction_for_report(report: Any):
    preds = []
    if getattr(report, "ml_predictions", None):
        preds = [
            p
            for p in report.ml_predictions
            if p.is_final or p.trust_score is not None or p.prediction_label is not None
        ]
        if preds:
            # Prioritize predictions with actual labels over those without
            preds.sort(
                key=lambda p: (
                    # First priority: is_final
                    bool(p.is_final),
                    # Second priority: has prediction_label (not None/empty)
                    bool(p.prediction_label and p.prediction_label.strip() and p.prediction_label != "unknown"),
                    # Third priority: has trust_score
                    bool(p.trust_score is not None),
                    # Fourth priority: most recent
                    p.evaluated_at or datetime.min.replace(tzinfo=timezone.utc)
                ),
                reverse=True,
            )
            return preds[0]
    return None


def resolve_display_trust_score(report: Any) -> Optional[float]:
    """Per-report trust for UI: ML trust first, else device trust (matches list endpoint)."""
    ml_prediction = resolve_ml_prediction_for_report(report)
    if ml_prediction is not None and ml_prediction.trust_score is not None:
        return float(ml_prediction.trust_score)
    if getattr(report, "device", None) and report.device and report.device.device_trust_score is not None:
        return float(report.device.device_trust_score)
    return None
