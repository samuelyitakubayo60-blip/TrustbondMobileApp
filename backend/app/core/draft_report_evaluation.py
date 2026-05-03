"""
Server-side preview of submit-time trust aggregation for submission guidance.

Uses the same TrustBond inference, NL scorer, trust aggregator, and (when evidence
is only described, not uploaded) the same heuristic evidence metrics as offline guidance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.credibility_model import compute_trustbond_credibility_inference
from app.core.natural_language_scorer import analyze_description_quality
from app.core.submission_guidance import TrustScoreEstimate, submission_guidance
from app.core.trust_aggregator import aggregate_trust_scores
from app.models.device import Device
from app.models.incident_type import IncidentType


def _resolve_incident_type(db: Session, incident_type_label: str) -> Tuple[int, str, str]:
    label = (incident_type_label or "").strip()
    if label:
        row = (
            db.query(IncidentType)
            .filter(IncidentType.type_name.ilike(label))
            .filter(IncidentType.is_active.is_(True))
            .first()
        )
        if row:
            return int(row.incident_type_id), row.type_name or label, (row.description or "")
    row = db.query(IncidentType).filter(IncidentType.is_active.is_(True)).first()
    if row:
        return int(row.incident_type_id), row.type_name or label, (row.description or "")
    return 1, label, ""


def _draft_device(db: Session, device_id: Optional[str]) -> Any:
    if device_id:
        try:
            uid = UUID(device_id)
        except ValueError:
            uid = None
        if uid is not None:
            d = db.query(Device).filter(Device.device_id == uid).first()
            if d:
                return d
    return SimpleNamespace(
        device_id=uuid4(),
        total_reports=0,
        trusted_reports=0,
        flagged_reports=0,
        spam_flags=0,
        device_trust_score=50.0,
    )


def _build_draft_report(
    *,
    device: Any,
    incident_type_id: int,
    type_name: str,
    type_desc: str,
    description: str,
    evidence_count: int,
    gps_accuracy: Optional[float],
    movement_speed: Optional[float],
) -> Any:
    now = datetime.now(timezone.utc)
    speed = movement_speed
    stationary = True
    if speed is not None:
        try:
            stationary = float(speed) <= 1.0
        except Exception:
            stationary = True
    placeholders = [SimpleNamespace() for _ in range(min(max(evidence_count, 0), 10))]
    return SimpleNamespace(
        report_id=uuid4(),
        device_id=getattr(device, "device_id"),
        incident_type_id=incident_type_id,
        incident_type=SimpleNamespace(type_name=type_name, description=type_desc),
        description=description,
        latitude=-1.5,
        longitude=29.6,
        gps_accuracy=gps_accuracy,
        movement_speed=movement_speed,
        was_stationary=stationary,
        reported_at=now,
        rule_status="pending",
        is_flagged=False,
        feature_vector={},
        network_type="mobile",
        motion_level=None,
        evidence_files=placeholders,
    )


def _base_score_from_aggregation(aggregated: Any) -> float:
    for ms in aggregated.model_scores:
        if ms.model_name == "base":
            return float(ms.raw_score)
    return 0.0


def preview_trust_estimate_online(
    db: Session,
    *,
    description: str,
    incident_type: str,
    evidence_count: int,
    file_types: Optional[List[str]] = None,
    gps_accuracy: Optional[float] = None,
    movement_speed: Optional[float] = None,
    device_id: Optional[str] = None,
    has_live_capture: bool = False,
) -> Optional[TrustScoreEstimate]:
    """
    Mirror unified validation scoring (TrustBond + NL + optional heuristic Volo) without persisting.
    Returns None only if aggregation fails unexpectedly.
    """
    incident_type_id, type_name, type_desc = _resolve_incident_type(db, incident_type)
    device = _draft_device(db, device_id)
    report = _build_draft_report(
        device=device,
        incident_type_id=incident_type_id,
        type_name=type_name,
        type_desc=type_desc,
        description=description or "",
        evidence_count=evidence_count,
        gps_accuracy=gps_accuracy,
        movement_speed=movement_speed,
    )

    nl = analyze_description_quality(
        description or "",
        type_name,
        type_desc,
    )

    tb_result = compute_trustbond_credibility_inference(db, report, device, evidence_count)
    trustbond_score = tb_result["credibility_score"] if tb_result else None

    volo_score: Optional[float] = None
    if evidence_count > 0:
        metrics = submission_guidance.evaluate_evidence_quality(
            evidence_count=evidence_count,
            has_live_capture=has_live_capture,
            file_types=file_types or [],
            incident_type=incident_type,
        )
        yolo = float(metrics.get("yolo_coverage_score", 0.0))
        file_rel = float(metrics.get("trustbond_evidence_score", 0.0))
        volo_score = max(0.0, min(100.0, (yolo * 0.75) + (file_rel * 0.25)))
    else:
        volo_score = None

    volo_results_meta_len = evidence_count if evidence_count > 0 else 0

    aggregated = aggregate_trust_scores(
        report=report,
        device=device,
        trustbond_score=trustbond_score,
        natural_language_score=nl.overall_score,
        volo_score=volo_score,
        model_metadata={
            "trustbond": {
                "confidence": 0.8,
                "model_version": (tb_result or {}).get("model_version", "report_credibility_xgb_v1"),
            },
            "natural_language": {
                "confidence": nl.confidence,
                "semantic_similarity": nl.semantic_similarity_score,
                "description_quality": nl.description_quality_score,
            },
            "volo": {
                "confidence": 0.5 if volo_score is not None else 0.0,
                "evidence_count": volo_results_meta_len,
                "preview_heuristic": True,
            },
        },
    )

    th = submission_guidance.thresholds
    has_evidence = evidence_count > 0
    confirm_min = th["evidence_confirmed_min"] if has_evidence else th["text_confirmed_min"]
    review_min = th["evidence_under_review_min"] if has_evidence else th["text_under_review_min"]
    total = round(float(aggregated.total_score), 2)

    if total >= confirm_min:
        confidence = "high_confidence"
        will_be_verified = True
    elif total >= review_min:
        confidence = "medium_confidence"
        will_be_verified = False
    elif total > 0:
        confidence = "low_confidence"
        will_be_verified = False
    else:
        confidence = "reject"
        will_be_verified = False

    tb_display = float(trustbond_score) if trustbond_score is not None else 0.0
    base_display = _base_score_from_aggregation(aggregated)

    return TrustScoreEstimate(
        total_score=total,
        trustbond_score=tb_display,
        natural_language_score=float(nl.overall_score),
        volo_score=volo_score,
        base_score=base_display,
        confidence=confidence,
        will_be_verified=will_be_verified,
        contributing_models=int(aggregated.contributing_models),
    )
