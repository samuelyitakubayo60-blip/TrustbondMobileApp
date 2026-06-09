"""
Stage 5: Dynamic Trust Score Computation
==========================================
Computes final trust score ONLY after all validation stages pass.

Components:
- Incident match score (Stage 2)
- Description quality score (Stage 3)
- Evidence match score (Stage 4)
- Evidence admissibility score (Stage 1)
- Reporter historical credibility (TrustBond XGBoost)
- Corroboration score (community votes)
- Location consistency score
- Temporal consistency score

Dynamic normalization: if evidence is missing, evidence-related weights
are removed and remaining weights normalized back to 100%.

This allows a report without evidence to still achieve score 100
if all available factors indicate high credibility.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.trust_thresholds import TrustBand, trust_thresholds

logger = logging.getLogger(__name__)


@dataclass
class TrustComponent:
    """A single component contributing to the trust score."""
    name: str
    raw_score: float      # 0-100
    weight: float          # assigned weight (before normalization)
    normalized_weight: float  # after dynamic normalization
    contribution: float    # normalized_weight * raw_score / 100 * 100
    available: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StageFiveResult:
    """Final trust score computation result."""
    trust_score: float              # 0-100
    trust_band: str                 # high_confidence | medium_confidence | low_confidence | reject
    components: List[TrustComponent] = field(default_factory=list)
    decision: str = ""              # ACCEPTED | FLAGGED_FOR_REVIEW | REJECTED
    decision_reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Default weights ──────────────────────────────────────────────────────────
# These sum to 100 when all components are available.

DEFAULT_WEIGHTS = {
    "incident_match": 25.0,        # Semantic match — moderate weight (hard-gate on mismatch)
    "description_quality": 20.0,   # Quality of the description text
    "evidence_match": 10.0,        # Evidence ↔ description alignment
    "evidence_admissibility": 15.0, # Evidence quality / forensic checks
    "reporter_history": 5.0,       # Device history — LOW (new devices must not be penalized)
    "corroboration": 5.0,          # Community votes
    "location_consistency": 20.0,  # GPS / credibility checks — HIGHEST
}
# Total = 100.0

# ── Thresholds for final decision ────────────────────────────────────────────
ACCEPT_THRESHOLD = 70.0   # 70-100 → verified
REVIEW_THRESHOLD = 40.0   # 40-69 → under_review; 0-39 → rejected


def _compute_location_consistency(
    gps_accuracy: Optional[float],
    movement_speed: Optional[float],
    was_stationary: Optional[bool],
) -> float:
    """
    Score 0-100 based on GPS and movement plausibility.

    This is the highest-weighted credibility component (20%).
    Good GPS + stationary reporter = strong credibility signal.
    """
    score = 75.0  # baseline — most reports within Musanze are credible

    if gps_accuracy is not None:
        acc = float(gps_accuracy)
        if acc <= 10:
            score += 20.0  # Very precise GPS lock
        elif acc <= 20:
            score += 15.0  # Good accuracy
        elif acc <= 35:
            score += 8.0   # Acceptable
        elif acc > 100:
            score -= 25.0  # Poor accuracy — suspicious

    if movement_speed is not None:
        speed = float(movement_speed)
        if speed > 50:
            score -= 25.0  # Unreasonably fast while reporting
        elif speed > 20:
            score -= 10.0
        elif speed <= 2.0:
            score += 5.0   # Walking or stationary — normal

    if was_stationary is True:
        score += 5.0  # Stationary reporting is a positive signal

    return max(0.0, min(100.0, score))


def _compute_corroboration_score(
    community_votes: Optional[Dict[str, int]],
) -> float:
    """
    Score 0-100 based on community votes.
    Neutral (no votes) = 50.
    """
    if not community_votes:
        return 60.0  # No votes = neutral-positive (not negative)

    real = int(community_votes.get("real", 0) or 0)
    false_v = int(community_votes.get("false", 0) or 0)
    total = real + false_v
    if total == 0:
        return 60.0  # No votes = neutral-positive

    # Net vote ratio
    net_ratio = (real - false_v) / total
    # Map -1..1 to 0..100
    score = 50.0 + (net_ratio * 50.0)
    return max(0.0, min(100.0, score))


def compute_dynamic_trust_score(
    *,
    incident_match_score: Optional[float] = None,
    description_quality_score: Optional[float] = None,
    evidence_match_score: Optional[float] = None,
    evidence_admissibility_score: Optional[float] = None,
    reporter_history_score: Optional[float] = None,
    community_votes: Optional[Dict[str, int]] = None,
    gps_accuracy: Optional[float] = None,
    movement_speed: Optional[float] = None,
    was_stationary: Optional[bool] = None,
    has_evidence: bool = False,
) -> StageFiveResult:
    """
    Compute final trust score with dynamic weight normalization.

    If evidence is missing, evidence-related weights are removed and
    remaining weights are normalized to sum to 100%.
    """
    # Build all components
    components_config = {
        "incident_match": {
            "score": incident_match_score,
            "weight": DEFAULT_WEIGHTS["incident_match"],
            "available": incident_match_score is not None,
        },
        "description_quality": {
            "score": description_quality_score,
            "weight": DEFAULT_WEIGHTS["description_quality"],
            "available": description_quality_score is not None,
        },
        "evidence_match": {
            "score": evidence_match_score,
            "weight": DEFAULT_WEIGHTS["evidence_match"],
            "available": has_evidence and evidence_match_score is not None,
        },
        "evidence_admissibility": {
            "score": evidence_admissibility_score,
            "weight": DEFAULT_WEIGHTS["evidence_admissibility"],
            "available": has_evidence and evidence_admissibility_score is not None,
        },
        "reporter_history": {
            "score": reporter_history_score if reporter_history_score is not None else 70.0,
            "weight": DEFAULT_WEIGHTS["reporter_history"],
            "available": True,  # Always available (default 70 for new reporters — neutral, low weight)
        },
        "corroboration": {
            "score": _compute_corroboration_score(community_votes),
            "weight": DEFAULT_WEIGHTS["corroboration"],
            "available": True,
        },
        "location_consistency": {
            "score": _compute_location_consistency(
                gps_accuracy, movement_speed, was_stationary
            ),
            "weight": DEFAULT_WEIGHTS["location_consistency"],
            "available": True,
        },
    }

    # Separate available and unavailable
    available_total_weight = sum(
        c["weight"] for c in components_config.values() if c["available"]
    )

    if available_total_weight == 0:
        return StageFiveResult(
            trust_score=0.0,
            trust_band=TrustBand.REJECT.value,
            decision="REJECTED",
            decision_reasons=["no_scoring_components_available"],
        )

    # Dynamic normalization: redistribute to sum to 100
    normalization_factor = 100.0 / available_total_weight

    components: List[TrustComponent] = []
    weighted_sum = 0.0

    for name, config in components_config.items():
        if config["available"]:
            raw = float(config["score"])
            norm_weight = config["weight"] * normalization_factor
            contribution = (raw / 100.0) * norm_weight
            weighted_sum += contribution
            components.append(TrustComponent(
                name=name,
                raw_score=round(raw, 2),
                weight=config["weight"],
                normalized_weight=round(norm_weight, 2),
                contribution=round(contribution, 2),
                available=True,
                metadata={},
            ))
        else:
            components.append(TrustComponent(
                name=name,
                raw_score=0.0,
                weight=config["weight"],
                normalized_weight=0.0,
                contribution=0.0,
                available=False,
                metadata={"reason": "component_not_available"},
            ))

    trust_score = round(max(0.0, min(100.0, weighted_sum)), 2)

    # HARD GATE: Semantic incident mismatch → force reject.
    # If the description does not match the selected incident type,
    # the report MUST be rejected regardless of other scores.
    # NOTE: Only apply hard cap for very low scores (< 20) which indicate
    # a clear mismatch. Scores 20-50 may be legitimate reports where
    # TF-IDF fallback (when LLM is rate-limited) gives low similarity
    # for descriptions that actually match the incident type.
    if incident_match_score is not None and incident_match_score < 20.0:
        trust_score = min(trust_score, 15.0)
        logger.warning(
            "Semantic mismatch hard reject (%.1f) — capping trust at 15", incident_match_score
        )

    # Determine trust band
    band = trust_thresholds.get_trust_band(trust_score)

    # Final decision
    decision_reasons: List[str] = []
    if trust_score >= ACCEPT_THRESHOLD:
        decision = "ACCEPTED"
        decision_reasons.append(f"trust_score_{trust_score}_above_accept_threshold_{ACCEPT_THRESHOLD}")
    elif trust_score >= REVIEW_THRESHOLD:
        decision = "FLAGGED_FOR_REVIEW"
        decision_reasons.append(f"trust_score_{trust_score}_in_review_range")
    else:
        decision = "REJECTED"
        decision_reasons.append(f"trust_score_{trust_score}_below_review_threshold_{REVIEW_THRESHOLD}")

    metadata = {
        "has_evidence": has_evidence,
        "available_components": sum(1 for c in components if c.available),
        "total_components": len(components),
        "available_weight_sum": round(available_total_weight, 2),
        "normalization_factor": round(normalization_factor, 4),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Stage 5 trust score: %.2f band=%s decision=%s "
        "components=%d/%d evidence=%s",
        trust_score,
        band.value,
        decision,
        sum(1 for c in components if c.available),
        len(components),
        has_evidence,
    )

    return StageFiveResult(
        trust_score=trust_score,
        trust_band=band.value,
        components=components,
        decision=decision,
        decision_reasons=decision_reasons,
        metadata=metadata,
    )
