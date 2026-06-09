"""
Stage 3: Description Quality Analysis
=======================================
Evaluates the report description itself, independent of evidence.

Analyzes:
- Completeness
- Clarity
- Coherence
- Specificity
- Internal consistency
- Presence of useful contextual details

Does NOT evaluate against evidence.

Reject only if description quality is extremely poor (gibberish, empty, etc.).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────────────────────
MIN_WORDS = 5
ADEQUATE_WORDS = 15
GOOD_WORDS = 25
MIN_CHARS = 15
REJECT_SCORE_THRESHOLD = 15.0  # Only reject extremely poor descriptions

# ── Cache ────────────────────────────────────────────────────────────────────
_QUALITY_LLM_CACHE: Dict[str, Dict[str, Any]] = {}
_QUALITY_LLM_CACHE_MAX = 256


@dataclass
class StageThreeResult:
    """Result of description quality analysis."""
    description_score: float  # 0-100, overall quality
    completeness: float       # 0-100
    clarity: float            # 0-100
    specificity: float        # 0-100
    consistency: float        # 0-100
    decision: str             # "accept" | "reject"
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Local heuristic analysis ────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _sentence_count(text: str) -> int:
    sentences = re.split(r'[.!?;]+', text)
    return len([s for s in sentences if s.strip()])


def _has_temporal_markers(text: str) -> bool:
    """Check for time/date references indicating specificity."""
    patterns = [
        r'\b\d{1,2}[:/]\d{2}\b',  # times like 14:30
        r'\b(morning|afternoon|evening|night|midnight|dawn|dusk)\b',
        r'\b(yesterday|today|last\s+\w+|this\s+\w+)\b',
        r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\b',
        r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # dates
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _has_location_markers(text: str) -> bool:
    """Check for location references."""
    patterns = [
        r'\b(street|road|avenue|market|shop|house|home|school|church|hospital|station)\b',
        r'\b(near|behind|next\s+to|opposite|in\s+front\s+of|between)\b',
        r'\b(sector|cell|village|district|province)\b',
        r'\b(musanze|kigali|ruhengeri)\b',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _has_actor_references(text: str) -> bool:
    """Check for references to people/perpetrators/victims."""
    patterns = [
        r'\b(man|woman|men|women|person|people|group|gang|thief|robber|attacker)\b',
        r'\b(he|she|they|him|her|them)\b',
        r'\b(victim|suspect|perpetrator|witness|neighbour|neighbor)\b',
        r'\b(i\s+was|i\s+saw|i\s+heard|someone|anybody|nobody)\b',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _detect_gibberish(text: str) -> bool:
    """Detect obviously meaningless / spammy text."""
    if len(text) < 10:
        return True

    words = re.findall(r'[A-Za-z]{2,}', text)
    if len(words) < 2:
        if text.count(" ") < 1:
            return True

    letters = re.findall(r'[A-Za-z]', text)
    if not letters:
        return True

    alpha_ratio = len(letters) / max(1, len(text))
    if alpha_ratio < 0.4:
        return True

    # Very long single tokens (keysmash)
    longest_token = max((len(t) for t in re.findall(r'\S+', text)), default=0)
    if longest_token >= 20:
        return True

    # Low vowel ratio
    vowels = sum(1 for ch in "".join(letters).lower() if ch in "aeiou")
    if len(letters) > 5 and vowels / len(letters) < 0.15:
        return True

    # Excessive repeated characters
    if re.search(r'(.)\1{6,}', text):
        return True

    return False


def _analyze_completeness(text: str) -> float:
    """Score 0-100 based on how complete the description is."""
    score = 0.0
    wc = _word_count(text)

    # Word count scoring
    if wc >= GOOD_WORDS:
        score += 40.0
    elif wc >= ADEQUATE_WORDS:
        score += 30.0
    elif wc >= MIN_WORDS:
        score += 15.0
    else:
        score += 5.0

    # Sentence structure
    sc = _sentence_count(text)
    if sc >= 3:
        score += 20.0
    elif sc >= 2:
        score += 15.0
    elif sc >= 1:
        score += 8.0

    # Contextual markers
    if _has_temporal_markers(text):
        score += 15.0
    if _has_location_markers(text):
        score += 15.0
    if _has_actor_references(text):
        score += 10.0

    return min(100.0, score)


def _analyze_clarity(text: str) -> float:
    """Score 0-100 based on how clear and readable the text is."""
    score = 60.0  # baseline

    wc = _word_count(text)
    if wc == 0:
        return 0.0

    # Word diversity
    words = text.lower().split()
    unique = set(words)
    diversity = len(unique) / len(words) if words else 0
    if diversity >= 0.75:
        score += 20.0
    elif diversity >= 0.5:
        score += 10.0
    elif diversity < 0.3:
        score -= 15.0

    # Average word length (very short = vague, very long = jargon)
    avg_word_len = sum(len(w) for w in words) / max(1, len(words))
    if 3.5 <= avg_word_len <= 7.0:
        score += 10.0
    elif avg_word_len < 2.5 or avg_word_len > 10.0:
        score -= 10.0

    # Spam indicators
    if re.search(r'(.)\1{4,}', text):
        score -= 20.0
    if re.search(r'[!?]{3,}', text):
        score -= 10.0

    return max(0.0, min(100.0, score))


def _analyze_specificity(text: str) -> float:
    """Score 0-100 based on how specific and detailed the description is."""
    score = 30.0  # baseline

    if _has_temporal_markers(text):
        score += 20.0
    if _has_location_markers(text):
        score += 20.0
    if _has_actor_references(text):
        score += 15.0

    # Numbers in text (quantities, addresses, etc.)
    if re.search(r'\d+', text):
        score += 10.0

    # Descriptive adjectives / adverbs
    descriptive = re.findall(
        r'\b(large|small|tall|short|old|young|dark|light|red|blue|black|white|'
        r'fast|slow|loud|quiet|armed|masked|injured|bleeding|broken)\b',
        text.lower(),
    )
    score += min(15.0, len(descriptive) * 5.0)

    return max(0.0, min(100.0, score))


def _analyze_consistency(text: str) -> float:
    """Score 0-100 based on internal consistency. Basic heuristic check."""
    # For local analysis, we check for contradictory signals
    score = 75.0  # baseline - assume consistent

    words_lower = text.lower()

    # Check for self-contradictions (simple patterns)
    contradictions = [
        (r'\bno one\b.*\b(he|she|they)\b(attacked|hit|stole)', -15),
        (r'\b(nothing happened)\b.*\b(injured|wounded|killed)\b', -20),
        (r'\b(did not|didn\'t)\b.*\bbut\s+(was|were)\b', -5),
    ]
    for pattern, penalty in contradictions:
        if re.search(pattern, words_lower):
            score += penalty

    # Repetitive text lowers consistency
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    if len(sentences) > 1:
        unique_sentences = set(s.lower() for s in sentences)
        if len(unique_sentences) < len(sentences) * 0.6:
            score -= 20.0

    return max(0.0, min(100.0, score))


def _llm_quality_analysis(description: str) -> Optional[Dict[str, Any]]:
    """Use LLM for deeper quality analysis when available."""
    ck = hashlib.sha256(description[:500].encode()).hexdigest()[:24]
    if ck in _QUALITY_LLM_CACHE:
        return _QUALITY_LLM_CACHE[ck]

    prompt = f"""You are analyzing the quality of a citizen crime report description for Rwanda National Police.

