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
        "history": 0.30,
        "spam_penalty": 0.15,
        "confirmation_rate": 0.30,
        "location_diversity": 0.10,
        "location_quality": 0.15,
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


def calculate_location_score(db: Session, device_id: str, window: int = 10) -> float:
    """
    Calculate location score for a device based on GPS accuracy, consistency, and plausibility.
    Returns a score from 0.0 to 1.0.
    """
    from app.models.report import Report
    
    # Get recent reports with location data
    recent_reports = (
        db.query(Report)
        .filter(Report.device_id == device_id)
        .order_by(Report.reported_at.desc())
        .limit(window)
        .all()
    )
    
    if not recent_reports:
        return 0.5  # Neutral score for devices with no location history
    
    location_scores = []
    
    for report in recent_reports:
        report_score = 0.5  # Base score for this report
        
        # 1. GPS Accuracy Score (0.0 to 1.0)
        if report.gps_accuracy is not None:
            gps_accuracy = float(report.gps_accuracy)
            if gps_accuracy <= 10:  # Excellent GPS (≤10m)
                accuracy_score = 1.0
            elif gps_accuracy <= 30:  # Good GPS (≤30m)
                accuracy_score = 0.8
            elif gps_accuracy <= 100:  # Fair GPS (≤100m)
                accuracy_score = 0.6
            elif gps_accuracy <= 500:  # Poor GPS (≤500m)
                accuracy_score = 0.4
            else:  # Very poor GPS (>500m)
                accuracy_score = 0.2
            report_score += (accuracy_score * 0.3)  # 30% weight for GPS accuracy
        else:
            report_score += 0.1  # Small penalty for missing GPS data
        
        # 2. Location Consistency Score (0.0 to 1.0)
        if report.village_location_id is not None:
            # Check if device reports consistently from same village
            same_village_reports = sum(1 for r in recent_reports 
                                     if r.village_location_id == report.village_location_id)
            consistency_ratio = same_village_reports / len(recent_reports)
            # Reward consistency but not too much (allows for legitimate travel)
            if consistency_ratio >= 0.8:  # Very consistent
                consistency_score = 0.8
            elif consistency_ratio >= 0.5:  # Moderately consistent
                consistency_score = 1.0  # Sweet spot - not too consistent, not too random
            else:  # Very scattered
                consistency_score = 0.6
            report_score += (consistency_score * 0.3)  # 30% weight for consistency
        else:
            report_score += 0.1  # Small penalty for missing village data
        
        # 3. Movement Plausibility Score (0.0 to 1.0)
        if report.movement_speed is not None and report.was_stationary is not None:
            speed = float(report.movement_speed)
            if report.was_stationary:
                if speed <= 5:  # Reasonable speed when stationary
                    plausibility_score = 1.0
                else:
                    plausibility_score = 0.3  # Suspicious: high speed while "stationary"
            else:
                if speed <= 15:  # Walking/running speed
                    plausibility_score = 1.0
                elif speed <= 50:  # Vehicle speed
                    plausibility_score = 0.8
                elif speed <= 100:  # Fast vehicle
                    plausibility_score = 0.6
                else:  # Very high speed (suspicious)
                    plausibility_score = 0.3
            report_score += (plausibility_score * 0.4)  # 40% weight for movement plausibility
        else:
            report_score += 0.2  # Neutral score for missing movement data
        
        location_scores.append(min(1.0, report_score))
    
    # Return average location score across recent reports
    return sum(location_scores) / len(location_scores)


