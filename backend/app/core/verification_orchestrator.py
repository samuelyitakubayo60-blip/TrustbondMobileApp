"""
5-Stage Citizen Report Verification Pipeline
=============================================

Stage 1: Evidence Admissibility
Stage 2: Incident Type ↔ Description Validation (semantic, NO keywords)
Stage 3: Description Quality Analysis
Stage 4: Description ↔ Evidence Semantic Matching
Stage 5: Dynamic Trust Score Computation (only after stages 1-4 pass)

Final Decision: REJECTED | FLAGGED_FOR_REVIEW | ACCEPTED

Design principles:
- No keyword matching for incident validation
- Semantic analysis and embeddings for incident type matching
- Evidence compared against description, NOT incident type
- No evidence can still achieve trust score 100
- Invalid evidence causes immediate rejection
- Trust scoring only after all validation stages pass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.core.credibility_model import _json_safe, update_device_ml_aggregates
from app.core.report_priority import apply_anti_fraud_rules, calculate_report_priority
from app.core.report_review import (
    infer_prediction_label_from_trust_score,
    resolve_ml_prediction_for_report,
)
from app.core.trust_thresholds import TrustBand
from app.models.device import Device
from app.models.evidence_file import EvidenceFile
from app.models.incident_type import IncidentType
from app.models.ml_prediction import MLPrediction
from app.models.report import Report

logger = logging.getLogger(__name__)

VOLO_VALID_THRESHOLD = 45.0

HARD_GATE_REJECT_CODES = frozenset({
    "RULE_REJECTED",
    "LOCATION_OUT_OF_BOUNDARY",
    "BOUNDARY_REJECT",
    "HARD_RULE_REJECT",
    "boundary_reject",
    "hard_rule_reject",
})


# ── Pipeline Result ──────────────────────────────────────────────────────────

@dataclass
class PipelineStageAudit:
    """Audit trail for a single pipeline stage."""
    stage: int
    name: str
    decision: str
    score: Optional[float] = None
    duration_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationPipelineResult:
    """Result of the full 5-stage verification pipeline."""
    unified_validation: Dict[str, Any]
    scorecard: Dict[str, Any]
    rule_status: str
    is_flagged: bool
    flag_reason: Optional[str]
    priority: str
    ml_prediction: Optional[Any]
    ai_trust_score: Optional[float]
    ai_label: Optional[str]
    pipeline_audit: List[PipelineStageAudit] = field(default_factory=list)
    final_decision: str = ""  # ACCEPTED | FLAGGED_FOR_REVIEW | REJECTED


# ── Helpers ──────────────────────────────────────────────────────────────────

def pending_evidence_validation() -> Dict[str, Any]:
    return {
        "pending": True,
        "valid": None,
        "confidence": None,
        "source": "awaiting_unified_volo",
        "issues": [],
    }


def _normalize_evidence_url(url: Optional[str]) -> str:
    return (url or "").strip().split("?")[0]


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
        "image/jpeg", "image/png", "image/jpg", "image/webp",
    )


def evidence_files_for_volo(evidence_files: Optional[List[EvidenceFile]]) -> List[EvidenceFile]:
    out: List[EvidenceFile] = []
    for ef in evidence_files or []:
        if not getattr(ef, "file_url", None):
            continue
        if _media_types_for_volo(getattr(ef, "file_type", None)):
            out.append(ef)
    return out


# ── Volo merge (reused for evidence analysis) ───────────────────────────────

def merge_volo_into_evidence_validations(
    evidence_validations: List[Dict[str, Any]],
    evidence_files: Optional[List[EvidenceFile]],
    volo_results: List[Any],
) -> List[Dict[str, Any]]:
    """Replace stub validations with Volo/YOLO scores."""
    analyzed = evidence_files_for_volo(evidence_files)
    volo_by_url: Dict[str, Any] = {}
    for idx, ef in enumerate(analyzed):
        if idx >= len(volo_results):
            break
        url = _normalize_evidence_url(getattr(ef, "file_url", None))
        if url:
            volo_by_url[url] = volo_results[idx]

    merged: List[Dict[str, Any]] = []
    for item in evidence_validations or []:
        entry = dict(item) if isinstance(item, dict) else {"evidence_url": "", "validation": {}}
        url = _normalize_evidence_url(entry.get("evidence_url"))
        volo = volo_by_url.get(url)
        if volo is None:
            val = entry.get("validation") if isinstance(entry.get("validation"), dict) else {}
            if val.get("pending"):
                entry["validation"] = {
                    "pending": False, "valid": False, "confidence": 0.0,
                    "source": "volo_unavailable",
                    "issues": ["volo_analysis_unavailable"],
                    "threshold_used": VOLO_VALID_THRESHOLD / 100.0,
                }
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
        matched_ef = next((e for e in analyzed if (e.file_url or "").strip() == url), None)
        media_type = (getattr(matched_ef, "file_type", None) or "media")
        analysis_summary: Dict[str, Any] = {
            "quality_score": round(score / 100.0, 4),
            "detected_objects": det.get("detected_objects") or [],
            "media_type": media_type,
        }
        audio_meta = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        transcript = det.get("transcript_excerpt") or audio_meta.get("transcript") or ""
        if transcript:
            analysis_summary["extracted_text"] = transcript.strip()[:800]
        validation_entry: Dict[str, Any] = {
            "valid": valid, "confidence": max(0.0, min(1.0, conf)),
            "threshold_used": VOLO_VALID_THRESHOLD / 100.0,
            "issues": issues, "source": "volo",
            "volo_overall_score": round(score, 2),
            "analysis_summary": analysis_summary,
        }
        # Include forensic audio analysis if present (from AudioForensicAnalyzer)
        forensic = meta.get("forensic_analysis")
        if isinstance(forensic, dict):
            validation_entry["forensic_analysis"] = forensic
            # Also include audio_analysis for backward compat
            validation_entry["audio_analysis"] = audio_meta
        entry["validation"] = validation_entry
        merged.append(entry)
    return merged


def build_evidence_semantic_text(evidence_validations: List[Dict[str, Any]]) -> str:
    """Compact text from Volo outputs for semantic alignment."""
    fragments: List[str] = []
    for item in evidence_validations or []:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        advanced = validation.get("advanced_analysis") or {}
        objects = summary.get("detected_objects") or []
        if isinstance(objects, list) and objects:
            fragments.append("objects: " + ", ".join(str(o) for o in objects[:10]))
        extracted_text = summary.get("extracted_text")
        if isinstance(extracted_text, str) and extracted_text.strip():
            fragments.append("text: " + extracted_text.strip()[:300])
        actions = advanced.get("actions_detected") or []
        if isinstance(actions, list) and actions:
            fragments.append("actions: " + ", ".join(str(a) for a in actions[:8]))
        scene_context = advanced.get("scene_context") or {}
        scene_bits: List[str] = []
        indoor = scene_context.get("is_indoor")
        if isinstance(indoor, bool):
            scene_bits.append("indoor" if indoor else "outdoor")
        lighting = scene_context.get("lighting")
        if lighting:
            scene_bits.append(str(lighting))
        if scene_bits:
            fragments.append("scene: " + ", ".join(scene_bits))
        media_type = summary.get("media_type")
        if media_type:
            fragments.append(f"media_type: {media_type}")
    return " | ".join(fragments)[:2000]


# ── Build backward-compatible text_only_validation from Stage 2+3 ────────────

def build_text_only_validation_from_stages(
    stage2_result: Any,
    stage3_result: Any,
) -> Dict[str, Any]:
    """Map new pipeline stage results into legacy scorecard-compatible format."""
    incident_score = getattr(stage2_result, "final_incident_match_score", 50.0)
    desc_score = getattr(stage3_result, "description_score", 50.0)
    overall = (incident_score * 0.5) + (desc_score * 0.5)
    confidence = getattr(stage2_result, "confidence", 0.5)

    reason_codes: List[str] = []
    if desc_score < 15.0:
        reason_codes.append("GIBBERISH")
    if incident_score < 30.0:
        reason_codes.append("INCIDENT_TEXT_MISMATCH")
    if overall < 35.0:
        reason_codes.append("REJECT_QUALITY")
    elif overall < 55.0:
        reason_codes.append("REVIEW_QUALITY")

    if overall >= 55.0 and incident_score >= 35.0 and desc_score >= 20.0:
        quality_band = "accept_quality"
        valid = True
    elif overall < 30.0 or "REJECT_QUALITY" in reason_codes:
        quality_band = "reject_quality"
        valid = False
    else:
        quality_band = "review_quality"
        valid = False

    return {
        "valid": valid,
        "quality_band": quality_band,
        "reason_codes": reason_codes,
        "overall_score": round(overall, 2),
        "semantic_similarity": round(incident_score / 100.0, 4),
        "description_quality": round(desc_score, 2),
        "confidence": round(confidence, 4),
    }


# Legacy compat — old callers may import this
def build_text_only_validation_from_nl(nl: Any) -> Dict[str, Any]:
    """Legacy: Map NL analysis into scorecard-compatible text_only_validation."""
    overall = float(getattr(nl, "overall_score", 0.0) or 0.0)
    sem = float(getattr(nl, "semantic_similarity_score", 0.0) or 0.0)
    desc_q = float(getattr(nl, "description_quality_score", 0.0) or 0.0)
    conf = float(getattr(nl, "confidence", 0.0) or 0.0)
    reason_codes: List[str] = []
    if desc_q < 25.0:
        reason_codes.append("GIBBERISH")
    sem_meta = (getattr(nl, "metadata", {}) or {}).get("semantic_analysis", {}) or {}
    is_llm_based = bool(sem_meta.get("semantic_model_available", False))
    if is_llm_based:
        if sem < 35.0:
            reason_codes.append("INCIDENT_TEXT_MISMATCH")
    else:
        if sem < 25.0 and desc_q < 40.0:
            reason_codes.append("INCIDENT_TEXT_MISMATCH")
    if overall < 35.0:
        reason_codes.append("REJECT_QUALITY")
    elif overall < 55.0:
        reason_codes.append("REVIEW_QUALITY")
    sem_accept_min = 42.0 if is_llm_based else 20.0
    if overall >= 55.0 and sem >= sem_accept_min and desc_q >= 40.0:
        quality_band = "accept_quality"
        valid = True
    elif overall < 40.0 or "REJECT_QUALITY" in reason_codes:
        quality_band = "reject_quality"
        valid = False
    else:
        quality_band = "review_quality"
        valid = False
    return {
        "valid": valid, "quality_band": quality_band,
        "reason_codes": reason_codes, "overall_score": round(overall, 2),
        "semantic_similarity": round(sem, 4),
        "description_quality": round(desc_q, 2), "confidence": round(conf, 4),
    }


# ── ML Prediction helpers ───────────────────────────────────────────────────

def store_pipeline_trust_score(
    db: Session,
    report: Report,
    trust_score: float,
    pipeline_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist pipeline trust score as unified_validation and ML prediction row."""
    from app.core.trust_thresholds import trust_thresholds as _tt
    trust_band = _tt.get_trust_band(trust_score).value

    unified_validation = {
        "aggregated_score": round(trust_score, 2),
        "trust_band": trust_band,
        "contributing_models": pipeline_data.get("contributing_models", 0),
        "model_breakdown": pipeline_data.get("model_breakdown", {}),
        "validation_metadata": pipeline_data.get("validation_metadata", {}),
        "pipeline_version": "v2_5stage",
    }

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["unified_validation"] = unified_validation
    fv["pipeline_stages"] = pipeline_data.get("stage_results", {})
    report.feature_vector = _json_safe(fv)

    score_decimal = Decimal(f"{round(trust_score, 2):.2f}")
    label = infer_prediction_label_from_trust_score(trust_score)

    ml_prediction = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == report.report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if ml_prediction is not None:
        # Don't overwrite leader/human override scores (is_final=True)
        if getattr(ml_prediction, "is_final", False) and getattr(ml_prediction, "model_type", None) in ("leader_override", "human_override"):
            return unified_validation
        ml_prediction.trust_score = score_decimal
        ml_prediction.prediction_label = label
        explanation = ml_prediction.explanation if isinstance(ml_prediction.explanation, dict) else {}
        explanation["unified_validation"] = unified_validation
        ml_prediction.explanation = _json_safe(explanation)
        if hasattr(ml_prediction, "is_final"):
            ml_prediction.is_final = False
    else:
        db.add(MLPrediction(
            prediction_id=uuid4(),
            report_id=report.report_id,
            trust_score=score_decimal,
            prediction_label=label,
            confidence=Decimal("0.80"),
            model_type="unified_aggregation",
            is_final=False,
            explanation={"unified_validation": unified_validation},
            evaluated_at=datetime.now(timezone.utc),
        ))

    return unified_validation


