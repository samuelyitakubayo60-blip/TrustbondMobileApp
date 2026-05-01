"""
Centralized Trust Threshold Configuration
Single source of truth for all model thresholds and weights.
"""

from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum

class TrustBand(Enum):
    """Trust score bands for consistent classification across all models."""
    HIGH_CONFIDENCE = "high_confidence"
    MEDIUM_CONFIDENCE = "medium_confidence" 
    LOW_CONFIDENCE = "low_confidence"
    REJECT = "reject"

@dataclass
class ModelWeights:
    """Weights for each model in the final trust calculation."""
    trustbond: float = 0.4      # Historical patterns credibility
    natural_language: float = 0.3  # Semantic and description quality
    volo: float = 0.2           # Evidence authenticity
    base_score: float = 0.1     # Base credibility starting point

@dataclass 
class ThresholdConfig:
    """Centralized threshold configuration for all models."""
    
    # Trust Score Bands (0-100 scale)
    HIGH_TRUST_MIN: float = 70.0
    MEDIUM_TRUST_MIN: float = 45.0
    LOW_TRUST_MIN: float = 20.0
    REJECT_MAX: float = 20.0
    
    # Individual Model Thresholds
    TRUSTBOND_MIN_SCORE: float = 30.0  # Minimum credibility score to contribute
    NATURAL_LANGUAGE_MIN_SIMILARITY: float = 0.42  # Semantic similarity threshold
    VOLO_MIN_CONFIDENCE: float = 0.3   # Minimum object detection confidence
    
    # Description Quality Thresholds (Natural Language model only)
    DESCRIPTION_MIN_LENGTH: int = 20
    DESCRIPTION_ADEQUATE_LENGTH: int = 50
    DESCRIPTION_MAX_LENGTH: int = 1000
    
    # Evidence Quality Thresholds (Volo model only)
    EVIDENCE_MIN_BLUR_SCORE: float = 100.0
    EVIDENCE_MIN_BRIGHTNESS: float = 0.1
    EVIDENCE_MAX_BRIGHTNESS: float = 0.9
    
    # Aggregation Weights
    WEIGHTS = ModelWeights()
    
    # Validation Rules
    MIN_MODELS_FOR_TRUST: int = 2  # Minimum models that must contribute
    MAX_CONTRIBUTIONS_PER_MODEL: float = 40.0  # Max points any single model can contribute

class TrustThresholds:
    """Centralized trust threshold management."""
    
    def __init__(self, config: ThresholdConfig = None):
        self.config = config or ThresholdConfig()
        self._validate_weights()
    
    def _validate_weights(self):
        """Ensure model weights sum to 1.0."""
        total = (
            self.config.WEIGHTS.trustbond + 
            self.config.WEIGHTS.natural_language + 
            self.config.WEIGHTS.volo + 
            self.config.WEIGHTS.base_score
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Model weights must sum to 1.0, got {total}")
    
    def get_trust_band(self, score: float) -> TrustBand:
        """Convert trust score to band."""
        if score >= self.config.HIGH_TRUST_MIN:
            return TrustBand.HIGH_CONFIDENCE
        elif score >= self.config.MEDIUM_TRUST_MIN:
            return TrustBand.MEDIUM_CONFIDENCE
        elif score >= self.config.LOW_TRUST_MIN:
            return TrustBand.LOW_CONFIDENCE
        else:
            return TrustBand.REJECT
    
    def get_model_weights(self) -> ModelWeights:
        """Get model contribution weights."""
        return self.config.WEIGHTS
    
    def get_threshold_config(self) -> ThresholdConfig:
        """Get full threshold configuration."""
        return self.config
    
    def is_model_contribution_valid(self, model_name: str, score: float) -> bool:
        """Check if a model's contribution meets minimum thresholds."""
        if model_name == "trustbond":
            return score >= self.config.TRUSTBOND_MIN_SCORE
        elif model_name == "natural_language":
            return score >= (self.config.NATURAL_LANGUAGE_MIN_SIMILARITY * 100)
        elif model_name == "volo":
            return score >= (self.config.VOLO_MIN_CONFIDENCE * 100)
        return False
    
    def clamp_model_contribution(self, contribution: float) -> float:
        """Clamp individual model contribution to prevent domination."""
        return min(contribution, self.config.MAX_CONTRIBUTIONS_PER_MODEL)

# Global instance
trust_thresholds = TrustThresholds()

# Export key functions for backward compatibility
def get_trust_band(score: float) -> TrustBand:
    return trust_thresholds.get_trust_band(score)

def get_model_weights() -> ModelWeights:
    return trust_thresholds.get_model_weights()

def is_high_trust(score: float) -> bool:
    return score >= trust_thresholds.config.HIGH_TRUST_MIN

def is_medium_trust(score: float) -> bool:
    return trust_thresholds.config.MEDIUM_TRUST_MIN <= score < trust_thresholds.config.HIGH_TRUST_MIN

def is_low_trust(score: float) -> bool:
    return trust_thresholds.config.LOW_TRUST_MIN <= score < trust_thresholds.config.MEDIUM_TRUST_MIN

def is_reject_trust(score: float) -> bool:
    return score < trust_thresholds.config.LOW_TRUST_MIN

def should_auto_verify(aggregated_trust) -> bool:
    """Determine if report should be auto-verified based on aggregated trust."""
    return (
        aggregated_trust.trust_band == TrustBand.HIGH_CONFIDENCE and
        aggregated_trust.contributing_models >= trust_thresholds.config.MIN_MODELS_FOR_TRUST
    )

def should_flag_for_review(aggregated_trust) -> bool:
    """Determine if report should be flagged for human review."""
    return (
        aggregated_trust.trust_band in [TrustBand.MEDIUM_CONFIDENCE, TrustBand.LOW_CONFIDENCE] or
        aggregated_trust.contributing_models < trust_thresholds.config.MIN_MODELS_FOR_TRUST
    )

def should_reject(aggregated_trust) -> bool:
    """Determine if report should be rejected."""
    return aggregated_trust.trust_band == TrustBand.REJECT