def compute_trust_score(
    *,
    ml_avg: Optional[float],
    confirmation_rate: float,
    spam_signal: float,
    location_diversity: float,
    location_score: float,
    weights: Dict[str, float],
) -> float:
    """Central trust score computation (0..100) used for device trust updates."""
    history_component = ((ml_avg if ml_avg is not None else 50.0) / 100.0)
    history_component = max(0.0, min(1.0, history_component))
    conf_component = max(0.0, min(1.0, confirmation_rate))
    spam_component = 1.0 - max(0.0, min(1.0, spam_signal / 10.0))
    diversity_component = max(0.0, min(1.0, location_diversity))
    location_quality_component = max(0.0, min(1.0, location_score))

    score_0_1 = (
        weights.get("history", 0.0) * history_component
        + weights.get("confirmation_rate", 0.0) * conf_component
        + weights.get("spam_penalty", 0.0) * spam_component
        + weights.get("location_diversity", 0.0) * diversity_component
        + weights.get("location_quality", 0.0) * location_quality_component
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

    # TrustBond must avoid NLP-style conclusions; text quality/semantic checks belong to NL model.
    description_word_count = 0
    drug_keyword_count = 0
    drug_keyword_ratio = 0.0
    mentions_drug_keywords = 0

    latitude = getattr(report, "latitude", None)
    longitude = getattr(report, "longitude", None)
    gps_accuracy = getattr(report, "gps_accuracy", None)
    movement_speed = getattr(report, "movement_speed", None)
    was_stationary = getattr(report, "was_stationary", None)

    # Device stats from DB (real values; no synthetic neutral overrides).
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

    # Clamp evidence count to avoid accidental negative/None-derived evidence credit.
    safe_evidence_count = max(0, int(evidence_count or 0))
    # Whether we have at least one live-capture evidence – for now we approximate with count > 0.
    has_live_capture = 1 if safe_evidence_count > 0 else 0

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
            row[col] = safe_evidence_count
        elif col == "has_live_capture":
            row[col] = has_live_capture
        elif col == "time_of_day":
            row[col] = time_of_day
        elif col == "reported_at":
            row[col] = reported_at.isoformat() if reported_at is not None else None
        elif col == "description_word_count":
            row[col] = description_word_count
        elif col == "drug_keyword_count":
            row[col] = drug_keyword_count
        elif col == "drug_keyword_ratio":
            row[col] = drug_keyword_ratio
        elif col == "mentions_drug_keywords":
            row[col] = mentions_drug_keywords
        elif col == "incident_is_drug_type":
            # Keep neutral to avoid incident-text coupling in TrustBond.
            row[col] = 0
        elif col == "incident_description_mismatch":
            # NLP model owns semantic mismatch; keep neutral in TrustBond input.
            row[col] = 0
        elif col == "description":
            # Keep text payload neutral in TrustBond to avoid duplicated NLP responsibility.
            row[col] = ""
        elif col == "description_text":
            row[col] = ""
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
        elif col == "decision":
            # Training artifact column: keep deterministic neutral value at inference time.
            row[col] = "pending"
        elif col == "confidence_level":
            # Training artifact column: neutral midpoint to avoid leaking final outcomes.
            row[col] = 0.5
        elif col == "used_for_training":
            # Inference-time rows are not labeled training records.
            row[col] = 0
        else:
            # Unknown column – leave as None so the pipeline can handle it if needed
            row[col] = None

    return row


def _compute_trust_factors(db: Session, report: Report, device: Device, evidence_count: int, prob_real: float) -> Dict[str, Any]:
    """Calculate granular heuristics explaining the report's credibility."""
    factors: Dict[str, Any] = {}
    safe_evidence_count = max(0, int(evidence_count or 0))
    
    # 1. Evidence Presence Score (0-100)
    # NLP owns text quality; TrustBond only contributes non-textual heuristics.
    ev_score = min(100.0, safe_evidence_count * 50.0)  # Up to 100 points for 2+ evidence files
    content_score = ev_score
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
    *,
    window: int = 30,
    return_metadata: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Run XGBoost credibility model for a single report and persist the result.
    This is the core ML scoring function used by the 3-model system.
    
    Args:
        db: Database session
        report: Report object
        device: Device object
        evidence_count: Number of evidence files
        window: Time window for device history analysis
        return_metadata: If True, return metadata instead of persisting
        
    Returns:
        Dict with metadata if return_metadata=True, otherwise None
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

        # Calculate base credibility score (0-100)
        credibility_score = prob_real * 100.0
        
        # Calculate trust factors for explanation (no decision making)
        factors = _compute_trust_factors(db, report, device, evidence_count, prob_real)
        
        # Apply coordination penalty (reduces score but doesn't make decisions)
        coord_penalty = float(factors.get("coordination_penalty", 0.0) or 0.0)
        if coord_penalty > 0:
            credibility_score = max(0.0, credibility_score - (coord_penalty * 0.5))

        # Apply community votes modifier (adjusts score but doesn't make decisions)
        community_net = factors.get("community_net_votes", 0)
        if community_net > 0:
            credibility_score = min(100.0, credibility_score + (community_net * 5.0))
        elif community_net < 0:
            credibility_score = max(0.0, credibility_score + (community_net * 10.0))

        # Store TrustBond output as a model contribution only.
        # Final label/decision is assigned later by unified aggregation.
        prediction = MLPrediction(
            prediction_id=uuid4(),
            report_id=report.report_id,
            trust_score=Decimal(f"{credibility_score:.2f}"),
            prediction_label=None,
            model_version=meta.get("model_version", "report_credibility_xgb_v1"),
            model_type="xgboost",
            confidence=Decimal(f"{prob_real:.3f}"),
            is_final=False,  # Not final - will be aggregated
            explanation=factors,  # Store factors for aggregator use
            processing_time=None,
        )
        db.add(prediction)
        # Mark when features were extracted for this report
        report.features_extracted_at = datetime.now(timezone.utc)
    except Exception as e:
        # Log the actual error for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"XGBoost scoring failed for report {report.report_id}: {e}", exc_info=True)
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

        # Fix confirmation rate calculation - don't penalize new devices with pending reports
        if total_reports == 0:
            confirm_rate = 0.5  # Neutral for new devices
        elif trusted_reports == 0 and total_reports == 1:
            # Single report that's still pending - don't penalize heavily
            confirm_rate = 0.4  # Slightly lower than neutral but not zero
        else:
            confirm_rate = (trusted_reports / total_reports)
        
        spam_signal = spam_flags + flagged_reports
        
        # Improved behavior score calculation with recovery mechanisms
        # Base score from confirmation rate, but with floor to prevent death spiral
        base_score = confirm_rate * 100.0
        
        # Location diversity from recent reports (distinct villages / recent reports)
        recent_reports = (
            db.query(
                Report.village_location_id,
                Report.reported_at,
                Report.latitude,
                Report.longitude,
                Report.gps_accuracy,
            )
            .filter(Report.device_id == device.device_id)
            .order_by(Report.reported_at.desc())
            .limit(window)
            .all()
        )
        total_recent = len(recent_reports)
        distinct_villages = len({r[0] for r in recent_reports if r[0] is not None})
        location_diversity = (distinct_villages / total_recent) if total_recent > 0 else 0.0
        
        # Time-based decay: older negative impacts fade over time
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        decay_factor = 1.0
        
        if recent_reports:
            oldest_report_time = recent_reports[-1][1] if recent_reports[-1][1] else now
            days_since_oldest = (now - oldest_report_time).days
            # Decay factor: 1.0 (recent) to 0.3 (old) over 90 days
            decay_factor = max(0.3, 1.0 - (days_since_oldest / 90.0) * 0.7)
        
        # Apply spam penalty but less severe (was 2.5, now 1.5) with time decay
        spam_penalty = (spam_signal * 1.5) * decay_factor
        
        # Add recovery bonus: new reports get some trust back
        recovery_bonus = min(20.0, total_reports * 0.5) if confirm_rate > 0 else 0.0
        
        # Calculate final behavior score with minimum floor
        behavior_score = max(10.0, min(100.0, base_score - spam_penalty + recovery_bonus))

        # Calculate location quality score
        location_score = calculate_location_score(db, str(device.device_id))
        
        weights = _load_trust_formula(db)
        
        # Debug logging to identify the issue
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Device trust calculation for {device.device_id}:")
        logger.warning(f"  Current score: {getattr(device, 'device_trust_score', 'N/A')}")
        logger.warning(f"  ML avg: {ml_avg}")
        logger.warning(f"  Confirmation rate: {confirm_rate}")
        logger.warning(f"  Spam signal: {spam_signal}")
        logger.warning(f"  Location diversity: {location_diversity}")
        logger.warning(f"  Location quality score: {location_score}")
        logger.warning(f"  Weights: {weights}")
        
        blended = compute_trust_score(
            ml_avg=float(ml_avg) if ml_avg is not None else None,
            confirmation_rate=confirm_rate,
            spam_signal=spam_signal,
            location_diversity=location_diversity,
            location_score=location_score,
            weights=weights,
        )

        # Clamp 0..100 and persist
        blended = max(0.0, min(100.0, blended))
        logger.warning(f"  New calculated score: {blended}")
        
        # Sanity check: don't allow dramatic drops for single good reports
        current_score = float(getattr(device, 'device_trust_score', 50.0) or 50.0)
        if ml_avg is not None and ml_avg >= 80.0 and blended < current_score - 20.0:
            logger.warning(f"  OVERRIDING: Preventing dramatic drop after high-trust report")
            blended = max(blended, current_score - 5.0)  # Allow small drop but not dramatic
        
        if hasattr(device, "device_trust_score"):
            device.device_trust_score = Decimal(f"{blended:.2f}")

        # Heuristic blacklist from ML rates and behavior
        # (Keep "ban" as explicit admin action; blacklist is advisory/system-driven.)
        if hasattr(device, "is_blacklisted"):
            should_blacklist = False
            reason = None
            min_reports_for_blacklist = 5
            min_preds_for_blacklist = 5
            # Prevent first/early submissions from ending in an automatic "banned-like" UI state.
            if total_reports >= min_reports_for_blacklist:
                if fake_rate >= 0.7 and total_preds >= min_preds_for_blacklist:
                    should_blacklist = True
                    reason = "ml_high_fake_rate"
                elif (
                    ml_avg is not None
                    and float(ml_avg) < 15
                    and total_preds >= min_preds_for_blacklist
                ):
                    should_blacklist = True
                    reason = "ml_low_trust_average"
                elif spam_signal >= 12:
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
            "location_quality_score": round(float(location_score) * 100.0, 2),
        }
        # Persist compact location history for Device Trust UI consistency analysis.
        location_history = []
        for _, reported_at, lat, lon, gps_acc in recent_reports[:20]:
            try:
                if lat is None or lon is None:
                    continue
                location_history.append(
                    {
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "gps_accuracy": float(gps_acc) if gps_acc is not None else None,
                        "reported_at": reported_at.isoformat() if reported_at else None,
                    }
                )
            except Exception:
                continue
        meta["location_history"] = location_history
        if location_history:
            last = location_history[0]
            meta["last_latitude"] = last.get("latitude")
            meta["last_longitude"] = last.get("longitude")
            meta["last_gps_accuracy_m"] = last.get("gps_accuracy")
            meta["last_location_timestamp"] = last.get("reported_at")
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
    # Convert strings to UUID if needed
    from uuid import UUID
    try:
        report_uuid = UUID(report_id)
        device_uuid = UUID(device_id)
    except ValueError:
        return None
    
    # Verify the report belongs to the device
    report = db.query(Report).filter(
        Report.report_id == report_uuid,
        Report.device_id == device_uuid
    ).first()
    
    if not report:
        return None
    
    # Get latest ML prediction
    prediction = db.query(MLPrediction).filter(
        MLPrediction.report_id == report_uuid
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

    # Calculate prediction distribution
    distribution = {"likely_real": 0, "suspicious": 0, "uncertain": 0, "fake": 0}
    trust_scores = []
    confidences = []
    model_versions = set()
    
    for pred in predictions:
        label = (pred.prediction_label or "").lower()
        if label in distribution:
            distribution[label] += 1
        
        # Collect trust scores and confidences
        if pred.trust_score is not None:
            trust_scores.append(float(pred.trust_score))
        if pred.confidence is not None:
            confidences.append(float(pred.confidence))
        if pred.model_version:
            model_versions.add(pred.model_version)
    
    # Calculate ML statistics
    total_predictions = len(predictions)
    fake_rate = (distribution["fake"] / total_predictions * 100) if total_predictions > 0 else 0.0
    suspicious_rate = (distribution["suspicious"] / total_predictions * 100) if total_predictions > 0 else 0.0
    avg_trust_score = sum(trust_scores) / len(trust_scores) if trust_scores else None
    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    
    # Get device metadata
    meta = getattr(device, "metadata_json", None)
    behavior_meta = meta.get("behavior") if isinstance(meta, dict) else None
    
    # Build ML section with actual calculated data
    ml_stats = {
        "window": 30,  # 30-day window
        "fake_rate": round(fake_rate, 2),
        "suspicious_rate": round(suspicious_rate, 2),
        "distribution": distribution.copy(),
        "avg_trust_score": round(avg_trust_score, 2) if avg_trust_score is not None else None,
        "avg_confidence": round(avg_confidence, 3) if avg_confidence is not None else None,
        "last_confidence": round(float(confidences[0]), 3) if confidences else None,
        "model_versions": list(model_versions),
        "last_prediction_at": (
            predictions[0].evaluated_at.isoformat()
            if predictions and getattr(predictions[0], "evaluated_at", None)
            else None
        )
    }
    
    # Calculate behavior stats
    confirmed_reports = sum(1 for r in reports if getattr(r, 'status', None) == 'verified')
    confirmation_rate = (confirmed_reports / len(reports) * 100) if reports else 0.0
    
    behavior_stats = {
        "spam_signal": 0,  # Could be calculated from spam flags
        "behavior_score": 0.0,  # Could be calculated from various factors
        "confirmation_rate": round(confirmation_rate, 2)
    }

    return {
        "device_id": str(device_id),
        "total_reports": int(getattr(device, "total_reports", None) or len(reports) or 0),
        "trust_score": float(device.device_trust_score) if device.device_trust_score is not None else None,
        "prediction_distribution": distribution,
        "last_prediction_at": (
            predictions[0].evaluated_at.isoformat()
            if predictions and getattr(predictions[0], "evaluated_at", None)
            else None
        ),
        "ml": ml_stats,
        "behavior": behavior_stats,
    }

