"""
Unified Trust Validator
Integrates all models (TrustBond, Natural Language, Volo) with the central aggregator.
Replaces the old fragmented validation approach.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from .trust_aggregator import aggregate_trust_scores, AggregatedTrust, TrustBand
from .natural_language_scorer import analyze_description_quality, NLAnalysisResult
from .volo_scorer import (
    analyze_evidence_audio_content,
    analyze_evidence_content,
    analyze_evidence_video_content,
    VoloAnalysisResult,
)
from .credibility_model import score_report_credibility
from .trust_thresholds import trust_thresholds
from app.models.report import Report
from app.models.device import Device
from app.models.evidence_file import EvidenceFile
from app.models.ml_prediction import MLPrediction
from app.models.incident_type import IncidentType

logger = logging.getLogger(__name__)


def _incident_type_context(report: Report) -> str:
    """Name + DB description for Volo relevance (replaces name-only MiniLM-era context)."""
    if not report.incident_type:
        return ""
    name = (report.incident_type.type_name or "").strip()
    desc = (report.incident_type.description or "").strip()
    if name and desc:
        return f"{name}: {desc}"
    return name or desc


@dataclass
class ValidationResult:
    """Result of unified validation."""
    aggregated_trust: AggregatedTrust
    trustbond_score: Optional[float]
    natural_language_result: Optional[NLAnalysisResult]
    volo_results: List[VoloAnalysisResult]
    validation_metadata: Dict[str, Any]

class UnifiedValidator:
    """Unified validator that coordinates all models and aggregation."""
    
    def __init__(self):
        self.thresholds = trust_thresholds
    
    def validate_report(
        self,
        db: Session,
        report: Report,
        device: Device,
        evidence_files: Optional[List[EvidenceFile]] = None
    ) -> ValidationResult:
        """
        Perform unified validation using all models.
        
        Args:
            db: Database session
            report: Report to validate
            device: Device that submitted the report
            evidence_files: List of evidence files (optional)
            
        Returns:
            ValidationResult with all model scores and aggregated result
        """
        logger.info(f"Starting unified validation for report {report.report_id}")
        
        # Initialize scores
        trustbond_score = None
        natural_language_result = None
        volo_results = []
        
        # 1. Run TrustBond model (historical patterns)
        try:
            evidence_count = len(evidence_files) if evidence_files else 0
            score_report_credibility(db, report, device, evidence_count)
            
            # Get the score from the prediction
            ml_prediction = db.query(MLPrediction).filter(
                MLPrediction.report_id == report.report_id,
                MLPrediction.model_type == "xgboost"
            ).first()
            
            if ml_prediction and ml_prediction.trust_score is not None:
                trustbond_score = float(ml_prediction.trust_score)
                logger.info(f"TrustBond score: {trustbond_score:.2f}")
            
        except Exception as exc:
            logger.warning(f"TrustBond scoring failed: {exc}")
        
        # 2. Run Natural Language model (description analysis)
        try:
            incident_type_name = ""
            incident_type_description = ""
            
            if report.incident_type:
                incident_type_name = report.incident_type.type_name or ""
                incident_type_description = report.incident_type.description or ""
            
            natural_language_result = analyze_description_quality(
                description=report.description or "",
                incident_type_name=incident_type_name,
                incident_type_description=incident_type_description
            )
            logger.info(f"Natural Language score: {natural_language_result.overall_score:.2f}")
            
        except Exception as exc:
            logger.warning(f"Natural Language analysis failed: {exc}")
        
        # 3. Run Volo model (evidence analysis) - only if evidence exists
        if evidence_files:
            for evidence_file in evidence_files:
                if not evidence_file.file_url:
                    continue
                ft = (evidence_file.file_type or "").strip().lower()
                is_photo = ft == "photo" or ft.startswith("image/")
                is_video = ft == "video" or ft.startswith("video/")
                is_audio = ft == "audio" or ft.startswith("audio/")
                if not (is_photo or is_video or is_audio):
                    continue
                try:
                    incident_context = _incident_type_context(report)

                    if is_photo:
                        volo_result = analyze_evidence_content(
                            image_url=evidence_file.file_url,
                            incident_type_name=incident_context,
                        )
                    elif is_video:
                        volo_result = analyze_evidence_video_content(
                            video_url=evidence_file.file_url,
                            incident_type_name=incident_context,
                        )
                    else:
                        volo_result = analyze_evidence_audio_content(
                            audio_url=evidence_file.file_url,
                            incident_type_name=incident_context,
                        )

                    volo_results.append(volo_result)
                    logger.info(
                        "Volo score for evidence %s (%s): %.2f",
                        evidence_file.evidence_id,
                        ft,
                        volo_result.overall_score,
                    )

                except Exception as exc:
                    logger.warning(
                        "Volo analysis failed for evidence %s: %s",
                        evidence_file.evidence_id,
                        exc,
                    )
        
        # Calculate average Volo score if multiple pieces of evidence
        volo_score = None
        if volo_results:
            volo_score = sum(r.overall_score for r in volo_results) / len(volo_results)
        
        # 4. Aggregate all scores using central aggregator
        try:
            aggregated_trust = aggregate_trust_scores(
                report=report,
                device=device,
                trustbond_score=trustbond_score,
                natural_language_score=natural_language_result.overall_score if natural_language_result else None,
                volo_score=volo_score,
                model_metadata={
                    "trustbond": {
                        "confidence": 0.8,
                        "model_version": "trustbond_v2_no_desc_length"
                    },
                    "natural_language": {
                        "confidence": natural_language_result.confidence if natural_language_result else 0.0,
                        "semantic_similarity": natural_language_result.semantic_similarity_score if natural_language_result else 0.0,
                        "description_quality": natural_language_result.description_quality_score if natural_language_result else 0.0
                    },
                    "volo": {
                        "confidence": sum(r.confidence for r in volo_results) / len(volo_results) if volo_results else 0.0,
                        "evidence_count": len(volo_results),
                        "objects_detected": list(set(obj for r in volo_results for obj in r.metadata.get("detection_analysis", {}).get("detected_objects", [])))
                    }
                }
            )
            
            logger.info(f"Aggregated trust score: {aggregated_trust.total_score:.2f} ({aggregated_trust.trust_band.value})")
            
        except Exception as exc:
            logger.error(f"Trust aggregation failed: {exc}")
            # Create fallback result
            aggregated_trust = self._create_fallback_aggregation(trustbond_score, natural_language_result, volo_results)
        
        # 5. Create validation metadata
        validation_metadata = {
            "validation_completed_at": datetime.now(timezone.utc).isoformat(),
            "models_used": {
                "trustbond": trustbond_score is not None,
                "natural_language": natural_language_result is not None,
                "volo": len(volo_results) > 0
            },
            "evidence_analyzed": len(volo_results),
            "validation_version": "unified_v1.0"
        }
        
        return ValidationResult(
            aggregated_trust=aggregated_trust,
            trustbond_score=trustbond_score,
            natural_language_result=natural_language_result,
            volo_results=volo_results,
            validation_metadata=validation_metadata
        )
    
    def apply_validation_results(
        self,
        db: Session,
        report: Report,
        validation_result: ValidationResult
    ) -> None:
        """
        Apply validation metadata only.
        Final label and report status are decided in API orchestration.
        
        Args:
            db: Database session
            report: Report to update
            validation_result: Validation results to apply
        """
        aggregated = validation_result.aggregated_trust
        
        # Persist aggregated trust score as model contribution only.
        ml_prediction = db.query(MLPrediction).filter(
            MLPrediction.report_id == report.report_id,
            MLPrediction.model_type == "xgboost"
        ).first()
        
        if ml_prediction:
            ml_prediction.trust_score = aggregated.total_score
            ml_prediction.evaluated_at = datetime.now(timezone.utc)
        
        # Store validation metadata in feature_vector
        feature_vector = getattr(report, 'feature_vector', {}) or {}
        feature_vector.update({
            "unified_validation": {
                "aggregated_score": aggregated.total_score,
                "trust_band": aggregated.trust_band.value,
                "contributing_models": aggregated.contributing_models,
                "model_breakdown": {
                    score.model_name: {
                        "raw_score": score.raw_score,
                        "contribution": score.contribution,
                        "is_valid": score.is_valid
                    } for score in aggregated.model_scores
                },
                "validation_metadata": validation_result.validation_metadata
            }
        })
        
        # Import the json_safe function
        from .credibility_model import _json_safe
        report.feature_vector = _json_safe(feature_vector)
        
        logger.info(f"Applied validation metadata to report {report.report_id}")
    
    def _create_fallback_aggregation(
        self,
        trustbond_score: Optional[float],
        natural_language_result: Optional[NLAnalysisResult],
        volo_results: List[VoloAnalysisResult]
    ) -> AggregatedTrust:
        """Create fallback aggregation when main aggregator fails."""
        from .trust_aggregator import ModelScore, TrustBand
        
        model_scores = []
        
        # Add base score
        base_score = ModelScore(
            model_name="base",
            raw_score=10.0,
            confidence=1.0,
            weight=0.1,
            contribution=10.0,
            is_valid=True,
            metadata={"fallback": True}
        )
        model_scores.append(base_score)
        
        # Add available model scores
        if trustbond_score is not None:
            model_scores.append(ModelScore(
                model_name="trustbond",
                raw_score=trustbond_score,
                confidence=0.5,
                weight=0.4,
                contribution=min(trustbond_score * 0.4, 40.0),
                is_valid=True,
                metadata={"fallback": True}
            ))
        
        if natural_language_result is not None:
            model_scores.append(ModelScore(
                model_name="natural_language",
                raw_score=natural_language_result.overall_score,
                confidence=natural_language_result.confidence,
                weight=0.3,
                contribution=min(natural_language_result.overall_score * 0.3, 40.0),
                is_valid=True,
                metadata={"fallback": True}
            ))
        
        if volo_results:
            avg_volo_score = sum(r.overall_score for r in volo_results) / len(volo_results)
            model_scores.append(ModelScore(
                model_name="volo",
                raw_score=avg_volo_score,
                confidence=0.4,
                weight=0.2,
                contribution=min(avg_volo_score * 0.2, 40.0),
                is_valid=True,
                metadata={"fallback": True}
            ))
        
        total_score = sum(s.contribution for s in model_scores if s.is_valid)
        trust_band = self.thresholds.get_trust_band(total_score)
        
        return AggregatedTrust(
            total_score=total_score,
            trust_band=trust_band,
            model_scores=model_scores,
            contributing_models=len([s for s in model_scores if s.is_valid and s.model_name != "base"]),
            base_score=10.0,
            weighted_sum=total_score,
            metadata={"fallback": True, "fallback_reason": "aggregation_failed"}
        )

# Global instance
unified_validator = UnifiedValidator()

# Export main function for easy access
def validate_report_unified(
    db: Session,
    report: Report,
    device: Device,
    evidence_files: Optional[List[EvidenceFile]] = None
) -> ValidationResult:
    """Convenience function for unified validation."""
    return unified_validator.validate_report(
        db=db,
        report=report,
        device=device,
        evidence_files=evidence_files
    )
