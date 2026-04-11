import json
from pathlib import Path
from typing import Any, Dict, Optional

from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal

import joblib
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ml_prediction import MLPrediction
from app.models.report import Report
from app.models.device import Device
from app.models.system_config import SystemConfig


ROOT = Path(__file__).resolve().parents[2] / "musanze"
MODEL_PATH = ROOT / "TrustBond.joblib"
META_PATH = ROOT / "TrustBond.json"

_MODEL = None
_META: Optional[Dict[str, Any]] = None


def _json_safe(value: Any) -> Any:
    """
    Convert common non-JSON types (Decimal, datetime, UUID) into JSON-safe values.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        # keep timezone info if present
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    # UUIDs are safe as strings
    try:
        from uuid import UUID as _UUID

        if isinstance(value, _UUID):
            return str(value)
    except Exception:
        pass
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_trust_formula(db: Session) -> Dict[str, float]:
    """
    Load trust score weights from system_config.trust_score.formula when available.
    Expected JSON:
      {"history":0.3,"spam_penalty":0.2,"confirmation_rate":0.4,"location_diversity":0.1}
    """
    default = {
        "history": 0.35,
        "spam_penalty": 0.20,
        "confirmation_rate": 0.35,
        "location_diversity": 0.10,
    }
    try:
        row = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == "trust_score.formula")
            .first()
        )
        cfg = row.config_value if row and isinstance(row.config_value, dict) else {}
        merged: Dict[str, float] = {}
        for k, v in default.items():
            raw = cfg.get(k, v)
            try:
                merged[k] = max(0.0, float(raw))
            except Exception:
                merged[k] = v
        s = sum(merged.values())
        if s <= 0:
            return default
        return {k: (val / s) for k, val in merged.items()}
    except Exception:
        return default


def compute_trust_score(
    *,
    ml_avg: Optional[float],
    confirmation_rate: float,
    spam_signal: float,
    location_diversity: float,
    weights: Dict[str, float],
) -> float:
    """Central trust score computation (0..100) used for device trust updates."""
    history_component = ((ml_avg if ml_avg is not None else 50.0) / 100.0)
    history_component = max(0.0, min(1.0, history_component))
    conf_component = max(0.0, min(1.0, confirmation_rate))
    spam_component = 1.0 - max(0.0, min(1.0, spam_signal / 10.0))
    diversity_component = max(0.0, min(1.0, location_diversity))

    score_0_1 = (
        weights.get("history", 0.0) * history_component
        + weights.get("confirmation_rate", 0.0) * conf_component
        + weights.get("spam_penalty", 0.0) * spam_component
        + weights.get("location_diversity", 0.0) * diversity_component
    )
    return max(0.0, min(100.0, score_0_1 * 100.0))


def get_effective_trust_formula(db: Session) -> Dict[str, Any]:
    """
    Expose normalized trust formula weights and raw DB config for admin visibility.
    """
    raw_config: Dict[str, Any] = {}
    try:
        row = (
            db.query(SystemConfig)
            .filter(SystemConfig.config_key == "trust_score.formula")
            .first()
        )
        if row and isinstance(row.config_value, dict):
            raw_config = row.config_value
    except Exception:
        raw_config = {}

    normalized = _load_trust_formula(db)
    return {
        "config_key": "trust_score.formula",
        "raw": _json_safe(raw_config),
        "normalized": _json_safe(normalized),
        "sum_normalized": round(sum(normalized.values()), 6),
    }


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


def _compute_trust_factors(db: Session, report: Report, device: Device, evidence_count: int, prob_real: float) -> Dict[str, Any]:
    """Calculate granular heuristics explaining the report's credibility."""
    factors: Dict[str, Any] = {}
    
    # 1. Content Score (0-100)
    desc_len = len(report.description or "")
    desc_score = min(100.0, (desc_len / 100.0) * 50.0) # Up to 50 pts for 100+ chars
    ev_score = min(100.0, evidence_count * 25.0)       # Up to 50 pts for 2+ evidence files
    content_score = min(100.0, desc_score + ev_score)
    factors["content_score"] = round(content_score, 1)

    # 2. Location Match Score (0-100)
    # Penalize if movement_speed contradicts gps accuracy or is physically impossible
    loc_score = 100.0
    try:
        if report.movement_speed is not None and float(report.movement_speed) * 3.6 > 200:
            loc_score -= 80.0
        if report.gps_accuracy is not None and float(report.gps_accuracy) > 200:
            loc_score -= 30.0
    except Exception:
        pass
    factors["location_score"] = round(max(0.0, loc_score), 1)

    # 3. Cluster Confirmation Score (0-100)
    # Is this report near a confirmed hotspot of the same type?
    cluster_score = 0.0
    try:
        from app.models.hotspot import Hotspot
        lat = float(report.latitude)
        lon = float(report.longitude)
        hotspot = db.query(Hotspot).filter(
            Hotspot.incident_type_id == report.incident_type_id,
            Hotspot.center_lat.between(lat - 0.02, lat + 0.02),
            Hotspot.center_long.between(lon - 0.02, lon + 0.02)
        ).first()
        if hotspot:
            cluster_score = 80.0
            if getattr(hotspot, "risk_level", "") in ["high", "critical"]:
                cluster_score = 100.0
    except Exception:
        pass
    factors["cluster_score"] = round(cluster_score, 1)

    # 4. User Behavior Score (0-100)
    behavior_score = float(getattr(device, "device_trust_score", 50.0) or 50.0)
    factors["user_behavior_score"] = round(behavior_score, 1)

    # 5. Coordinated False Alerts Penalty (0-100)
    coordination_penalty = 0.0
    try:
        from datetime import timedelta
        lat = float(report.latitude)
        lon = float(report.longitude)
        recent_cutoff = (report.reported_at or datetime.now(timezone.utc)) - timedelta(minutes=15)
        # Check if multiple other devices reported the exact same incident type recently in the same area
        burst_count = db.query(Report).filter(
            Report.incident_type_id == report.incident_type_id,
            Report.device_id != report.device_id,
            Report.reported_at >= recent_cutoff,
            Report.latitude.between(lat - 0.005, lat + 0.005),
            Report.longitude.between(lon - 0.005, lon + 0.005)
        ).count()
        if burst_count > 5:
            # If a sudden burst comes from different devices in a tiny area very fast, penalize if ML says it's suspicious
            if prob_real < 0.5:
                coordination_penalty = min(100.0, burst_count * 10.0)
    except Exception:
        pass
    factors["coordination_penalty"] = round(coordination_penalty, 1)
    # 6. Community Votes Modifier
    community_net = 0
    fv = getattr(report, "feature_vector", None)
    if isinstance(fv, dict):
        votes = fv.get("community_votes", {})
        real_votes = sum(1 for v in votes.values() if v == "real")
        false_votes = sum(1 for v in votes.values() if v == "false")
        community_net = real_votes - false_votes
    factors["community_net_votes"] = community_net

    return factors


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

        trust_score_pct = prob_real * 100.0
        
        # Apply anti-spam / coordination penalty before community votes
        factors = _compute_trust_factors(db, report, device, evidence_count, prob_real)
        coord_penalty = float(factors.get("coordination_penalty", 0.0) or 0.0)
        if coord_penalty > 0:
            # coord_penalty is already 0-100; temper it so ML still has signal.
            trust_score_pct = max(0.0, trust_score_pct - (coord_penalty * 0.5))

        # Apply Community Votes Modifier
        community_net = factors.get("community_net_votes", 0)
        if community_net > 0:
            trust_score_pct = min(100.0, trust_score_pct + (community_net * 5.0))
        elif community_net < 0:
            trust_score_pct = max(0.0, trust_score_pct + (community_net * 10.0))

        # Re-evaluate labels based on final trust_score_pct
        if trust_score_pct >= 85.0:
            prediction_label = "likely_real"
        elif trust_score_pct >= 60.0:
            prediction_label = "suspicious"
        elif trust_score_pct >= 30.0:
            prediction_label = "uncertain"
        else:
            prediction_label = "fake"
        

        prediction = MLPrediction(
            prediction_id=uuid4(),
            report_id=report.report_id,
            trust_score=Decimal(f"{trust_score_pct:.2f}"),
            prediction_label=prediction_label,
            model_version=meta.get("model_version", "report_credibility_xgb_v1"),
            model_type="xgboost",
            confidence=Decimal(f"{prob_real:.3f}"),
            is_final=True,
            explanation=factors,  # Store the explainability breakdown here
            processing_time=None,
        )
        db.add(prediction)
        # Mark when features were extracted for this report
        report.features_extracted_at = datetime.now(timezone.utc)
    except Exception:
        # Fail silently; this is an enhancement, not critical path
        return


