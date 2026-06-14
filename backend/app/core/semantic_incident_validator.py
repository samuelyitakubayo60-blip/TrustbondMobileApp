"""
Stage 2: Incident Type ↔ Description Validation
=================================================
Uses semantic analysis (embeddings + LLM reasoning) to determine whether
the report description genuinely describes the selected incident type.

NO keyword matching. Works automatically for any new incident type
added to the database via `semantic_definition`.

Pipeline:
1. Generate embeddings for incident semantic_definition and user description.
   Uses sentence-transformers (all-MiniLM-L6-v2) for high-quality embeddings,
   falls back to TF-IDF if unavailable.
2. Calculate embedding cosine similarity with calibrated piecewise mapping.
3. Use LLM reasoning pass to confirm/deny match.
4. Combine: LLM available → 80% LLM + 20% embedding.
   Sentence-transformers only → 85% embedding + baseline.
   TF-IDF only → 70% embedding + generous baseline.

Reject if similarity is extremely low or final score below threshold.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.incident_type import IncidentType

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────────────────────
EMBEDDING_REJECT_THRESHOLD = 15.0    # Extremely low embedding similarity → reject
FINAL_SCORE_REJECT_THRESHOLD = 30.0  # Final combined score → reject
FINAL_SCORE_REVIEW_THRESHOLD = 50.0  # Below this → flag for review

# ── Cache ────────────────────────────────────────────────────────────────────
_EMBEDDING_CACHE: Dict[str, List[float]] = {}
_EMBEDDING_CACHE_MAX = 256
_LLM_CACHE: Dict[str, Dict[str, Any]] = {}
_LLM_CACHE_MAX = 512


@dataclass
class StageTwoResult:
    """Result of incident type vs description validation."""
    embedding_similarity: float       # 0-100
    llm_match_score: float            # 0-100
    final_incident_match_score: float  # 0-100
    decision: str                     # "accept" | "reject"
    confidence: float                 # 0-1
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Embedding helpers ────────────────────────────────────────────────────────

def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _get_sentence_transformer():
    """Load sentence-transformers model (cached globally)."""
    global _st_model
    if "_st_model" not in globals() or _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv(
                "EMBEDDING_MODEL", "all-MiniLM-L6-v2"
            )
            _st_model = SentenceTransformer(model_name)
            logger.info("Loaded sentence transformer: %s", model_name)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Falling back to TF-IDF embeddings."
            )
            _st_model = None
        except Exception as exc:
            logger.warning("Failed to load sentence transformer: %s", exc)
            _st_model = None
    return _st_model

_st_model = None


def _compute_embedding(text: str) -> Optional[List[float]]:
    """Compute embedding for text using sentence-transformers or TF-IDF fallback."""
    key = _cache_key(text)
    if key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[key]

    model = _get_sentence_transformer()
    if model is not None:
        try:
            emb = model.encode(text, convert_to_numpy=True).tolist()
            if len(_EMBEDDING_CACHE) >= _EMBEDDING_CACHE_MAX:
                _EMBEDDING_CACHE.clear()
            _EMBEDDING_CACHE[key] = emb
            return emb
        except Exception as exc:
            logger.warning("Sentence transformer encoding failed: %s", exc)

    return None  # Caller should use TF-IDF fallback


def _cosine_similarity_vectors(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tfidf_similarity(text_a: str, text_b: str) -> float:
    """TF-IDF cosine similarity fallback when sentence-transformers unavailable."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
        )
        tfidf = vectorizer.fit_transform([text_a.lower(), text_b.lower()])
        sim = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
        return sim
    except Exception as exc:
        logger.warning("TF-IDF similarity failed: %s", exc)
        return 0.0