def ensure_ml_prediction_from_unified(
    db: Session,
    report: Report,
    unified_validation: Optional[Dict[str, Any]],
) -> Optional[Any]:
    existing = resolve_ml_prediction_for_report(report)
    if existing is not None:
        return existing
    if not isinstance(unified_validation, dict):
        fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
        unified_validation = fv.get("unified_validation") if isinstance(fv.get("unified_validation"), dict) else None
    if not isinstance(unified_validation, dict):
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
    # 3-tier label: 70-100 likely_real, 40-69 suspicious, 0-39 fake
    # Score always determines the label — override any stale/mismatched label.
    if score is not None and score >= 70.0:
        label = "likely_real"
    elif score is not None and score >= 40.0:
        label = "suspicious"
    else:
        label = "fake"
    return score, label


# ── Outcome application ──────────────────────────────────────────────────────

def apply_threshold_outcome(report: Report, scorecard: Dict[str, Any]) -> None:
    """Apply scorecard to report status. Policy unchanged from previous version."""
    if not isinstance(scorecard, dict):
        return

    fv = getattr(report, "feature_vector", None) or {}
    if isinstance(fv, dict):
        leader_dec = (fv.get("leader_decision") or {})
        if isinstance(leader_dec, dict) and leader_dec.get("decision") == "rejected":
            report.rule_status = "rejected"
            report.verification_status = "rejected"
            report.status = "rejected"
            report.is_flagged = True
            if not getattr(report, "flag_reason", None):
                report.flag_reason = "rejected_by_local_leader"
            return

    band = str(scorecard.get("threshold_band") or "").lower()
    hard_gates = [str(g) for g in (scorecard.get("hard_gates") or [])]
    hard_set = {g.upper() for g in hard_gates}
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))
    flagged_for_review = is_flagged or rule_status == "flagged"

    hard_reject = (
        band == "hard_reject"
        or bool(hard_set & {c.upper() for c in HARD_GATE_REJECT_CODES})
    )
    if hard_reject:
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            if "LOCATION_OUT_OF_BOUNDARY" in hard_set or "BOUNDARY_REJECT" in hard_set:
                report.flag_reason = "out_of_musanze_boundary"
            else:
                report.flag_reason = "hard_rule_reject"
        return

    if rule_status == "rejected" and not flagged_for_review:
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        return

    if band == "confirmed_candidate":
        flag_reason_val = (getattr(report, "flag_reason", None) or "").strip().lower()
        content_mismatch = is_flagged and any(
            p in flag_reason_val
            for p in ("mismatch", "evidence_incident", "description_evidence",
                       "incident_description", "evidence_not_relevant", "contradictory", "unrelated")
        )
        if content_mismatch:
            if report.rule_status != "rejected":
                report.rule_status = "flagged"
                report.verification_status = "under_review"
                if report.status not in ("rejected",):
                    report.status = "pending"
            return
        if report.rule_status not in ("rejected",):
            report.rule_status = "passed"
            report.verification_status = "verified"
            report.is_flagged = False
            if report.status in {None, "", "pending", "flagged", "under_review"}:
                report.status = "verified"
        return

    if flagged_for_review:
        if report.rule_status != "rejected":
            report.verification_status = "under_review"
            if report.status not in ("rejected",):
                report.status = "pending"
        return

    if band == "low_confidence":
        # Score 0-39 → rejected
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            report.flag_reason = "threshold_low_score"
        return

    if band == "under_review":
        fv_ur = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
        sc_ur = fv_ur.get("threshold_scorecard") if isinstance(fv_ur.get("threshold_scorecard"), dict) else {}
        if sc_ur.get("evidence_all_failed"):
            report.rule_status = "rejected"
            report.verification_status = "rejected"
            report.status = "rejected"
            report.is_flagged = True
            if not getattr(report, "flag_reason", None):
                report.flag_reason = "evidence_does_not_match_incident"
            return
        if report.rule_status != "rejected":
            if report.rule_status not in {"flagged"}:
                report.rule_status = "passed"
            report.verification_status = "under_review"
            if report.status != "rejected":
                report.status = "pending"
        return


