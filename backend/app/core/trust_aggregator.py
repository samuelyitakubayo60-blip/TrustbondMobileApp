"""
Central Trust Aggregator
Combines scores from all models into a unified trust score.
No model makes final decisions - only contributes scores.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from .trust_thresholds import trust_thresholds, TrustBand, ModelWeights
from app.models.report import Report
from app.models.device import Device

logger = logging.getLogger(__name__)

@dataclass
class ModelScore:
    """Individual model contribution to trust score."""
    model_name: str
    raw_score: float  # 0-100 scale
    confidence: float  # 0.0-1.0 scale
    weight: float
    contribution: float  # Final weighted contribution
    is_valid: bool
    metadata: Dict[str, Any]

@dataclass
class AggregatedTrust:
    """Final aggregated trust result."""
    total_score: float
    trust_band: TrustBand
    model_scores: List[ModelScore]
    contributing_models: int
    base_score: float
    weighted_sum: float
    metadata: Dict[str, Any]

class TrustAggregator:
    """Central aggregator for trust scores from all models."""
    
    def __init__(self):
        self.thresholds = trust_thresholds
        self.weights = self.thresholds.get_model_weights()
    
    def aggregate_trust_scores(
        self,
        report: Report,
        device: Device,
        trustbond_score: Optional[float] = None,
        natural_language_score: Optional[float] = None,
        volo_score: Optional[float] = None,
        model_metadata: Optional[Dict[str, Any]] = None
    ) -> AggregatedTrust:
        """
        Aggregate trust scores from all models into unified trust score.
        Implements dynamic weight redistribution when models are missing.
        
        Args:
            report: Report object
            device: Device object  
            trustbond_score: TrustBond model credibility score (0-100)
            natural_language_score: Natural language model score (0-100)
            volo_score: Volo evidence analysis score (0-100)
            model_metadata: Additional metadata from models
            
        Returns:
            AggregatedTrust with final score and breakdown
        """
        model_scores = []
        metadata = model_metadata or {}
        
        # Determine which models are available
        available_models = {
            'trustbond': trustbond_score is not None,
            'natural_language': natural_language_score is not None,
            'volo': volo_score is not None
        }
        
        # Calculate dynamic weights (redistribute missing model weights)
        dynamic_weights = self._calculate_dynamic_weights(available_models)
        
        # 1. Process TrustBond Model Score (Location, Device, GPS validation)
        if available_models['trustbond']:
            trustbond_contribution = self._process_trustbond_score(
                trustbond_score, metadata.get('trustbond', {}), dynamic_weights['trustbond']
            )
            if trustbond_contribution:
                model_scores.append(trustbond_contribution)
        
        # 2. Process Natural Language Model Score (Description quality, semantic analysis)
        if available_models['natural_language']:
            nl_contribution = self._process_natural_language_score(
                natural_language_score, metadata.get('natural_language', {}), dynamic_weights['natural_language']
            )
            if nl_contribution:
                model_scores.append(nl_contribution)
        
        # 3. Process Volo Model Score (Evidence quality, object detection)
        if available_models['volo']:
            volo_contribution = self._process_volo_score(
                volo_score, metadata.get('volo', {}), dynamic_weights['volo']
            )
            if volo_contribution:
                model_scores.append(volo_contribution)
        
        # 4. Add base score (starting point for all reports)
        base_score = dynamic_weights['base_score'] * 100
        base_contribution = ModelScore(
            model_name="base",
            raw_score=base_score,
            confidence=1.0,
            weight=dynamic_weights['base_score'],
            contribution=base_score,
            is_valid=True,
            metadata={"reason": "base_credibility_start"}
        )
        model_scores.append(base_contribution)
        
        # 5. Calculate final aggregated score
        final_score = self._calculate_final_score(model_scores)
        
        # 6. Determine trust band
        trust_band = self.thresholds.get_trust_band(final_score)
        
        # 7. Create result
        contributing_models = len([s for s in model_scores if s.is_valid and s.model_name != "base"])
        
        return AggregatedTrust(
            total_score=final_score,
            trust_band=trust_band,
            model_scores=model_scores,
            contributing_models=contributing_models,
            base_score=base_score,
            weighted_sum=sum(s.contribution for s in model_scores if s.is_valid),
            metadata={
                "aggregated_at": datetime.now(timezone.utc).isoformat(),
                "available_models": available_models,
                "original_weights": {
                    "trustbond": self.weights.trustbond,
                    "natural_language": self.weights.natural_language,
                    "volo": self.weights.volo,
                    "base_score": self.weights.base_score
                },
                "dynamic_weights": dynamic_weights,
                "thresholds_applied": {
                    "min_models_for_trust": self.thresholds.config.MIN_MODELS_FOR_TRUST,
                    "max_contribution_per_model": self.thresholds.config.MAX_CONTRIBUTIONS_PER_MODEL
                }
            }
        )
    
    def _calculate_dynamic_weights(self, available_models: Dict[str, bool]) -> Dict[str, float]:
        """
        Calculate dynamic weights by redistributing missing model weights.
        
        Examples:
        - All models available: trustbond=0.4, natural_language=0.3, volo=0.2, base=0.1
        - No evidence (volo missing): trustbond=0.45, natural_language=0.35, base=0.2
        - No description (NL missing): trustbond=0.5, volo=0.3, base=0.2
        - Only TrustBond available: trustbond=0.7, base=0.3
        """
        original_weights = {
            'trustbond': self.weights.trustbond,
            'natural_language': self.weights.natural_language,
            'volo': self.weights.volo,
            'base_score': self.weights.base_score
        }
        
        # Find missing models (excluding base_score)
        missing_main_models = [model for model, available in available_models.items() 
                              if not available and model != 'base_score']
        
        if not missing_main_models:
            # All models available, return original weights
            return original_weights

        # No evidence case: use strict 50/50 between TrustBond and NL, no base/VOLO share.
        if (
            not available_models.get('volo', False)
            and available_models.get('trustbond', False)
            and available_models.get('natural_language', False)
        ):
            return {
                'trustbond': 0.5,
                'natural_language': 0.5,
                'volo': 0.0,
                'base_score': 0.0,
            }
        
        # Calculate total weight to redistribute from missing main models
        missing_weight = sum(original_weights[model] for model in missing_main_models)
        
        # Count available main models (trustbond, natural_language, volo)
        available_main_models = [model for model, available in available_models.items() 
                                if available and model != 'base_score']
        
        if not available_main_models:
            # Only base_score available
            return {'base_score': 1.0, 'trustbond': 0.0, 'natural_language': 0.0, 'volo': 0.0}
        
        # Start with original weights
        dynamic_weights = original_weights.copy()
        
        # Set missing main models to 0
        for model in missing_main_models:
            dynamic_weights[model] = 0.0
        
        # Redistribute missing weight equally among available main models AND base_score
        # This matches the examples: missing weight is shared by available models + base
        total_recipients = len(available_main_models) + 1  # +1 for base_score
        redistribution_per_recipient = missing_weight / total_recipients
        
        # Add redistributed weight to available main models
        for model in available_main_models:
            dynamic_weights[model] += redistribution_per_recipient
        
        # Add redistributed weight to base_score
        dynamic_weights['base_score'] += redistribution_per_recipient
        
        # Ensure weights sum to 1.0 (normalize if needed)
        total = sum(dynamic_weights.values())
        if abs(total - 1.0) > 0.001:
            dynamic_weights = {k: v/total for k, v in dynamic_weights.items()}
        
        return dynamic_weights
    
    def _process_trustbond_score(self, score: Optional[float], metadata: Dict[str, Any], dynamic_weight: float) -> Optional[ModelScore]:
        """Process TrustBond model score."""
        if score is None:
            return None
        
        is_valid = self.thresholds.is_model_contribution_valid("trustbond", score)
        if not is_valid:
            logger.warning(f"TrustBond score {score} below minimum threshold")
            return None
        
        # Clamp contribution to prevent domination
        raw_contribution = score * dynamic_weight
        contribution = self.thresholds.clamp_model_contribution(raw_contribution)
        
        return ModelScore(
            model_name="trustbond",
            raw_score=score,
            confidence=metadata.get('confidence', 0.8),
            weight=dynamic_weight,
            contribution=contribution,
            is_valid=True,
            metadata={
                "focus": "location_device_gps_validation",
                "feature_importance": metadata.get('feature_importance', {}),
                "model_version": metadata.get('model_version', 'unknown'),
                "prediction_factors": metadata.get('prediction_factors', [])
            }
        )
    
    def _process_natural_language_score(self, score: Optional[float], metadata: Dict[str, Any], dynamic_weight: float) -> Optional[ModelScore]:
        """Process Natural Language model score."""
        if score is None:
            return None
        
        is_valid = self.thresholds.is_model_contribution_valid("natural_language", score)
        if not is_valid:
            logger.warning(f"Natural Language score {score} below minimum threshold")
            return None
        
        # Clamp contribution to prevent domination
        raw_contribution = score * dynamic_weight
        contribution = self.thresholds.clamp_model_contribution(raw_contribution)
        
        return ModelScore(
            model_name="natural_language",
            raw_score=score,
            confidence=metadata.get('confidence', 0.7),
            weight=dynamic_weight,
            contribution=contribution,
            is_valid=True,
            metadata={
                "focus": "description_quality_semantic_analysis",
                "semantic_similarity": metadata.get('semantic_similarity', 0.0),
                "description_quality": metadata.get('description_quality', {}),
                "language_detected": metadata.get('language_detected', 'unknown'),
                "incident_type_match": metadata.get('incident_type_match', False)
            }
        )
    
    def _process_volo_score(self, score: Optional[float], metadata: Dict[str, Any], dynamic_weight: float) -> Optional[ModelScore]:
        """Process Volo model score."""
        if score is None:
            return None
        
        is_valid = self.thresholds.is_model_contribution_valid("volo", score)
        if not is_valid:
            logger.warning(f"Volo score {score} below minimum threshold")
            return None
        
        # Clamp contribution to prevent domination
        raw_contribution = score * dynamic_weight
        contribution = self.thresholds.clamp_model_contribution(raw_contribution)
        
        return ModelScore(
            model_name="volo",
            raw_score=score,
            confidence=metadata.get('confidence', 0.6),
            weight=dynamic_weight,
            contribution=contribution,
            is_valid=True,
            metadata={
                "focus": "evidence_quality_object_detection",
                "objects_detected": metadata.get('objects_detected', []),
                "evidence_authenticity": metadata.get('evidence_authenticity', {}),
                "image_quality": metadata.get('image_quality', {}),
                "tamper_detection": metadata.get('tamper_detection', {})
            }
        )
    
    def _calculate_final_score(self, model_scores: List[ModelScore]) -> float:
        """Calculate final trust score from model contributions."""
        if not model_scores:
            return 0.0
        
        # Sum all valid contributions
        total_score = sum(s.contribution for s in model_scores if s.is_valid)
        
        # Apply minimum model requirement
        contributing_models = len([s for s in model_scores if s.is_valid and s.model_name != "base"])
        if contributing_models < self.thresholds.config.MIN_MODELS_FOR_TRUST:
            # Penalize for insufficient model contributions
            penalty = (self.thresholds.config.MIN_MODELS_FOR_TRUST - contributing_models) * 10
            total_score = max(0.0, total_score - penalty)
            logger.warning(f"Insufficient model contributions: {contributing_models}, applying penalty: {penalty}")
        
        # Ensure score is within bounds
        return max(0.0, min(100.0, total_score))
    
    def should_auto_verify(self, aggregated_trust: AggregatedTrust) -> bool:
        """Determine if report should be auto-verified based on aggregated trust."""
        return (
            aggregated_trust.trust_band == TrustBand.HIGH_CONFIDENCE and
            aggregated_trust.contributing_models >= self.thresholds.config.MIN_MODELS_FOR_TRUST
        )
    
    def should_flag_for_review(self, aggregated_trust: AggregatedTrust) -> bool:
        """Determine if report should be flagged for human review."""
        return (
            aggregated_trust.trust_band in [TrustBand.MEDIUM_CONFIDENCE, TrustBand.LOW_CONFIDENCE] or
            aggregated_trust.contributing_models < self.thresholds.config.MIN_MODELS_FOR_TRUST
        )
    
    def should_reject(self, aggregated_trust: AggregatedTrust) -> bool:
        """Determine if report should be rejected."""
        return aggregated_trust.trust_band == TrustBand.REJECT

# Global instance
trust_aggregator = TrustAggregator()

# Export main function for easy access
def aggregate_trust_scores(
    report: Report,
    device: Device,
    trustbond_score: Optional[float] = None,
    natural_language_score: Optional[float] = None,
    volo_score: Optional[float] = None,
    model_metadata: Optional[Dict[str, Any]] = None
) -> AggregatedTrust:
    """Convenience function for trust aggregation."""
    return trust_aggregator.aggregate_trust_scores(
        report=report,
        device=device,
        trustbond_score=trustbond_score,
        natural_language_score=natural_language_score,
        volo_score=volo_score,
        model_metadata=model_metadata
    )