def compute_embedding_similarity(
    description: str,
    semantic_definition: str,
    incident_type_name: str = "",
) -> float:
    """
    Compute semantic similarity between description and incident definition.
    Returns 0-100 score.

    Uses sentence-transformers embeddings when available, falls back to TF-IDF.
    """
    if not description.strip() or not semantic_definition.strip():
        return 0.0

    # Prepend incident type name to the definition for better matching
    # (e.g. "Assault: Intentional physical attack..." gives the model
    # the label context alongside the definition)
    full_definition = semantic_definition
    if incident_type_name:
        full_definition = f"{incident_type_name}: {semantic_definition}"

    # Try sentence-transformer embeddings first
    emb_desc = _compute_embedding(description)
    emb_def = _compute_embedding(full_definition)

    if emb_desc is not None and emb_def is not None:
        raw_sim = _cosine_similarity_vectors(emb_desc, emb_def)
        # Sentence-transformer cosine similarity for crime reports:
        #   Clear match (description matches incident definition): ~0.35-0.70
        #   Moderate/indirect match (related actions/context): ~0.25-0.40
        #   Weak/no match: ~0.0-0.20
        #
        # Calibrated mapping — generous for genuine crime reports where
        # citizens use informal language that differs from formal definitions:
        if raw_sim >= 0.50:
            score = 88.0 + (raw_sim - 0.50) * 24.0     # 0.50→88, 0.60→90.4, 1.0→100
        elif raw_sim >= 0.35:
            score = 72.0 + (raw_sim - 0.35) * 106.67   # 0.35→72, 0.425→80, 0.50→88
        elif raw_sim >= 0.25:
            score = 55.0 + (raw_sim - 0.25) * 170.0    # 0.25→55, 0.30→63.5, 0.35→72
        elif raw_sim >= 0.15:
            score = 25.0 + (raw_sim - 0.15) * 300.0    # 0.15→25, 0.20→40, 0.25→55
        else:
            score = raw_sim * 166.67                     # 0.0→0, 0.10→16.7, 0.15→25
        score = min(100.0, max(0.0, score))
        return round(score, 2)

    # TF-IDF fallback — scores are inherently low for short semantic definitions
    # vs longer descriptions. Scale aggressively to get meaningful spread.
    raw_sim = _tfidf_similarity(description, semantic_definition)
    # TF-IDF similarity for crime reports: matching ~0.05-0.25, non-matching ~0.0-0.03
    if raw_sim >= 0.15:
        score = 60.0 + (raw_sim - 0.15) * 400.0  # 0.15→60, 0.25→100
    elif raw_sim >= 0.05:
        score = 25.0 + (raw_sim - 0.05) * 350.0   # 0.05→25, 0.15→60
    else:
        score = raw_sim * 500.0                     # 0.0→0, 0.05→25
    score = min(100.0, max(0.0, score))
    return round(score, 2)


# ── LLM reasoning pass ──────────────────────────────────────────────────────

def _llm_cache_key(description: str, definition: str, type_name: str) -> str:
    payload = json.dumps([description[:500], definition[:500], type_name], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:32]


def _call_llm_for_incident_match(
    description: str,
    incident_type_name: str,
    semantic_definition: str,
) -> Optional[Dict[str, Any]]:
    """
    Use LLM (Groq/Gemini) to reason whether description matches incident type.
    Returns dict with match_score (0-100), confidence, and reasoning.
    """
    ck = _llm_cache_key(description, semantic_definition, incident_type_name)
    if ck in _LLM_CACHE:
        return _LLM_CACHE[ck]

    prompt = f"""You are validating citizen crime reports for Rwanda National Police (Musanze District).

Determine whether the REPORT DESCRIPTION genuinely describes the INCIDENT TYPE by comparing it against the INCIDENT DEFINITION.

INCIDENT TYPE: {incident_type_name}
INCIDENT DEFINITION: {semantic_definition[:800]}

REPORT DESCRIPTION:
{description[:2000]}

Analyze carefully:
1. Compare the REPORT DESCRIPTION to the INCIDENT DEFINITION — do the described events, actions, and circumstances match the definition?
2. Look for semantic overlap: are the people, actions, locations, and situations described consistent with this incident type?
3. A genuine match does NOT require exact wording — real citizen reports use informal, emotional language. Focus on meaning, not keywords.
4. Consider: beaten by husband at home = domestic violence. Stolen phone = theft. Crashed vehicle = traffic accident. Match the MEANING.

Return JSON only:
{{
  "match_score": <integer 0-100, how well description matches this incident type>,
  "confidence": <float 0.0-1.0, your confidence in the assessment>,
  "reasoning": "<one sentence explaining your assessment>"
}}

Score guide:
- 85-100: Description clearly and directly describes this incident type (the events match the definition)
- 70-84: Description is strongly consistent with this incident type
- 50-69: Description partially relates but is ambiguous
- 20-49: Description weakly related, likely a different incident type
- 0-19: Description clearly describes a different type of incident"""

    result = _call_semantic_llm(prompt, max_tokens=200)
    if not isinstance(result, dict):
        return None

    try:
        match_score = max(0, min(100, int(float(result.get("match_score", 50)))))
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
        reasoning = str(result.get("reasoning", ""))[:300]
    except (TypeError, ValueError):
        return None

    out = {
        "match_score": match_score,
        "confidence": confidence,
        "reasoning": reasoning,
    }
    if len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        _LLM_CACHE.clear()
    _LLM_CACHE[ck] = out
    return out