def reconcile_scorecard_with_unified_trust(
    scorecard: Dict[str, Any],
    unified_validation: Optional[Dict[str, Any]],
    *,
    has_evidence: bool,
) -> Dict[str, Any]:
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

    # 3-tier mapping: 70-100 verified, 40-69 under_review, 0-39 rejected
    if trust_band == TrustBand.HIGH_CONFIDENCE.value:
        band = "confirmed_candidate"
    elif trust_band == TrustBand.MEDIUM_CONFIDENCE.value:
        band = "under_review"
    else:
        # REJECT band (0-39)
        band = "low_confidence"

    scorecard["threshold_band"] = band
    scorecard["unified_band_aligned"] = True
    scorecard["unified_trust_band"] = trust_band
    return scorecard


# ── Legacy integrity checks ──────────────────────────────────────────────────

def run_integrity_checks_on_evidence(
    report: Report,
    evidence_metadata_list: List[dict],
) -> Tuple[List[str], bool]:
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
            screenshot_result = enhanced_screenshot_detection(filename=file_url, file_path=path)
            if screenshot_result.get("is_screenshot"):
                issues.append(f"Screenshot detected: {screenshot_result.get('details')}")
        except Exception as exc:
            logger.warning("Screenshot detection failed: %s", exc)
        try:
            timing_result = analyze_file_timing(file_path=path, file_created_at=evidence_meta.get("captured_at"))
            if timing_result.get("is_suspicious"):
                issues.append(f"Suspicious file timing: {timing_result.get('suspicious_reasons')}")
        except Exception as exc:
            logger.warning("Timing analysis failed: %s", exc)
        try:
            source_result = validate_evidence_source(filename=file_url, file_path=path)
            if not source_result.get("is_valid"):
                issues.append(f"Invalid evidence source: {source_result.get('suspicious_indicators')}")
        except Exception as exc:
            logger.warning("Source validation failed: %s", exc)

    if not issues:
        return issues, False

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["integrity_issues"] = issues
    report.feature_vector = _json_safe(fv)
    return issues, True


