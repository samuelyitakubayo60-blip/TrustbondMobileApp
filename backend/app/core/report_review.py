"""
Report verification utilities: ML prediction label resolution and trust scoring.
Trust display: prefer latest ML prediction trust, else device aggregate (same as list API).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.models.report import Report


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
    derive a label using standard trust bands (70 / 45 thresholds).
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
    UI shows (`resolve_display_trust_score`: same headline score as police report list)
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
    """Per-report trust for police list/dashboard — delegates to scorecard headline resolver."""
    from app.core.report_list_trust import resolve_report_list_trust_score

    return resolve_report_list_trust_score(report)