def _call_semantic_llm(prompt: str, *, max_tokens: int = 300) -> Optional[Dict[str, Any]]:
    """Call Groq or Gemini for semantic analysis (shared with other modules)."""
    # Try Groq first
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            err = str(exc).lower()
            if "organization_restricted" not in err and "invalid_api_key" not in err:
                logger.warning("Groq semantic call failed: %s", exc)

    # Try Gemini
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from app.core.llm_recommendations import _gemini_model_candidates, gemini_generate_json
            for model_name in _gemini_model_candidates():
                parsed = gemini_generate_json(
                    prompt, gemini_key, model_name,
                    max_tokens=max_tokens, temperature=0.2,
                )
                if parsed:
                    return parsed
        except Exception as exc:
            logger.warning("Gemini semantic call failed: %s", exc)

    return None


def _llm_configured() -> bool:
    """Check if any LLM API is configured."""
    return bool(
        os.getenv("GROQ_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )


# ── Main validation function ────────────────────────────────────────────────

def get_incident_semantic_definition(
    db: Session,
    incident_type_id: int,
) -> Tuple[str, str, str]:
    """
    Get incident type details including semantic_definition.
    Returns (type_name, description, semantic_definition).
    Falls back to description if semantic_definition not set.
    """
    from app.core.incident_type_loader import (
        fetch_incident_type_by_id,
        semantic_definition_for_type,
    )

    row = fetch_incident_type_by_id(db, incident_type_id)
    if not row:
        return "", "", ""

    type_name = (row.type_name or "").strip()
    description = (row.description or "").strip()
    semantic_def = semantic_definition_for_type(
        type_name,
        description,
        getattr(row, "semantic_definition", None),
    )

    return type_name, description, semantic_def


def validate_incident_description(
    db: Session,
    description: str,
    incident_type_id: int,
) -> StageTwoResult:
    """
    Stage 2: Validate that description matches the selected incident type
    using semantic embeddings + LLM reasoning.

    NO keyword matching.

    Returns StageTwoResult with scores and accept/reject decision.
    """
    desc = (description or "").strip()
    if not desc:
        return StageTwoResult(
            embedding_similarity=0.0,
            llm_match_score=0.0,
            final_incident_match_score=0.0,
            decision="reject",
            confidence=1.0,
            metadata={"reason": "empty_description"},
        )

    type_name, type_desc, semantic_def = get_incident_semantic_definition(
        db, incident_type_id
    )
    if not semantic_def:
        # Unknown incident type — cannot validate, pass through
        return StageTwoResult(
            embedding_similarity=50.0,
            llm_match_score=50.0,
            final_incident_match_score=50.0,
            decision="accept",
            confidence=0.3,
            metadata={"reason": "unknown_incident_type", "incident_type_id": incident_type_id},
        )

    # 1. Compute embedding similarity (include type name for better context)
    embedding_sim = compute_embedding_similarity(desc, semantic_def, type_name)

    # 2. LLM reasoning pass
    llm_score = 50.0  # neutral default
    llm_confidence = 0.3
    llm_reasoning = ""
    llm_available = False

    if _llm_configured():
        llm_result = _call_llm_for_incident_match(desc, type_name, semantic_def)
        if llm_result:
            llm_score = float(llm_result["match_score"])
            llm_confidence = float(llm_result["confidence"])
            llm_reasoning = llm_result.get("reasoning", "")
            llm_available = True

    # 3. Combine scores — LLM is far more accurate than TF-IDF for incident matching
    embedding_method = "sentence_transformer" if _get_sentence_transformer() else "tfidf"

    if llm_available:
        # LLM dominates: 80% LLM + 20% embedding
        # TF-IDF is weak for short semantic definitions, LLM actually understands context
        final_score = (embedding_sim * 0.2) + (llm_score * 0.8)
    elif embedding_method == "sentence_transformer":
        # Sentence-transformers embeddings are much more reliable than TF-IDF.
        # Trust them more when LLM is unavailable.
        # For a genuine match (embedding ~75-85), this gives ~77-85
        final_score = embedding_sim * 0.9 + 8.0
    else:
        # No LLM AND no sentence-transformers — only TF-IDF available.
        # TF-IDF alone is unreliable for incident matching (short formal
        # definitions vs long informal descriptions → inherently low scores).
        # Use a high baseline so TF-IDF never causes rejection of legitimate
        # reports. Real mismatches are caught by other pipeline stages.
        final_score = embedding_sim * 0.4 + 50.0  # generous baseline (50-90 range)

    final_score = round(max(0.0, min(100.0, final_score)), 2)

    # 4. Decision
    if llm_available and llm_score >= 70 and llm_confidence >= 0.6:
        # LLM confidently says it matches — trust it even if embedding is low
        decision = "accept"
    elif llm_available and llm_score < 20 and llm_confidence >= 0.6:
        # LLM confidently says it does NOT match — reject
        decision = "reject"
    elif not llm_available and embedding_method == "sentence_transformer":
        # Sentence-transformers are reliable for semantic matching.
        # Reject when similarity is clearly low (different incident type).
        if embedding_sim < 25.0:
            decision = "reject"
        else:
            decision = "accept"
    elif not llm_available:
        # TF-IDF only — too unreliable for incident matching decisions.
        # Short formal definitions vs long informal descriptions produce
        # near-zero TF-IDF similarity even for genuine matches.
        # NEVER reject on TF-IDF alone — let Stage 5 trust scoring handle it.
        decision = "accept"
    elif embedding_sim < EMBEDDING_REJECT_THRESHOLD and llm_score < 25:
        decision = "reject"
    elif final_score < FINAL_SCORE_REJECT_THRESHOLD:
        decision = "reject"
    else:
        decision = "accept"

    # Overall confidence
    if llm_available:
        confidence = min(1.0, 0.5 + llm_confidence * 0.5)
    elif embedding_method == "sentence_transformer":
        confidence = 0.6  # sentence-transformers are reasonably reliable
    else:
        confidence = 0.35  # low confidence without LLM — TF-IDF is unreliable

    metadata = {
        "incident_type_name": type_name,
        "incident_type_id": incident_type_id,
        "semantic_definition_used": semantic_def[:200],
        "llm_available": llm_available,
        "llm_reasoning": llm_reasoning,
        "embedding_method": "sentence_transformer" if _get_sentence_transformer() else "tfidf",
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Stage 2 incident validation: report=%s emb=%.1f llm=%.1f final=%.1f decision=%s",
        incident_type_id,
        embedding_sim,
        llm_score,
        final_score,
        decision,
    )

    return StageTwoResult(
        embedding_similarity=round(embedding_sim, 2),
        llm_match_score=round(llm_score, 2),
        final_incident_match_score=final_score,
        decision=decision,
        confidence=round(confidence, 4),
        metadata=metadata,
    )