# ══════════════════════════════════════════════════════════════════════════════
# MAIN 5-STAGE PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

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
    Full 5-stage citizen report verification pipeline.

    Stage 1: Evidence Admissibility
    Stage 2: Incident Type ↔ Description (semantic)
    Stage 3: Description Quality
    Stage 4: Description ↔ Evidence (semantic)
    Stage 5: Dynamic Trust Score

    Invalid evidence → immediate rejection (Stage 1).
    Trust scoring only happens after Stages 1-4 pass.
    """
    import time

    # ── Respect leader/human final decisions ─────────────────────────────────
    ml_pred_check = resolve_ml_prediction_for_report(report)
    if (
        ml_pred_check is not None
        and getattr(ml_pred_check, "is_final", False)
        and getattr(ml_pred_check, "model_type", None) in ("leader_override", "human_override")
    ):
        ai_ts = float(ml_pred_check.trust_score) if ml_pred_check.trust_score is not None else None
        ai_lbl = getattr(ml_pred_check, "prediction_label", None)
        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status=report.rule_status or "passed",
            is_flagged=bool(report.is_flagged),
            flag_reason=report.flag_reason,
            priority=report.priority or "medium",
            ml_prediction=ml_pred_check,
            ai_trust_score=ai_ts, ai_label=ai_lbl,
            final_decision="ACCEPTED" if report.verification_status == "verified" else "REJECTED",
        )

    audit_trail: List[PipelineStageAudit] = []
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}

    # ── Boundary check ───────────────────────────────────────────────────────
    if skip_if_out_of_boundary and fv.get("boundary_status") == "out_of_musanze":
        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status=report.rule_status or "rejected",
            is_flagged=bool(report.is_flagged),
            flag_reason=report.flag_reason,
            priority=report.priority or "low",
            ml_prediction=resolve_ml_prediction_for_report(report),
            ai_trust_score=None, ai_label=None,
            final_decision="REJECTED",
        )

    # Load evidence
    if evidence_files is None:
        evidence_files = (
            db.query(EvidenceFile)
            .filter(EvidenceFile.report_id == report.report_id)
            .all()
        )
    evidence_count = len(evidence_files)
    has_evidence = evidence_count > 0
    description = (getattr(report, "description", None) or "").strip()
    reported_at = getattr(report, "reported_at", None)

    # Legacy integrity hints
    if evidence_metadata_list:
        _, should_flag = run_integrity_checks_on_evidence(report, evidence_metadata_list)
        if should_flag and report.rule_status != "rejected":
            report.is_flagged = True
            report.rule_status = "flagged"
            report.verification_status = "under_review"
            if not report.flag_reason:
                report.flag_reason = "evidence_integrity_check"

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 1: Evidence Admissibility
    # ══════════════════════════════════════════════════════════════════════════
    t0 = time.monotonic()
    from app.core.evidence_admissibility import run_evidence_admissibility

    stage1 = run_evidence_admissibility(evidence_files, reported_at)
    stage1_ms = round((time.monotonic() - t0) * 1000, 1)

    stage1_audit = PipelineStageAudit(
        stage=1, name="evidence_admissibility",
        decision="skip" if stage1.skipped else ("accept" if stage1.accepted else "reject"),
        score=stage1.admissibility_score,
        duration_ms=stage1_ms,
        details={
            "skipped": stage1.skipped,
            "reasons": stage1.reasons[:10],
            "per_evidence_count": len(stage1.per_evidence),
        },
    )
    audit_trail.append(stage1_audit)

    fv["stage_1_admissibility"] = {
        "accepted": stage1.accepted,
        "score": stage1.admissibility_score,
        "skipped": stage1.skipped,
        "reasons": stage1.reasons[:10],
    }

    # RULE: Invalid evidence → immediate rejection
    if has_evidence and not stage1.accepted:
        logger.warning(
            "Report %s REJECTED at Stage 1: evidence admissibility failed: %s",
            report.report_id, stage1.reasons,
        )
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = "invalid_evidence_admissibility_failure"
        fv["pipeline_decision"] = "REJECTED"
        fv["pipeline_rejection_stage"] = 1
        fv["pipeline_rejection_reason"] = "evidence_admissibility_failed"
        report.feature_vector = _json_safe(fv)

        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status="rejected", is_flagged=True,
            flag_reason="invalid_evidence_admissibility_failure",
            priority="low", ml_prediction=None,
            ai_trust_score=0.0, ai_label="fake",
            pipeline_audit=audit_trail, final_decision="REJECTED",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 2: Incident Type ↔ Description Validation (Semantic)
    # ══════════════════════════════════════════════════════════════════════════
    t0 = time.monotonic()
    from app.core.semantic_incident_validator import validate_incident_description

    stage2 = validate_incident_description(
        db, description, report.incident_type_id,
    )
    stage2_ms = round((time.monotonic() - t0) * 1000, 1)

    stage2_audit = PipelineStageAudit(
        stage=2, name="incident_description_validation",
        decision=stage2.decision,
        score=stage2.final_incident_match_score,
        duration_ms=stage2_ms,
        details={
            "embedding_similarity": stage2.embedding_similarity,
            "llm_match_score": stage2.llm_match_score,
            "incident_type": stage2.metadata.get("incident_type_name", ""),
        },
    )
    audit_trail.append(stage2_audit)

    fv["stage_2_incident_match"] = {
        "embedding_similarity": stage2.embedding_similarity,
        "llm_match_score": stage2.llm_match_score,
        "final_score": stage2.final_incident_match_score,
        "decision": stage2.decision,
        "metadata": stage2.metadata,
    }

    # RULE: Incident mismatch → reject
    if stage2.decision == "reject":
        logger.warning(
            "Report %s REJECTED at Stage 2: incident-description mismatch (score=%.1f)",
            report.report_id, stage2.final_incident_match_score,
        )
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = "incident_description_mismatch"
        fv["pipeline_decision"] = "REJECTED"
        fv["pipeline_rejection_stage"] = 2
        fv["pipeline_rejection_reason"] = "incident_description_semantic_mismatch"
        report.feature_vector = _json_safe(fv)

        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status="rejected", is_flagged=True,
            flag_reason="incident_description_mismatch",
            priority="low", ml_prediction=None,
            ai_trust_score=0.0, ai_label="fake",
            pipeline_audit=audit_trail, final_decision="REJECTED",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 3: Description Quality Analysis
    # ══════════════════════════════════════════════════════════════════════════
    t0 = time.monotonic()
    from app.core.description_quality_analyzer import (
        analyze_description_quality as analyze_desc_quality,
    )

    stage3 = analyze_desc_quality(description)
    stage3_ms = round((time.monotonic() - t0) * 1000, 1)

    stage3_audit = PipelineStageAudit(
        stage=3, name="description_quality",
        decision=stage3.decision,
        score=stage3.description_score,
        duration_ms=stage3_ms,
        details={
            "completeness": stage3.completeness,
            "clarity": stage3.clarity,
            "specificity": stage3.specificity,
            "consistency": stage3.consistency,
        },
    )
    audit_trail.append(stage3_audit)

    fv["stage_3_description_quality"] = {
        "description_score": stage3.description_score,
        "completeness": stage3.completeness,
        "clarity": stage3.clarity,
        "specificity": stage3.specificity,
        "consistency": stage3.consistency,
        "decision": stage3.decision,
        "metadata": stage3.metadata,
    }

    # Build backward-compatible text_only_validation
    text_only_validation = build_text_only_validation_from_stages(stage2, stage3)
    fv["text_only_validation"] = text_only_validation

    # RULE: Extremely poor description → reject
    if stage3.decision == "reject":
        logger.warning(
            "Report %s REJECTED at Stage 3: extremely poor description (score=%.1f)",
            report.report_id, stage3.description_score,
        )
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = "extremely_poor_description"
        fv["pipeline_decision"] = "REJECTED"
        fv["pipeline_rejection_stage"] = 3
        fv["pipeline_rejection_reason"] = "description_quality_below_minimum"
        report.feature_vector = _json_safe(fv)

        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status="rejected", is_flagged=True,
            flag_reason="extremely_poor_description",
            priority="low", ml_prediction=None,
            ai_trust_score=0.0, ai_label="fake",
            pipeline_audit=audit_trail, final_decision="REJECTED",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Run Volo/YOLO evidence analysis (needed for Stage 4)
    # ══════════════════════════════════════════════════════════════════════════
    from app.core.unified_validator import validate_report_unified

    validation_result = validate_report_unified(
        db=db, report=report, device=device,
        evidence_files=list(evidence_files or []),
    )

    # Merge Volo results into evidence validations
    validations = list(evidence_validations or [])
    if isinstance(report.feature_vector, dict) and report.feature_vector.get("evidence_validations"):
        validations = list(report.feature_vector.get("evidence_validations") or validations)
    validations = merge_volo_into_evidence_validations(
        validations, evidence_files, validation_result.volo_results,
    )
    if validations:
        fv["evidence_validations"] = validations

    report.feature_vector = _json_safe(fv)

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 4: Description ↔ Evidence Semantic Matching
    # ══════════════════════════════════════════════════════════════════════════
    t0 = time.monotonic()
    from app.core.description_evidence_matcher import match_description_to_evidence

    stage4 = match_description_to_evidence(description, validations)
    stage4_ms = round((time.monotonic() - t0) * 1000, 1)

    stage4_audit = PipelineStageAudit(
        stage=4, name="description_evidence_matching",
        decision="skip" if stage4.skipped else stage4.decision,
        score=stage4.evidence_match_score if not stage4.skipped else None,
        duration_ms=stage4_ms,
        details={
            "skipped": stage4.skipped,
            "support_level": stage4.support_level,
            "semantic_similarity": stage4.semantic_similarity,
        },
    )
    audit_trail.append(stage4_audit)

    fv["stage_4_evidence_match"] = {
        "semantic_similarity": stage4.semantic_similarity,
        "support_level": stage4.support_level,
        "evidence_match_score": stage4.evidence_match_score,
        "decision": stage4.decision,
        "skipped": stage4.skipped,
        "evidence_descriptions": stage4.evidence_descriptions,
        "metadata": stage4.metadata,
    }

    # RULE: Contradictory or unrelated evidence → reject
    if not stage4.skipped and stage4.decision == "reject":
        logger.warning(
            "Report %s REJECTED at Stage 4: evidence %s description (support=%s, score=%.1f)",
            report.report_id, stage4.support_level,
            stage4.support_level, stage4.evidence_match_score,
        )
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        report.flag_reason = f"evidence_{stage4.support_level}_to_description"
        fv["pipeline_decision"] = "REJECTED"
        fv["pipeline_rejection_stage"] = 4
        fv["pipeline_rejection_reason"] = f"evidence_{stage4.support_level}"
        report.feature_vector = _json_safe(fv)

        return VerificationPipelineResult(
            unified_validation={}, scorecard={},
            rule_status="rejected", is_flagged=True,
            flag_reason=f"evidence_{stage4.support_level}_to_description",
            priority="low", ml_prediction=None,
            ai_trust_score=0.0, ai_label="fake",
            pipeline_audit=audit_trail, final_decision="REJECTED",
        )

    # Flag weak evidence support
    if not stage4.skipped and stage4.decision == "flag":
        report.is_flagged = True
        if report.rule_status != "rejected":
            report.rule_status = "flagged"
        report.verification_status = "under_review"
        if not report.flag_reason:
            report.flag_reason = f"weak_evidence_support_{stage4.support_level}"

    # ══════════════════════════════════════════════════════════════════════════
    # STAGE 5: Dynamic Trust Score Computation
    # ══════════════════════════════════════════════════════════════════════════
    t0 = time.monotonic()
    from app.core.dynamic_trust_scorer import compute_dynamic_trust_score

    # Get reporter history score from TrustBond XGBoost
    trustbond_score = None
    if validation_result.trustbond_score is not None:
        trustbond_score = validation_result.trustbond_score

    stage5 = compute_dynamic_trust_score(
        incident_match_score=stage2.final_incident_match_score,
        description_quality_score=stage3.description_score,
        evidence_match_score=stage4.evidence_match_score if not stage4.skipped else None,
        evidence_admissibility_score=stage1.admissibility_score if not stage1.skipped else None,
        reporter_history_score=trustbond_score,
        community_votes=community_votes_from_report(report),
        gps_accuracy=float(getattr(report, "gps_accuracy", 0) or 0),
        movement_speed=float(getattr(report, "movement_speed", 0) or 0),
        was_stationary=getattr(report, "was_stationary", None),
        has_evidence=has_evidence,
    )
    stage5_ms = round((time.monotonic() - t0) * 1000, 1)

    stage5_audit = PipelineStageAudit(
        stage=5, name="dynamic_trust_score",
        decision=stage5.decision,
        score=stage5.trust_score,
        duration_ms=stage5_ms,
        details={
            "trust_band": stage5.trust_band,
            "components": {c.name: c.contribution for c in stage5.components},
        },
    )
    audit_trail.append(stage5_audit)

    fv["stage_5_trust_score"] = {
        "trust_score": stage5.trust_score,
        "trust_band": stage5.trust_band,
        "decision": stage5.decision,
        "components": [
            {
                "name": c.name,
                "raw_score": c.raw_score,
                "weight": c.weight,
                "normalized_weight": c.normalized_weight,
                "contribution": c.contribution,
                "available": c.available,
            }
            for c in stage5.components
        ],
        "metadata": stage5.metadata,
    }

    # Build model_breakdown for backward compatibility
    model_breakdown = {}
    for c in stage5.components:
        model_breakdown[c.name] = {
            "raw_score": c.raw_score,
            "contribution": c.contribution,
            "is_valid": c.available,
            "metadata": c.metadata,
        }

    pipeline_data = {
        "contributing_models": sum(1 for c in stage5.components if c.available),
        "model_breakdown": model_breakdown,
        "validation_metadata": {
            "pipeline_version": "v2_5stage",
            "stages_completed": len(audit_trail),
            "total_duration_ms": sum(a.duration_ms or 0 for a in audit_trail),
        },
        "stage_results": {
            f"stage_{a.stage}": {
                "name": a.name,
                "decision": a.decision,
                "score": a.score,
            }
            for a in audit_trail
        },
    }

    unified_validation = store_pipeline_trust_score(
        db, report, stage5.trust_score, pipeline_data,
    )

    # ── Anti-fraud rules ─────────────────────────────────────────────────────
    rule_status, is_flagged, flag_reason = apply_anti_fraud_rules(report, evidence_count, db)
    if report.rule_status != "rejected":
        report.rule_status = rule_status
    report.is_flagged = bool(report.is_flagged or is_flagged)
    if is_flagged and flag_reason and not report.flag_reason:
        report.flag_reason = flag_reason
    if report.is_flagged and report.rule_status != "rejected":
        report.verification_status = "under_review"

    # ── Priority ─────────────────────────────────────────────────────────────
    priority = calculate_report_priority(report, evidence_count, db, unified_validation)
    report.priority = priority

    # ── Scorecard (backward compat) ──────────────────────────────────────────
    # Save fv first so compute_scorecard_fn can see stage_5_trust_score
    report.feature_vector = _json_safe(fv)

    votes = community_votes_from_report(report)
    ml_prediction = resolve_ml_prediction_for_report(report)
    scorecard = compute_scorecard_fn(
        report,
        ml_prediction=ml_prediction,
        community_votes=votes,
        unified_validation=unified_validation,
    )
    scorecard = reconcile_scorecard_with_unified_trust(
        scorecard, unified_validation, has_evidence=has_evidence,
    )
    # Use the local `fv` dict which has all stage data (stage_5_trust_score, etc.)
    # instead of re-reading from report.feature_vector which may be a stale copy.
    fv["threshold_scorecard"] = scorecard
    fv["pipeline_audit"] = [
        {"stage": a.stage, "name": a.name, "decision": a.decision,
         "score": a.score, "duration_ms": a.duration_ms}
        for a in audit_trail
    ]
    fv["pipeline_decision"] = stage5.decision
    report.feature_vector = _json_safe(fv)

    apply_threshold_outcome(report, scorecard)

    # ── ML prediction finalization ───────────────────────────────────────────
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

    # ── Narratives ───────────────────────────────────────────────────────────
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

    # Determine final pipeline decision
    final_decision = stage5.decision
    if report.verification_status == "rejected":
        final_decision = "REJECTED"
    elif report.verification_status == "under_review":
        final_decision = "FLAGGED_FOR_REVIEW"
    elif report.verification_status == "verified":
        final_decision = "ACCEPTED"

    logger.info(
        "Pipeline complete for report %s: trust=%.2f decision=%s stages=%d",
        report.report_id, stage5.trust_score, final_decision, len(audit_trail),
    )

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
        pipeline_audit=audit_trail,
        final_decision=final_decision,
    )


# ── Backward-compatible exports ──────────────────────────────────────────────

def rerun_scorecard_and_outcome(
    db: Session,
    report: Report,
    device: Device,
    *,
    compute_scorecard_fn: Callable[..., Dict[str, Any]],
    respect_human_final: bool = True,
) -> Dict[str, Any]:
    """Recompute scorecard + outcome after community votes or evidence changes."""
    ml_prediction = resolve_ml_prediction_for_report(report)
    if (
        respect_human_final
        and ml_prediction is not None
        and getattr(ml_prediction, "is_final", False)
        and getattr(ml_prediction, "model_type", None) in ("human_override", "leader_override")
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
        report, ml_prediction=ml_prediction,
        community_votes=community_votes_from_report(report),
        unified_validation=unified_validation or None,
    )
    scorecard = reconcile_scorecard_with_unified_trust(
        scorecard, unified_validation, has_evidence=has_evidence,
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


def process_backlog_report(
    db: Session,
    report: Report,
    *,
    compute_scorecard_fn: Callable[..., Dict[str, Any]],
    compose_narratives_fn: Optional[Callable[..., None]] = None,
) -> bool:
    """Run unified pipeline for stale pending rows."""
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
        db, report, device,
        evidence_files=evidence_files,
        evidence_validations=validations,
        compute_scorecard_fn=compute_scorecard_fn,
        compose_narratives_fn=compose_narratives_fn,
    )
    report.ai_ready = True
    report.features_extracted_at = datetime.now(timezone.utc)
    return True


# ── Legacy exports (backward compat for apply_evidence_semantic_checks) ──────

def apply_evidence_semantic_checks(
    db: Session,
    report: Report,
    *,
    description: Optional[str] = None,
    skip_if_rejected: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Legacy: triple alignment check. Now handled by Stage 4 in the pipeline.
    Kept for callers outside the main pipeline.
    """
    if skip_if_rejected and (getattr(report, "rule_status", None) or "").strip().lower() == "rejected":
        return None

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []
    if not validations:
        return None

    desc_text = (description if description is not None else getattr(report, "description", None)) or ""

    try:
        from app.core.description_evidence_matcher import match_description_to_evidence
        result = match_description_to_evidence(desc_text, validations)

        if not result.skipped:
            semantic_result = {
                "model": "pipeline_v2_stage4",
                "description_evidence_similarity": round(result.semantic_similarity / 100.0, 4),
                "support_level": result.support_level,
                "evidence_match_score": result.evidence_match_score,
                "mismatch": result.decision == "reject",
            }
            fv["semantic_alignment"] = semantic_result

            if result.decision == "reject":
                report.rule_status = "flagged"
                report.is_flagged = True
                report.verification_status = "under_review"
                if not report.flag_reason:
                    report.flag_reason = f"evidence_{result.support_level}_to_description"

            report.feature_vector = _json_safe(fv)
            return semantic_result
    except Exception as exc:
        logger.warning("Evidence semantic checks failed: %s", exc)

    return None


# Legacy store function — still used by some callers
def store_unified_validation_result(
    db: Session,
    report: Report,
    validation_result: Any,
) -> Dict[str, Any]:
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
    return unified_validation
