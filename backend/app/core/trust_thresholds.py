"""
Centralized Trust Threshold Configuration
Single source of truth for all model thresholds and weights.

Updated for the 5-stage verification pipeline:
  Stage 1: Evidence Admissibility
  Stage 2: Incident Type ↔ Description (semantic)
  Stage 3: Description Quality
  Stage 4: Description ↔ Evidence (semantic)
  Stage 5: Dynamic Trust Score Computation
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
    """Weights for each model in the final trust calculation (legacy compat)."""
    trustbond: float = 0.4
    natural_language: float = 0.3
    volo: float = 0.2
    base_score: float = 0.1

@dataclass
class PipelineWeights:
    """Weights for the 5-stage pipeline trust score computation.
    These sum to 100 when all components are available.

    Credibility checks (location, evidence admissibility) carry the most
    weight. Device/reporter history contributes very little — a new device
    should not be penalized. Semantic incident match acts as a hard gate
    (reject on mismatch) so its scoring weight is moderate.
    """
    incident_match: float = 25.0
    description_quality: float = 20.0
    evidence_match: float = 10.0
    evidence_admissibility: float = 15.0
    reporter_history: float = 5.0
    corroboration: float = 5.0
    location_consistency: float = 20.0

@dataclass
class ThresholdConfig:
    """Centralized threshold configuration for all models and pipeline stages."""

    # Trust Score Bands (0-100 scale)
    # 70-100 → verified (auto-confirmed)
    # 40-69  → under_review (needs leader attention)
    # 0-39   → rejected
    HIGH_TRUST_MIN: float = 70.0
    MEDIUM_TRUST_MIN: float = 40.0
    LOW_TRUST_MIN: float = 40.0   # same as MEDIUM — no separate low band
    REJECT_MAX: float = 40.0

    # Pipeline Stage Thresholds
    STAGE1_MIN_ADMISSIBILITY: float = 30.0     # Min admissibility score to pass
    STAGE2_EMBEDDING_REJECT: float = 15.0      # Extremely low embedding → reject
    STAGE2_FINAL_REJECT: float = 30.0          # Final incident match score → reject
    STAGE2_FINAL_REVIEW: float = 50.0          # Below this → flag for review
    STAGE3_REJECT: float = 15.0                # Extremely poor description → reject
    STAGE5_ACCEPT: float = 70.0                # Trust score → auto-accept (verified)
    STAGE5_REVIEW: float = 40.0                # Trust score → review range (40-69)

    # Individual Model Thresholds (legacy compat)
    TRUSTBOND_MIN_SCORE: float = 30.0
    NATURAL_LANGUAGE_MIN_SIMILARITY: float = 0.42
    VOLO_MIN_CONFIDENCE: float = 0.3

    # Description Quality Thresholds
    DESCRIPTION_MIN_WORDS: int = 15
    DESCRIPTION_MIN_LENGTH: int = 20
    DESCRIPTION_ADEQUATE_LENGTH: int = 50
    DESCRIPTION_MAX_LENGTH: int = 1000

    # Evidence Quality Thresholds
    EVIDENCE_MIN_BLUR_SCORE: float = 100.0
    EVIDENCE_MIN_BRIGHTNESS: float = 0.1
    EVIDENCE_MAX_BRIGHTNESS: float = 0.9

    # Aggregation Weights
    WEIGHTS = ModelWeights()
    PIPELINE_WEIGHTS = PipelineWeights()

    # Validation Rules
    MIN_MODELS_FOR_TRUST: int = 1
    MAX_CONTRIBUTIONS_PER_MODEL: float = 55.0

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
        """Convert trust score to band.
        70-100 → HIGH_CONFIDENCE (verified)
        40-69  → MEDIUM_CONFIDENCE (under_review)
        0-39   → REJECT (rejected)
        """
        if score >= self.config.HIGH_TRUST_MIN:
            return TrustBand.HIGH_CONFIDENCE
        elif score >= self.config.MEDIUM_TRUST_MIN:
            return TrustBand.MEDIUM_CONFIDENCE
        else:
            return TrustBand.REJECT

    def get_model_weights(self) -> ModelWeights:
        return self.config.WEIGHTS

    def get_pipeline_weights(self) -> PipelineWeights:
        return self.config.PIPELINE_WEIGHTS

    def get_threshold_config(self) -> ThresholdConfig:
        return self.config

    def is_model_contribution_valid(self, model_name: str, score: float) -> bool:
        if model_name == "trustbond":
            return score >= self.config.TRUSTBOND_MIN_SCORE
        elif model_name == "natural_language":
            return score >= (self.config.NATURAL_LANGUAGE_MIN_SIMILARITY * 100)
        elif model_name == "volo":
            return score >= (self.config.VOLO_MIN_CONFIDENCE * 100)
        return False

    def clamp_model_contribution(self, contribution: float) -> float:
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
    return (
        aggregated_trust.trust_band == TrustBand.HIGH_CONFIDENCE and
        aggregated_trust.contributing_models >= trust_thresholds.config.MIN_MODELS_FOR_TRUST
    )

def should_flag_for_review(aggregated_trust) -> bool:
    return (
        aggregated_trust.trust_band in [TrustBand.MEDIUM_CONFIDENCE, TrustBand.LOW_CONFIDENCE] or
        aggregated_trust.contributing_models < trust_thresholds.config.MIN_MODELS_FOR_TRUST
    )

def should_reject(aggregated_trust) -> bool:
    return aggregated_trust.trust_band == TrustBand.REJECT
