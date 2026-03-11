import json
from pathlib import Path
from typing import Any, Dict, Optional

from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from app.models.ml_prediction import MLPrediction
from app.models.report import Report
from app.models.device import Device


ROOT = Path(__file__).resolve().parents[2] / "musanze"
MODEL_PATH = ROOT / "TrustBond.joblib"
META_PATH = ROOT / "TrustBond.json"

_MODEL = None
_META: Optional[Dict[str, Any]] = None


def _load_model_and_meta():
    """Lazy-load the trained XGBoost pipeline and metadata."""
    global _MODEL, _META
    if _MODEL is not None and _META is not None:
        return _MODEL, _META

    if not MODEL_PATH.exists() or not META_PATH.exists():
        return None, None

    _MODEL = joblib.load(MODEL_PATH)
    _META = json.loads(META_PATH.read_text(encoding="utf-8"))
    return _MODEL, _META


def _bucket_time_of_day(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    hour = dt.hour
    if 0 <= hour < 6:
        return "night"
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "day"
    return "evening"


def _build_feature_row(
    report: Report,
    device: Device,
    evidence_count: int,
    feature_columns: list[str],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    reported_at: Optional[datetime] = getattr(report, "reported_at", None)
    if reported_at is not None and reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=timezone.utc)

    time_of_day = _bucket_time_of_day(reported_at)

    description = getattr(report, "description", None) or ""
    description_length = len(description)

    latitude = getattr(report, "latitude", None)
    longitude = getattr(report, "longitude", None)
    gps_accuracy = getattr(report, "gps_accuracy", None)
    movement_speed = getattr(report, "movement_speed", None)
    was_stationary = getattr(report, "was_stationary", None)

    # Device stats from DB (see devices table)
    total_reports = getattr(device, "total_reports", None) or 0
    trusted_reports = getattr(device, "trusted_reports", None) or 0
    flagged_reports = getattr(device, "flagged_reports", None) or 0
    spam_flags = getattr(device, "spam_flags", None) or 0
    device_trust_score = getattr(device, "device_trust_score", None)

    confirmation_rate = float(trusted_reports) / float(total_reports) if total_reports > 0 else 0.0
    spam_flag_count = spam_flags or flagged_reports

    gps_speed_check = None
    if movement_speed is not None:
        try:
            gps_speed_check = float(movement_speed) * 3.6
        except Exception:
            gps_speed_check = None

    gps_anomaly_flag = 0
    try:
        if gps_speed_check is not None and gps_speed_check > 200:
            gps_anomaly_flag = 1
        elif gps_accuracy is not None and float(gps_accuracy) > 200:
            gps_anomaly_flag = 1
    except Exception:
        gps_anomaly_flag = 0

    future_timestamp_flag = 0
    if reported_at is not None and reported_at > now:
        future_timestamp_flag = 1

    # Basic network_type – if the reports table has a column, use it; otherwise default to "mobile"
    network_type = getattr(report, "network_type", None) or "mobile"

    # Whether we have at least one live-capture evidence – for now we approximate with "evidence_count > 0"
    has_live_capture = 1 if evidence_count > 0 else 0

    # Rule-engine status already computed on the report
    rule_status = getattr(report, "rule_status", None)
    is_flagged = getattr(report, "is_flagged", None)

    # Build a complete feature row covering all expected columns (fill unknowns with None/defaults)
    row: Dict[str, Any] = {}
    for col in feature_columns:
        if col == "latitude":
            row[col] = latitude
        elif col == "longitude":
            row[col] = longitude
        elif col == "sector":
            row[col] = None
        elif col == "cell":
            row[col] = None
        elif col == "village":
            row[col] = None
        elif col == "sector_id":
            row[col] = None
        elif col == "cell_id":
            row[col] = None
        elif col == "village_id":
            row[col] = None
        elif col == "incident_type_id":
            row[col] = getattr(report, "incident_type_id", None)
        elif col == "incident_type_name":
            it = getattr(report, "incident_type", None)
            row[col] = getattr(it, "type_name", None) if it is not None else None
        elif col == "gps_accuracy":
            row[col] = gps_accuracy
        elif col == "motion_level":
            row[col] = getattr(report, "motion_level", None)
        elif col == "movement_speed":
            row[col] = movement_speed
        elif col == "was_stationary":
            row[col] = was_stationary
        elif col == "evidence_count":
            row[col] = evidence_count
        elif col == "has_live_capture":
            row[col] = has_live_capture
        elif col == "time_of_day":
            row[col] = time_of_day
        elif col == "reported_at":
            row[col] = reported_at.isoformat() if reported_at is not None else None
        elif col == "description_length":
            row[col] = description_length
        elif col == "network_type":
            row[col] = network_type
        elif col == "device_total_reports":
            row[col] = total_reports
        elif col == "device_trusted_reports":
            row[col] = trusted_reports
        elif col == "device_flagged_reports":
            row[col] = flagged_reports
        elif col == "device_trust_score":
            row[col] = float(device_trust_score) if device_trust_score is not None else None
        elif col == "confirmation_rate":
            row[col] = confirmation_rate
        elif col == "spam_flag_count":
            row[col] = spam_flag_count
        elif col == "rule_status":
            row[col] = rule_status
        elif col == "is_flagged":
            row[col] = is_flagged
        elif col == "gps_speed_check":
            row[col] = gps_speed_check
        elif col == "gps_anomaly_flag":
            row[col] = gps_anomaly_flag
        elif col == "future_timestamp_flag":
            row[col] = future_timestamp_flag
        else:
            # Unknown column – leave as None so the pipeline can handle it if needed
            row[col] = None

    return row


def score_report_credibility(
    db: Session,
    report: Report,
    device: Device,
    evidence_count: int,
) -> None:
    """
    Run the trained XGBoost credibility model for a single report, and persist
    the result into ml_predictions. Safe to call from API code; failures are
    swallowed so they don't break report submission.
    """
    try:
        model, meta = _load_model_and_meta()
        if model is None or meta is None:
            return

        feature_columns = meta.get("feature_columns", [])
        if not feature_columns:
            return

        row = _build_feature_row(report, device, evidence_count, feature_columns)
        X = pd.DataFrame([row], columns=feature_columns)

        # predict_proba returns [[p_fake, p_real]]
        proba = model.predict_proba(X)[0]
        prob_real = float(proba[1])

        best_threshold = float(meta.get("best_threshold", 0.5))

        # Map probability to label bands around the tuned threshold
        if prob_real >= best_threshold + 0.2:
            prediction_label = "likely_real"
        elif prob_real >= best_threshold - 0.1:
            prediction_label = "suspicious"
        else:
            prediction_label = "fake"

        trust_score_pct = prob_real * 100.0

        prediction = MLPrediction(
            prediction_id=uuid4(),
            report_id=report.report_id,
            trust_score=Decimal(f"{trust_score_pct:.2f}"),
            prediction_label=prediction_label,
            model_version=meta.get("model_version", "report_credibility_xgb_v1"),
            model_type="xgboost",
            confidence=Decimal(f"{prob_real:.3f}"),
            is_final=True,
            explanation=None,  # placeholder; can be filled with SHAP/feature attributions later
            processing_time=None,
        )
        db.add(prediction)
        # Mark when features were extracted for this report
        report.features_extracted_at = datetime.now(timezone.utc)
    except Exception:
        # Fail silently; this is an enhancement, not critical path
        return