Evaluate ONLY the description quality (not whether it's true or matches an incident type).

DESCRIPTION:
{description[:2000]}

Return JSON only:
{{
  "completeness": <integer 0-100>,
  "clarity": <integer 0-100>,
  "specificity": <integer 0-100>,
  "consistency": <integer 0-100>,
  "overall_quality": <integer 0-100>,
  "issues": ["<list of quality issues if any>"]
}}

Scoring guide:
- completeness: Does it describe what happened, when, where, who was involved?
- clarity: Is it readable and understandable?
- specificity: Does it provide specific details (times, places, descriptions)?
- consistency: Is the narrative internally consistent?"""

    result = _call_quality_llm(prompt, max_tokens=250)
    if not isinstance(result, dict):
        return None

    try:
        out = {
            "completeness": max(0, min(100, int(float(result.get("completeness", 50))))),
            "clarity": max(0, min(100, int(float(result.get("clarity", 50))))),
            "specificity": max(0, min(100, int(float(result.get("specificity", 50))))),
            "consistency": max(0, min(100, int(float(result.get("consistency", 50))))),
            "overall_quality": max(0, min(100, int(float(result.get("overall_quality", 50))))),
            "issues": result.get("issues", []),
        }
    except (TypeError, ValueError):
        return None

    if len(_QUALITY_LLM_CACHE) >= _QUALITY_LLM_CACHE_MAX:
        _QUALITY_LLM_CACHE.clear()
    _QUALITY_LLM_CACHE[ck] = out
    return out


def _call_quality_llm(prompt: str, *, max_tokens: int = 300) -> Optional[Dict[str, Any]]:
    """Call Groq or Gemini."""
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
            logger.warning("Groq quality analysis failed: %s", exc)

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
            logger.warning("Gemini quality analysis failed: %s", exc)

    return None


# ── Main function ────────────────────────────────────────────────────────────

def analyze_description_quality(description: str) -> StageThreeResult:
    """
    Stage 3: Analyze description quality.

    Combines local heuristic analysis with optional LLM-based analysis.
    Rejects ONLY if quality is extremely poor.
    """
    desc = (description or "").strip()

    if not desc or len(desc) < 5:
        return StageThreeResult(
            description_score=0.0,
            completeness=0.0,
            clarity=0.0,
            specificity=0.0,
            consistency=0.0,
            decision="reject",
            metadata={"reason": "empty_or_trivial_description"},
        )

    if _detect_gibberish(desc):
        return StageThreeResult(
            description_score=5.0,
            completeness=5.0,
            clarity=0.0,
            specificity=0.0,
            consistency=0.0,
            decision="reject",
            metadata={"reason": "gibberish_detected"},
        )

    # Try LLM analysis first
    llm_result = _llm_quality_analysis(desc)
    llm_used = False

    if llm_result:
        llm_used = True
        completeness = float(llm_result["completeness"])
        clarity = float(llm_result["clarity"])
        specificity = float(llm_result["specificity"])
        consistency = float(llm_result["consistency"])
        overall = float(llm_result["overall_quality"])
        issues = llm_result.get("issues", [])
    else:
        # Local heuristic fallback
        completeness = _analyze_completeness(desc)
        clarity = _analyze_clarity(desc)
        specificity = _analyze_specificity(desc)
        consistency = _analyze_consistency(desc)
        # Weighted combination
        overall = (
            completeness * 0.30
            + clarity * 0.25
            + specificity * 0.25
            + consistency * 0.20
        )
        issues = []

    overall = round(max(0.0, min(100.0, overall)), 2)

    # Decision: reject only if extremely poor
    if overall < REJECT_SCORE_THRESHOLD:
        decision = "reject"
    else:
        decision = "accept"

    metadata = {
        "word_count": _word_count(desc),
        "char_count": len(desc),
        "sentence_count": _sentence_count(desc),
        "llm_used": llm_used,
        "has_temporal_markers": _has_temporal_markers(desc),
        "has_location_markers": _has_location_markers(desc),
        "has_actor_references": _has_actor_references(desc),
        "issues": issues,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Stage 3 description quality: score=%.1f completeness=%.1f clarity=%.1f "
        "specificity=%.1f consistency=%.1f decision=%s",
        overall, completeness, clarity, specificity, consistency, decision,
    )

    return StageThreeResult(
        description_score=overall,
        completeness=round(completeness, 2),
        clarity=round(clarity, 2),
        specificity=round(specificity, 2),
        consistency=round(consistency, 2),
        decision=decision,
        metadata=metadata,
    )
