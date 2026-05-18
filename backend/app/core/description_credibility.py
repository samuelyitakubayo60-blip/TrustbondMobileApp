"""Description length and semantic-match adjustments for credibility scoring."""
from __future__ import annotations

from typing import Any, Optional

MIN_RECOMMENDED_WORDS = 15
MAX_LENGTH_PENALTY_POINTS = 30.0
SHORT_DESC_RESCUE_MAX_PENALTY_PCT = 0.30  # At most 30% score reduction when rescued


def _word_count(description: str | None) -> int:
    if not description or not str(description).strip():
        return 0
    return len(str(description).strip().split())


def _semantic_score_from_report(report: Any) -> float:
    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        return 0.0
    nl = fv.get("text_only_nl")
    if isinstance(nl, dict):
        for key in ("semantic_similarity", "semantic_similarity_score"):
            val = nl.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    align = fv.get("semantic_alignment")
    if isinstance(align, dict):
        for key in ("similarity_score", "score", "semantic_similarity"):
            val = align.get(key)
            if val is not None:
                try:
                    v = float(val)
                    return v * 100.0 if v <= 1.0 else v
                except (TypeError, ValueError):
                    pass
    return 0.0


def adjust_credibility_for_description(
    credibility_score: float,
    description: str | None,
    *,
    evidence_count: int = 0,
    report: Any | None = None,
    semantic_similarity: Optional[float] = None,
) -> tuple[float, dict[str, Any]]:
    """
  Apply length-based credibility tuning.

  - 15+ words: small bonus as descriptions grow (rewards detail).
  - <15 words: penalty unless description matches incident/evidence (semantic + evidence),
    in which case total penalty is capped at 30% of the score.
    """
    words = _word_count(description)
    meta: dict[str, Any] = {
        "word_count": words,
        "min_recommended_words": MIN_RECOMMENDED_WORDS,
    }
    score = float(credibility_score)

    sem = semantic_similarity
    if sem is None and report is not None:
        sem = _semantic_score_from_report(report)
    sem = float(sem or 0.0)
    meta["semantic_similarity"] = round(sem, 2)

    has_evidence = int(evidence_count or 0) > 0
    meta["has_evidence"] = has_evidence

    if words >= MIN_RECOMMENDED_WORDS:
        bonus = min(12.0, max(0.0, (words - MIN_RECOMMENDED_WORDS) * 0.6))
        score = min(100.0, score + bonus)
        meta["length_adjustment"] = "bonus"
        meta["length_points"] = round(bonus, 2)
        return score, meta

    missing = MIN_RECOMMENDED_WORDS - words
    raw_penalty = min(MAX_LENGTH_PENALTY_POINTS, missing * 2.5)
    meta["length_adjustment"] = "penalty"
    meta["raw_penalty_points"] = round(raw_penalty, 2)

    semantic_ok = sem >= 45.0
    evidence_ok = has_evidence
    if semantic_ok and evidence_ok:
        floor = score * (1.0 - SHORT_DESC_RESCUE_MAX_PENALTY_PCT)
        penalized = max(floor, score - raw_penalty)
        meta["short_description_rescue"] = True
        meta["applied_penalty_points"] = round(score - penalized, 2)
        return penalized, meta

    if semantic_ok and not evidence_ok:
        raw_penalty *= 0.6
        meta["partial_rescue"] = "semantic_only"

    penalized = max(0.0, score - raw_penalty)
    meta["applied_penalty_points"] = round(score - penalized, 2)
    meta["short_description_rescue"] = False
    return penalized, meta