def update_device_ml_aggregates(
    db: Session,
    device: Device,
    *,
    window: int = 30,
) -> None:
    """
    Recompute device-level aggregates derived from ML + behavior and persist them
    on the device row.

    Updates:
    - device.device_trust_score (blended ML + behavioral signals)
    - device.is_blacklisted / device.blacklist_reason (heuristic thresholds)
    - device.metadata_json (stores ML breakdown + last update timestamps)
    """
    try:
        # Pull recent final predictions for reports submitted by this device
        preds = (
            db.query(MLPrediction)
            .join(Report, MLPrediction.report_id == Report.report_id)
            .filter(Report.device_id == device.device_id)
            .filter(MLPrediction.trust_score.isnot(None))
            .order_by(MLPrediction.evaluated_at.desc().nullslast())
            .limit(window)
            .all()
        )

        ml_scores: list[float] = []
        confs: list[float] = []
        dist = {"likely_real": 0, "suspicious": 0, "uncertain": 0, "fake": 0}  # FIXED: Added "uncertain"
        model_versions: set[str] = set()
        last_pred_at: Optional[datetime] = None
        last_conf: Optional[float] = None

        for p in preds:
            try:
                if p.trust_score is not None:
                    ml_scores.append(float(p.trust_score))
            except Exception:
                pass
            try:
                if getattr(p, "confidence", None) is not None:
                    c = float(p.confidence)
                    confs.append(c)
                    if last_conf is None:
                        last_conf = c
            except Exception:
                pass
            label = (p.prediction_label or "").lower()
            if label in dist:
                dist[label] += 1
            if p.model_version:
                model_versions.add(str(p.model_version))
            if last_pred_at is None and getattr(p, "evaluated_at", None) is not None:
                last_pred_at = p.evaluated_at

        ml_avg = sum(ml_scores) / len(ml_scores) if ml_scores else None
        conf_avg = sum(confs) / len(confs) if confs else None
        total_preds = sum(dist.values())
        fake_rate = (dist["fake"] / total_preds) if total_preds else 0.0
        suspicious_rate = ((dist["suspicious"] + dist["uncertain"]) / total_preds) if total_preds else 0.0  # FIXED: Include uncertain

        # Behavioral score: confirmation rate - spam penalty (0..100)
        total_reports = float(getattr(device, "total_reports", 0) or 0)
        trusted_reports = float(getattr(device, "trusted_reports", 0) or 0)
        spam_flags = float(getattr(device, "spam_flags", 0) or 0)
        flagged_reports = float(getattr(device, "flagged_reports", 0) or 0)

        confirm_rate = (trusted_reports / total_reports) if total_reports > 0 else 0.0
        spam_signal = spam_flags + flagged_reports
        behavior_score = max(0.0, min(100.0, (confirm_rate * 100.0) - (spam_signal * 2.5)))

        # Location diversity from recent reports (distinct villages / recent reports)
        recent_reports = (
            db.query(Report.village_location_id)
            .filter(Report.device_id == device.device_id)
            .order_by(Report.reported_at.desc())
            .limit(window)
            .all()
        )
        total_recent = len(recent_reports)
        distinct_villages = len({v for (v,) in recent_reports if v is not None})
        location_diversity = (distinct_villages / total_recent) if total_recent > 0 else 0.0

        weights = _load_trust_formula(db)
        blended = compute_trust_score(
            ml_avg=float(ml_avg) if ml_avg is not None else None,
            confirmation_rate=confirm_rate,
            spam_signal=spam_signal,
            location_diversity=location_diversity,
            weights=weights,
        )

        # Clamp 0..100 and persist
        blended = max(0.0, min(100.0, blended))
        if hasattr(device, "device_trust_score"):
            device.device_trust_score = Decimal(f"{blended:.2f}")

        # Heuristic blacklist from ML rates and behavior
        # (Keep "ban" as explicit admin action; blacklist is advisory/system-driven.)
        if hasattr(device, "is_blacklisted"):
            should_blacklist = False
            reason = None
            if fake_rate >= 0.6 and total_preds >= 5:
                should_blacklist = True
                reason = "ml_high_fake_rate"
            elif ml_avg is not None and float(ml_avg) < 20 and total_preds >= 5:
                should_blacklist = True
                reason = "ml_low_trust_average"
            elif spam_signal >= 10:
                should_blacklist = True
                reason = "high_spam_signal"

            device.is_blacklisted = bool(should_blacklist)
            if hasattr(device, "blacklist_reason"):
                device.blacklist_reason = reason

        # Persist breakdown to metadata JSONB (non-identifying)
        meta = getattr(device, "metadata_json", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        meta["ml"] = {
            "window": window,
            "avg_trust_score": float(ml_avg) if ml_avg is not None else None,
            "distribution": dist,
            "fake_rate": round(fake_rate, 4),
            "suspicious_rate": round(suspicious_rate, 4),
            "model_versions": sorted(model_versions),
            "last_prediction_at": last_pred_at.isoformat() if last_pred_at else None,
            "avg_confidence": round(float(conf_avg), 4) if conf_avg is not None else None,
            "last_confidence": round(float(last_conf), 4) if last_conf is not None else None,
        }
        meta["behavior"] = {
            "confirmation_rate": round(confirm_rate, 4),
            "behavior_score": round(behavior_score, 2),
            "spam_signal": int(spam_signal),
            "location_diversity": round(location_diversity, 4),
        }
        meta["trust_formula"] = {
            "weights": _json_safe(weights),
            "computed_score": round(blended, 2),
        }
        meta["last_aggregate_update_at"] = datetime.now(timezone.utc).isoformat()
        device.metadata_json = _json_safe(meta)
    except Exception:
        # Best-effort; don't block request paths
        return


# API Functions for ML endpoints
def get_report_prediction(db: Session, report_id: str, device_id: str):
    """Get ML prediction for a specific report"""
    # Verify the report belongs to the device
    report = db.query(Report).filter(
        Report.report_id == report_id,
        Report.device_id == device_id
    ).first()
    
    if not report:
        return None
    
    # Get latest ML prediction
    prediction = db.query(MLPrediction).filter(
        MLPrediction.report_id == report_id
    ).order_by(MLPrediction.evaluated_at.desc()).first()
    
    return prediction


def get_home_insights(db: Session):
    """Get ML insights for home dashboard"""
    total_reports = db.query(Report).count()
    
    # Get prediction counts - FIXED: Include uncertain
    likely_real = db.query(MLPrediction).filter(
        MLPrediction.prediction_label == "likely_real"
    ).count()
    
    suspicious = db.query(MLPrediction).filter(
        MLPrediction.prediction_label == "suspicious"
    ).count()
    
    uncertain = db.query(MLPrediction).filter(
        MLPrediction.prediction_label == "uncertain"
    ).count()  # FIXED: Added uncertain count
    
    fake = db.query(MLPrediction).filter(
        MLPrediction.prediction_label == "fake"
    ).count()
    
    # Calculate average trust score
    avg_score = db.query(MLPrediction).filter(
        MLPrediction.trust_score.isnot(None)
    ).with_entities(
        func.avg(MLPrediction.trust_score)
    ).scalar()
    
    return {
        "total_reports": total_reports,
        "likely_real_count": likely_real,
        "suspicious_count": suspicious,
        "uncertain_count": uncertain,  # FIXED: Added uncertain
        "fake_count": fake,
        "average_trust_score": float(avg_score) if avg_score else None
    }


def get_device_ml_stats(db: Session, device_id: str):
    """Get ML statistics for a specific device"""
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        return None
    
    # Get all reports for this device
    reports = db.query(Report).filter(Report.device_id == device_id).all()
    report_ids = [r.report_id for r in reports]
    
    # Get predictions for these reports (recent first)
    predictions = []
    if report_ids:
        predictions = (
            db.query(MLPrediction)
            .filter(MLPrediction.report_id.in_(report_ids))
            .order_by(MLPrediction.evaluated_at.desc().nullslast())
            .all()
        )

    # Calculate distribution - FIXED: Include uncertain
    distribution = {"likely_real": 0, "suspicious": 0, "uncertain": 0, "fake": 0}
    for pred in predictions:
        label = (pred.prediction_label or "").lower()
        if label in distribution:
            distribution[label] += 1

    meta = getattr(device, "metadata_json", None)
    ml_meta = meta.get("ml") if isinstance(meta, dict) else None
    behavior_meta = meta.get("behavior") if isinstance(meta, dict) else None

    return {
        "device_id": str(device_id),
        "total_reports": int(getattr(device, "total_reports", None) or len(reports) or 0),
        "trust_score": float(device.device_trust_score) if device.device_trust_score is not None else None,
        "prediction_distribution": distribution,
        "last_prediction_at": (
            predictions[0].evaluated_at.isoformat()
            if predictions and getattr(predictions[0], "evaluated_at", None)
            else (ml_meta.get("last_prediction_at") if isinstance(ml_meta, dict) else None)
        ),
        "ml": ml_meta if isinstance(ml_meta, dict) else None,
        "behavior": behavior_meta if isinstance(behavior_meta, dict) else None,
    }

