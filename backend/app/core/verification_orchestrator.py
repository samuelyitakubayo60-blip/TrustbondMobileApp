"""
Single citizen-report verification pipeline.

Order: integrity hints → unified models → anti-fraud rules → scorecard → outcome → narratives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.credibility_model import _json_safe, update_device_ml_aggregates
from app.core.report_priority import apply_anti_fraud_rules, calculate_report_priority
from app.core.report_review import infer_prediction_label_from_trust_score, resolve_ml_prediction_for_report
from app.core.trust_thresholds import TrustBand
from app.core.unified_validator import validate_report_unified
from app.models.device import Device
from app.models.evidence_file import EvidenceFile
from app.models.ml_prediction import MLPrediction
from app.models.report import Report

logger = logging.getLogger(__name__)

VOLO_VALID_THRESHOLD = 45.0  # overall_score 0-100


@dataclass
class VerificationPipelineResult:
    unified_validation: Dict[str, Any]
    scorecard: Dict[str, Any]
    rule_status: str
    is_flagged: bool
    flag_reason: Optional[str]
    priority: str
    ml_prediction: Optional[Any]
    ai_trust_score: Optional[float]
    ai_label: Optional[str]


def community_votes_from_report(report: Report) -> Dict[str, int]:
    votes = {"real": 0, "false": 0, "unknown": 0}
    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        return votes
    raw = fv.get("community_votes")
    if not isinstance(raw, dict):
        return votes
    for v in raw.values():
        k = str(v).strip().lower()
        if k in votes:
            votes[k] += 1
    return votes


def _media_types_for_volo(file_type: Optional[str]) -> bool:
    ft = (file_type or "").strip().lower()
    if ft in ("photo", "video", "audio"):
        return True
    return ft.startswith("image/") or ft in (
        "image/jpeg",
        "image/png",
        "image/jpg",
        "image/webp",
    )


def evidence_files_for_volo(evidence_files: Optional[List[EvidenceFile]]) -> List[EvidenceFile]:
    out: List[EvidenceFile] = []
    for ef in evidence_files or []:
        if not getattr(ef, "file_url", None):
            continue
        if _media_types_for_volo(getattr(ef, "file_type", None)):
            out.append(ef)
    return out


def merge_volo_into_evidence_validations(
    evidence_validations: List[Dict[str, Any]],
    evidence_files: Optional[List[EvidenceFile]],
    volo_results: List[Any],
) -> List[Dict[str, Any]]:
    """Replace stub validations with Volo/YOLO scores (same order as unified validator loop)."""
    analyzed = evidence_files_for_volo(evidence_files)
    volo_by_url: Dict[str, Any] = {}
    for idx, ef in enumerate(analyzed):
        if idx >= len(volo_results):
            break
        url = (getattr(ef, "file_url", None) or "").strip()
        if url:
            volo_by_url[url] = volo_results[idx]

    merged: List[Dict[str, Any]] = []
    for item in evidence_validations or []:
        entry = dict(item) if isinstance(item, dict) else {"evidence_url": "", "validation": {}}
        url = (entry.get("evidence_url") or "").strip()
        volo = volo_by_url.get(url)
        if volo is None:
            merged.append(entry)
            continue
        score = float(getattr(volo, "overall_score", 0.0) or 0.0)
        conf = float(getattr(volo, "confidence", 0.0) or 0.0)
        meta = getattr(volo, "metadata", None) or {}
        det = meta.get("detection_analysis") if isinstance(meta.get("detection_analysis"), dict) else {}
        valid = score >= VOLO_VALID_THRESHOLD
        issues: List[str] = []
        if not valid:
            issues.append("low_evidence_authenticity_score")
        entry["validation"] = {
            "valid": valid,
            "confidence": max(0.0, min(1.0, conf)),
            "threshold_used": VOLO_VALID_THRESHOLD / 100.0,
            "issues": issues,
            "source": "volo",
            "volo_overall_score": round(score, 2),
            "analysis_summary": {
                "quality_score": round(score / 100.0, 4),
                "detected_objects": det.get("detected_objects") or [],
                "media_type": (getattr(
                    next((e for e in analyzed if (e.file_url or "").strip() == url), None),
                    "file_type",
                    None,
                ) or "media"),
            },
        }
        merged.append(entry)
    return merged


def store_unified_validation_result(
    db: Session,
    report: Report,
    validation_result: Any,
) -> Dict[str, Any]:
    """Persist unified validation; ML row holds aggregate score only (not final verdict)."""
    aggregated = validation_result.aggregated_trust
    model_breakdown = {
        score.model_name: {
            "raw_score": score.raw_score,
            "contribution": score.contribution,
            "is_valid": score.is_valid,
            "metadata": score.metadata,
        }
        for score in aggregated.model_scores
    }
    unified_validation = {
        "aggregated_score": round(float(aggregated.total_score), 2),
        "trust_band": aggregated.trust_band.value,
        "contributing_models": aggregated.contributing_models,
        "model_breakdown": model_breakdown,
        "validation_metadata": validation_result.validation_metadata,
    }

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["unified_validation"] = unified_validation
    report.feature_vector = _json_safe(fv)

    aggregated_score = round(float(aggregated.total_score), 2)
    ml_prediction = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == report.report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if ml_prediction is not None:
        ml_prediction.trust_score = Decimal(f"{aggregated_score:.2f}")
        ml_prediction.prediction_label = infer_prediction_label_from_trust_score(aggregated_score)
        explanation = ml_prediction.explanation if isinstance(ml_prediction.explanation, dict) else {}
        explanation["unified_validation"] = unified_validation
        ml_prediction.explanation = _json_safe(explanation)
        if hasattr(ml_prediction, "is_final"):
            ml_prediction.is_final = False
    else:
        db.add(
            MLPrediction(
                prediction_id=uuid4(),
                report_id=report.report_id,
                trust_score=Decimal(f"{aggregated_score:.2f}"),
                prediction_label=infer_prediction_label_from_trust_score(aggregated_score),
                confidence=Decimal("0.75"),
                model_type="unified_aggregation",
                is_final=False,
                explanation={"unified_validation": unified_validation},
                evaluated_at=datetime.now(timezone.utc),
            )
        )

    return unified_validation


def reconcile_scorecard_with_unified_trust(
    scorecard: Dict[str, Any],
    unified_validation: Optional[Dict[str, Any]],
    *,
    has_evidence: bool,
) -> Dict[str, Any]:
    """
    Align scorecard threshold_band with unified TrustBand when unified_validation drove the score.
    Prevents 85-point scorecard bands fighting 70-point aggregator bands.
    """
    if not isinstance(scorecard, dict) or not isinstance(unified_validation, dict):
        return scorecard
    if scorecard.get("decision_source") != "unified_validation":
        return scorecard

    hard_gates = scorecard.get("hard_gates") or []
    if hard_gates:
        scorecard["threshold_band"] = "hard_reject"
        scorecard["unified_band_aligned"] = True
        return scorecard

    trust_band = str(unified_validation.get("trust_band") or "").strip().lower()
    total = float(scorecard.get("total_score") or unified_validation.get("aggregated_score") or 0.0)

    if trust_band == TrustBand.REJECT.value:
        band = "low_confidence"
    elif trust_band == TrustBand.HIGH_CONFIDENCE.value:
        band = "confirmed_candidate"
    elif trust_band == TrustBand.MEDIUM_CONFIDENCE.value:
        band = "under_review"
    else:
        # low_confidence from aggregator → officer review, not instant reject
        band = "under_review"

    # Extra guard: very low aggregate without hard gate still review unless extremely low
    reject_floor = 15.0 if has_evidence else 20.0
    if total < reject_floor and trust_band == TrustBand.REJECT.value:
        band = "low_confidence"

    scorecard["threshold_band"] = band
    scorecard["unified_band_aligned"] = True
    scorecard["unified_trust_band"] = trust_band
    return scorecard


def apply_threshold_outcome(report: Report, scorecard: Dict[str, Any]) -> None:
    """
    Apply scorecard to verification_status.

    Policy:
    - Hard gates / explicit rule reject → rejected
    - Flagged reports → under_review (never auto-rejected by score alone)
    - low_confidence without flag → rejected
    - under_review / confirmed_candidate as named
    """
    if not isinstance(scorecard, dict):
        return

    band = str(scorecard.get("threshold_band") or "").lower()
    hard_gates = scorecard.get("hard_gates") or []
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))
    flagged_for_review = is_flagged or rule_status == "flagged"

    if "boundary_reject" in hard_gates or "hard_rule_reject" in hard_gates:
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            report.flag_reason = (
                "boundary_reject" if "boundary_reject" in hard_gates else "hard_rule_reject"
            )
        return

    if rule_status == "rejected" and not flagged_for_review:
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        return

    if flagged_for_review:
        if report.rule_status != "rejected":
            report.verification_status = "under_review"
            if report.status not in ("rejected",):
                report.status = "pending"
        return

    if band == "low_confidence":
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            report.flag_reason = "threshold_low_score"
        return

    if band == "under_review":
        if report.rule_status != "rejected":
            if report.rule_status not in {"flagged"}:
                report.rule_status = "passed"
            report.verification_status = "under_review"
            if report.status != "rejected":
                report.status = "pending"
        return

    if band == "confirmed_candidate":
        if report.rule_status == "passed" and not is_flagged:
            report.verification_status = "verified"
            if report.status in {None, "", "pending", "flagged"}:
                report.status = "verified"


def run_integrity_checks_on_evidence(
    report: Report,
    evidence_metadata_list: List[dict],
) -> Tuple[List[str], bool]:
    """
    Lightweight post-upload integrity checks (screenshot, timing, source).
    Returns (issue messages, should_flag).
    """
    from app.core.report_rules import (
        analyze_file_timing,
        enhanced_screenshot_detection,
        validate_evidence_source,
    )

    issues: List[str] = []
    for evidence_meta in evidence_metadata_list or []:
        file_url = (evidence_meta.get("file_url") or "").split("/")[-1]
        path = evidence_meta.get("file_url")
        try:
            screenshot_result = enhanced_screenshot_detection(
                filename=file_url,
                file_path=path,
            )
            if screenshot_result.get("is_screenshot"):
                issues.append(f"Screenshot detected: {screenshot_result.get('details')}")
        except Exception as exc:
            logger.warning("Screenshot detection failed: %s", exc)

        try:
            timing_result = analyze_file_timing(
                file_path=path,
                file_created_at=evidence_meta.get("captured_at"),
            )
            if timing_result.get("is_suspicious"):
                issues.append(f"Suspicious file timing: {timing_result.get('suspicious_reasons')}")
        except Exception as exc:
            logger.warning("Timing analysis failed: %s", exc)

        try:
            source_result = validate_evidence_source(filename=file_url, file_path=path)
            if not source_result.get("is_valid"):
                issues.append(
                    f"Invalid evidence source: {source_result.get('suspicious_indicators')}"
                )
        except Exception as exc:
            logger.warning("Source validation failed: %s", exc)

    if not issues:
        return issues, False

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["integrity_issues"] = issues
    report.feature_vector = _json_safe(fv)
    return issues, True


def rule_adjusted_trust_label(
    report: Report,
    trust_score: Optional[float],
    ml_prediction_label: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    score = trust_score
    label = (ml_prediction_label or "").strip().lower() or None
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))

    if rule_status == "rejected":
        return score, "fake"
    if rule_status == "flagged" or is_flagged:
        if label in (None, "likely_real"):
            label = "suspicious"
        return score, label
    return score, label


def ensure_ml_prediction_from_unified(
    db: Session,
    report: Report,
    unified_validation: Optional[Dict[str, Any]],
) -> Optional[Any]:
    """
    Guarantee an ml_predictions row exists using unified aggregation only.
    No heuristic fallback — requires unified_validation from the verification pipeline.
    """
    existing = resolve_ml_prediction_for_report(report)
    if existing is not None:
        return existing
    if not isinstance(unified_validation, dict):
        fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
        unified_validation = fv.get("unified_validation") if isinstance(fv.get("unified_validation"), dict) else None
    if not isinstance(unified_validation, dict):
        logger.error(
            "Cannot create ML prediction for report %s: missing unified_validation",
            report.report_id,
        )
        return None
    try:
        aggregated_score = round(float(unified_validation.get("aggregated_score") or 0.0), 2)
    except (TypeError, ValueError):
        aggregated_score = 0.0
    row = MLPrediction(
        prediction_id=uuid4(),
        report_id=report.report_id,
        trust_score=Decimal(f"{aggregated_score:.2f}"),
        prediction_label=infer_prediction_label_from_trust_score(aggregated_score),
        confidence=Decimal("0.75"),
        model_type="unified_aggregation",
        is_final=False,
        explanation={"unified_validation": unified_validation},
        evaluated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    return row


def persist_adjusted_ml_prediction(
    db: Session,
    ml_prediction: Optional[Any],
    adjusted_trust_score: Optional[float],
    adjusted_label: Optional[str],
) -> None:
    if ml_prediction is None:
        return
    changed = False
    if adjusted_trust_score is not None:
        try:
            new_score = float(adjusted_trust_score)
            old_score = (
                float(ml_prediction.trust_score)
                if getattr(ml_prediction, "trust_score", None) is not None
                else None
            )
            if old_score is None or abs(old_score - new_score) > 1e-6:
                ml_prediction.trust_score = new_score
                changed = True
        except (TypeError, ValueError):
            pass
    if adjusted_label:
        new_label = str(adjusted_label).strip().lower()
        old_label = (
            str(getattr(ml_prediction, "prediction_label", "")).strip().lower()
            if getattr(ml_prediction, "prediction_label", None) is not None
            else ""
        )
        if new_label and new_label != old_label:
            ml_prediction.prediction_label = new_label
            changed = True
    if hasattr(ml_prediction, "is_final"):
        ml_prediction.is_final = True
    if changed:
        db.add(ml_prediction)


def rerun_scorecard_and_outcome(
    db: Session,
    report: Report,
    device: Device,
    *,
    compute_scorecard_fn: Callable[..., Dict[str, Any]],
    respect_human_final: bool = True,
) -> Dict[str, Any]:
    """
    Recompute scorecard + outcome after community votes or evidence changes.
    Skips outcome changes when ML prediction is marked is_final (police decision).
    """
    ml_prediction = resolve_ml_prediction_for_report(report)
    if (
        respect_human_final
        and ml_prediction is not None
        and getattr(ml_prediction, "is_final", False)
        and getattr(ml_prediction, "model_type", None) == "human_override"
    ):
        return report.feature_vector.get("threshold_scorecard", {}) if isinstance(
            report.feature_vector, dict
        ) else {}

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    unified_validation = fv.get("unified_validation") if isinstance(fv.get("unified_validation"), dict) else {}
    evidence_validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []
    has_evidence = len(evidence_validations) > 0 or bool(
        db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).count()
    )

    scorecard = compute_scorecard_fn(
        report,
        ml_prediction=ml_prediction,
        community_votes=community_votes_from_report(report),
        unified_validation=unified_validation or None,
    )
    scorecard = reconcile_scorecard_with_unified_trust(
        scorecard, unified_validation, has_evidence=has_evidence
    )
    fv["threshold_scorecard"] = scorecard
    report.feature_vector = _json_safe(fv)
    apply_threshold_outcome(report, scorecard)

    if ml_prediction is None:
        ml_prediction = ensure_ml_prediction_from_unified(db, report, unified_validation)
    ai_ts = (
        float(ml_prediction.trust_score)
        if ml_prediction and getattr(ml_prediction, "trust_score", None) is not None
        else None
    )
    ai_lbl = getattr(ml_prediction, "prediction_label", None) if ml_prediction else None
    ai_ts, ai_lbl = rule_adjusted_trust_label(report, ai_ts, ai_lbl)
    persist_adjusted_ml_prediction(db, ml_prediction, ai_ts, ai_lbl)
    try:
        update_device_ml_aggregates(db, device, window=30)
    except Exception as exc:
        logger.warning("Device ML aggregates update failed: %s", exc)

    return scorecard


def run_citizen_verification_pipeline(
    db: Session,
    report: Report,
    device: Device,
    *,
    evidence_files: Optional[List[EvidenceFile]] = None,
    evidence_validations: Optional[List[Dict[str, Any]]] = None,
    evidence_metadata_list: Optional[List[dict]] = None,
    compute_scorecard_fn: Callable[..., Dict[str, Any]],
    compose_narratives_fn: Optional[Callable[..., None]] = None,
    skip_if_out_of_boundary: bool = False,
) -> VerificationPipelineResult:
    """
    Full citizen verification: unified models → merge Volo evidence → rules → scorecard → outcome.
    """
    if skip_if_out_of_boundary:
        fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
        if fv.get("boundary_status") == "out_of_musanze":
            return VerificationPipelineResult(
                unified_validation={},
                scorecard={},
                rule_status=report.rule_status or "rejected",
                is_flagged=bool(report.is_flagged),
                flag_reason=report.flag_reason,
                priority=report.priority or "low",
                ml_prediction=resolve_ml_prediction_for_report(report),
                ai_trust_score=None,
                ai_label=None,
            )

    evidence_count = len(evidence_files or []) or (
        db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).count()
    )

    if evidence_metadata_list:
        _, should_flag = run_integrity_checks_on_evidence(report, evidence_metadata_list)
        if should_flag and report.rule_status != "rejected":
            report.is_flagged = True
            report.rule_status = "flagged"
            report.verification_status = "under_review"
            if not report.flag_reason:
                report.flag_reason = "evidence_integrity_check"

    validation_result = validate_report_unified(
        db=db,
        report=report,
        device=device,
        evidence_files=list(evidence_files or []),
    )
    unified_validation = store_unified_validation_result(db, report, validation_result)

    validations = list(evidence_validations or [])
    if isinstance(report.feature_vector, dict) and report.feature_vector.get("evidence_validations"):
        validations = list(report.feature_vector.get("evidence_validations") or validations)
    validations = merge_volo_into_evidence_validations(
        validations,
        evidence_files,
        validation_result.volo_results,
    )
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    if validations:
        fv["evidence_validations"] = validations
        report.feature_vector = _json_safe(fv)

    rule_status, is_flagged, flag_reason = apply_anti_fraud_rules(report, evidence_count, db)
    if report.rule_status != "rejected":
        report.rule_status = rule_status
    report.is_flagged = bool(report.is_flagged or is_flagged)
    if is_flagged and flag_reason and not report.flag_reason:
        report.flag_reason = flag_reason
    if report.is_flagged and report.rule_status != "rejected":
        report.verification_status = "under_review"

    priority = calculate_report_priority(report, evidence_count, db, unified_validation)
    report.priority = priority

    votes = community_votes_from_report(report)
    ml_prediction = resolve_ml_prediction_for_report(report)
    scorecard = compute_scorecard_fn(
        report,
        ml_prediction=ml_prediction,
        community_votes=votes,
        unified_validation=unified_validation,
    )
    has_evidence = len(validations) > 0 or evidence_count > 0
    scorecard = reconcile_scorecard_with_unified_trust(
        scorecard, unified_validation, has_evidence=has_evidence
    )
    fv_sc = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv_sc["threshold_scorecard"] = scorecard
    report.feature_vector = _json_safe(fv_sc)
    apply_threshold_outcome(report, scorecard)

    if ml_prediction is None:
        ml_prediction = ensure_ml_prediction_from_unified(db, report, unified_validation)
    ai_ts = (
        float(ml_prediction.trust_score)
        if ml_prediction and getattr(ml_prediction, "trust_score", None) is not None
        else None
    )
    ai_lbl = getattr(ml_prediction, "prediction_label", None) if ml_prediction else None
    ai_ts, ai_lbl = rule_adjusted_trust_label(report, ai_ts, ai_lbl)
    persist_adjusted_ml_prediction(db, ml_prediction, ai_ts, ai_lbl)
    try:
        update_device_ml_aggregates(db, device, window=30)
    except Exception:
        pass

    if compose_narratives_fn is not None:
        compose_narratives_fn(
            report=report,
            unified_validation=unified_validation,
            scorecard=scorecard,
            ml_prediction=ml_prediction,
            ai_trust_score=ai_ts,
            ai_label=ai_lbl,
            evidence_validations=validations,
        )

    report.ai_ready = True
    report.features_extracted_at = datetime.now(timezone.utc)

    return VerificationPipelineResult(
        unified_validation=unified_validation,
        scorecard=scorecard,
        rule_status=report.rule_status or rule_status,
        is_flagged=bool(report.is_flagged),
        flag_reason=report.flag_reason,
        priority=priority,
        ml_prediction=ml_prediction,
        ai_trust_score=ai_ts,
        ai_label=ai_lbl,
    )


def process_backlog_report(
    db: Session,
    report: Report,
    *,
    compute_scorecard_fn: Callable[..., Dict[str, Any]],
    compose_narratives_fn: Optional[Callable[..., None]] = None,
) -> bool:
    """Run unified pipeline for stale pending rows (replaces legacy ml_evaluator startup)."""
    from app.core.leader_workflow import report_is_leader_submitted

    if report_is_leader_submitted(report):
        return False

    rs = (report.rule_status or "").strip().lower()
    if rs == "rejected":
        report.verification_status = "rejected"
        report.status = "rejected"
        return True

    device = db.query(Device).filter(Device.device_id == report.device_id).first()
    if device is None:
        return False

    evidence_files = (
        db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).all()
    )
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []

    run_citizen_verification_pipeline(
        db,
        report,
        device,
        evidence_files=evidence_files,
        evidence_validations=validations,
        compute_scorecard_fn=compute_scorecard_fn,
        compose_narratives_fn=compose_narratives_fn,
    )
    report.ai_ready = True
    report.features_extracted_at = datetime.now(timezone.utc)
    return True
