"""
Natural Language Model Scorer
Analyzes description quality and semantic consistency.
Outputs only scores - no decision making.
"""

from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from .trust_thresholds import trust_thresholds

logger = logging.getLogger(__name__)

@dataclass
class NLAnalysisResult:
    """Result of natural language analysis."""
    description_quality_score: float  # 0-100
    semantic_similarity_score: float  # 0-100
    overall_score: float  # 0-100 weighted combination
    confidence: float  # 0.0-1.0
    metadata: Dict[str, Any]

class NaturalLanguageScorer:
    """Natural language model scorer for description analysis."""
    
    def __init__(self):
        self.thresholds = trust_thresholds
    
    def analyze_description(
        self,
        description: str,
        incident_type_name: str,
        incident_type_description: str = ""
    ) -> NLAnalysisResult:
        """
        Analyze description quality and semantic consistency.
        
        Args:
            description: Report description text
            incident_type_name: Name of the incident type
            incident_type_description: Description of the incident type
            
        Returns:
            NLAnalysisResult with scores and metadata
        """
        if not description or not description.strip():
            return self._create_empty_result("No description provided")
        
        description = description.strip()
        
        # 1. Description Quality Analysis
        quality_score, quality_metadata = self._analyze_description_quality(description)
        
        # 2. Semantic Consistency Analysis
        semantic_score, semantic_metadata = self._analyze_semantic_consistency(
            description, incident_type_name, incident_type_description
        )
        
        # 3. Calculate overall score (weighted combination)
        overall_score = (quality_score * 0.6) + (semantic_score * 0.4)
        
        # 4. Calculate confidence based on analysis completeness
        confidence = self._calculate_confidence(quality_metadata, semantic_metadata)
        
        # 5. Create result
        metadata = {
            "description_length": len(description),
            "word_count": len(description.split()),
            "quality_analysis": quality_metadata,
            "semantic_analysis": semantic_metadata,
            "incident_type": incident_type_name,
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }
        
        return NLAnalysisResult(
            description_quality_score=quality_score,
            semantic_similarity_score=semantic_score,
            overall_score=overall_score,
            confidence=confidence,
            metadata=metadata
        )
    
    def _analyze_description_quality(self, description: str) -> Tuple[float, Dict[str, Any]]:
        """Analyze description quality (length, readability, meaningful content)."""
        score = 0.0
        metadata = {}
        
        # Length analysis
        length = len(description)
        word_count = len(description.split())
        
        if length >= self.thresholds.config.DESCRIPTION_ADEQUATE_LENGTH:
            score += 30
            metadata["length_score"] = "adequate"
        elif length >= self.thresholds.config.DESCRIPTION_MIN_LENGTH:
            score += 15
            metadata["length_score"] = "minimal"
        else:
            metadata["length_score"] = "insufficient"
        
        # Word count analysis (15+ words recommended for full credit)
        min_words = getattr(self.thresholds.config, "DESCRIPTION_MIN_WORDS", 15)
        if word_count >= min_words + 10:
            score += 25
            metadata["word_count_score"] = "detailed"
        elif word_count >= min_words:
            score += 18
            metadata["word_count_score"] = "adequate"
        elif word_count >= max(5, min_words // 2):
            score += 8
            metadata["word_count_score"] = "moderate"
        else:
            metadata["word_count_score"] = "minimal"
        
        # Meaningful content analysis
        meaningful_score = self._analyze_meaningful_content(description)
        score += meaningful_score * 25
        metadata["meaningful_content_score"] = meaningful_score * 25
        
        # Spam/gibberish detection
        spam_penalty = self._detect_spam_indicators(description)
        score -= spam_penalty
        metadata["spam_penalty"] = spam_penalty
        
        # Emergency keywords (positive signal)
        emergency_bonus = self._detect_emergency_keywords(description)
        score += emergency_bonus
        metadata["emergency_bonus"] = emergency_bonus
        
        # Clamp to 0-100
        score = max(0.0, min(100.0, score))
        
        metadata["final_quality_score"] = score
        
        return score, metadata
    
    def _analyze_semantic_consistency(
        self,
        description: str,
        incident_type_name: str,
        incident_type_description: str
    ) -> Tuple[float, Dict[str, Any]]:
        """Analyze semantic consistency between description and incident type."""
        metadata = {
            "incident_type": incident_type_name,
            "semantic_model_available": False
        }
        
        from app.config import settings

        if getattr(settings, "enable_semantic_match", False) and report_semantic_llm_configured():
            api_score, api_meta = score_description_incident_similarity(
                description,
                incident_type_name,
                incident_type_description,
            )
            if api_score is not None:
                metadata.update(api_meta)
                return float(api_score), metadata

        return self._keyword_based_consistency(description, incident_type_name, metadata)
    
    def _keyword_based_consistency(
        self,
        description: str,
        incident_type_name: str,
        metadata: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        """Fallback keyword-based consistency analysis."""
        description_lower = description.lower()
        incident_type_lower = incident_type_name.lower()
        
        # Keyword mappings for different incident types
        keyword_mappings = {
            "theft": {"steal", "stolen", "rob", "robbed", "snatch", "burglary", "thief", "took"},
            "vandalism": {"damage", "destroy", "broken", "graffiti", "deface", "smashed"},
            "suspicious activity": {"suspicious", "strange", "unknown", "lurking", "watching", "weird"},
            "domestic violence": {"husband", "wife", "family", "home", "domestic", "partner", "beating"},
            "drug activity": {"drug", "weed", "cocaine", "heroin", "dealer", "selling", "pills"},
            "fraud/scam": {"scam", "fraud", "fake", "con", "money transfer", "phishing"},
            "harassment": {"harass", "threat", "stalk", "intimidat", "abuse"},
            "traffic incident": {"accident", "crash", "collision", "vehicle", "road", "car"},
            "assault": {"assault", "attack", "fight", "hit", "beaten", "injur", "violence"}
        }
        
        # Find matching keywords
        relevant_keywords = set()
        for incident_type, keywords in keyword_mappings.items():
            if incident_type in incident_type_lower:
                relevant_keywords.update(keywords)
        
        if not relevant_keywords:
            # Generic fallback for any incident type not explicitly in keyword_mappings.
            # Derive lightweight keywords from incident name tokens so new DB incident types
            # still get some consistency signal.
            stopwords = {"incident", "activity", "case", "report", "event", "type", "and", "or"}
            derived = {
                tok for tok in re.findall(r"[a-z]{4,}", incident_type_lower)
                if tok not in stopwords
            }
            if not derived:
                score = 50.0
                metadata["keyword_match_type"] = "no_specific_keywords"
                metadata["matched_keywords"] = []
                return score, metadata

            matched_keywords = [kw for kw in derived if kw in description_lower]
            if matched_keywords:
                score = 62.0
            else:
                score = 42.0
            metadata.update({
                "keyword_match_type": "derived_from_incident_name",
                "matched_keywords": matched_keywords,
                "available_keywords": list(derived),
                "match_count": len(matched_keywords),
                "keyword_score": score,
            })
            return score, metadata
        
        # Count matches
        matched_keywords = [kw for kw in relevant_keywords if kw in description_lower]
        match_count = len(matched_keywords)
        
        # Calculate score based on matches
        if match_count >= 3:
            score = 85.0
        elif match_count >= 2:
            score = 70.0
        elif match_count >= 1:
            score = 55.0
        else:
            score = 40.0
        
        metadata.update({
            "keyword_match_type": "keyword_based",
            "matched_keywords": matched_keywords,
            "available_keywords": list(relevant_keywords),
            "match_count": match_count,
            "keyword_score": score
        })
        
        return score, metadata
    
    def _analyze_meaningful_content(self, description: str) -> float:
        """Analyze if description contains meaningful content."""
        score = 0.0
        
        # Check for alphabetic content
        letters = re.findall(r"[a-zA-Z]", description)
        if letters:
            alpha_ratio = len(letters) / len(description)
            if alpha_ratio >= 0.7:
                score += 0.8
            elif alpha_ratio >= 0.5:
                score += 0.5
        
        # Check for word diversity
        words = description.lower().split()
        if words:
            unique_words = set(words)
            diversity_ratio = len(unique_words) / len(words)
            if diversity_ratio >= 0.8:
                score += 0.2
            elif diversity_ratio >= 0.6:
                score += 0.1
        
        return score
    
    def _detect_spam_indicators(self, description: str) -> float:
        """Detect spam/gibberish indicators and return penalty score."""
        penalty = 0.0
        
        # Excessive repeated characters
        if re.search(r"(.)\1{6,}", description):
            penalty += 20
        
        # Very long single word (keysmash)
        words = description.split()
        if words and len(max(words, key=len)) >= 18:
            penalty += 15
        
        # Low vowel ratio
        letters = re.findall(r"[a-zA-Z]", description)
        if letters:
            vowels = sum(1 for ch in letters if ch.lower() in "aeiou")
            vowel_ratio = vowels / len(letters)
            if vowel_ratio < 0.18:
                penalty += 10
        
        # Excessive unique characters with few spaces
        unique_chars = len(set(description.lower()))
        if unique_chars >= 22 and description.count(" ") <= 1 and len(description) >= 20:
            penalty += 15
        
        return penalty
    
    def _detect_emergency_keywords(self, description: str) -> float:
        """Detect emergency keywords and return bonus score."""
        emergency_keywords = [
            "urgent", "emergency", "immediate", "danger", "help", 
            "accident", "injured", "bleeding", "fire", "weapon"
        ]
        
        description_lower = description.lower()
        matches = sum(1 for keyword in emergency_keywords if keyword in description_lower)
        
        return min(matches * 3, 15)  # Cap at 15 points
    
    def _calculate_confidence(
        self,
        quality_metadata: Dict[str, Any],
        semantic_metadata: Dict[str, Any]
    ) -> float:
        """Calculate confidence in the analysis."""
        confidence = 0.7  # Base confidence
        
        # Boost confidence if semantic model was available
        if semantic_metadata.get("semantic_model_available", False):
            confidence += 0.2
        
        # Reduce confidence if spam indicators detected
        spam_penalty = quality_metadata.get("spam_penalty", 0)
        if spam_penalty > 10:
            confidence -= 0.2
        
        # Adjust based on description quality
        quality_score = quality_metadata.get("final_quality_score", 0)
        if quality_score >= 70:
            confidence += 0.1
        elif quality_score < 30:
            confidence -= 0.2
        
        return max(0.3, min(1.0, confidence))
    
    def _create_empty_result(self, reason: str) -> NLAnalysisResult:
        """Create empty result for cases where analysis cannot be performed."""
        return NLAnalysisResult(
            description_quality_score=0.0,
            semantic_similarity_score=0.0,
            overall_score=0.0,
            confidence=0.0,
            metadata={
                "error": reason,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }
        )


# ── Report semantic checks (Groq/Gemini API — replaces all-MiniLM-L6-v2) ─────

_REPORT_SEMANTIC_CACHE: Dict[str, Any] = {}
_REPORT_SEMANTIC_CACHE_MAX = 512
_REPORT_SEMANTIC_PROVIDER = "groq-gemini-api"


def report_semantic_llm_configured() -> bool:
    return bool(os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip())


def _call_report_semantic_llm(prompt: str, *, max_tokens: int = 300) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.warning("Groq report semantic call failed: %s", exc)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            import google.generativeai as genai

            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                generation_config={"response_mime_type": "application/json", "temperature": 0.3},
            )
            resp = model.generate_content(prompt)
            return json.loads(resp.text)
        except Exception as exc:
            logger.warning("Gemini report semantic call failed: %s", exc)
    return None


def _report_semantic_cache_key(prefix: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _report_semantic_cache_get(key: str) -> Optional[Any]:
    return _REPORT_SEMANTIC_CACHE.get(key)


def _report_semantic_cache_set(key: str, value: Any) -> None:
    if len(_REPORT_SEMANTIC_CACHE) >= _REPORT_SEMANTIC_CACHE_MAX:
        _REPORT_SEMANTIC_CACHE.clear()
    _REPORT_SEMANTIC_CACHE[key] = value


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def score_description_incident_similarity(
    description: str,
    incident_type_name: str,
    incident_type_description: str = "",
) -> Tuple[Optional[float], Dict[str, Any]]:
    """Semantic similarity 0–100 (description vs incident type). None if no API key."""
    desc = (description or "").strip()
    incident_text = f"{(incident_type_name or '').strip()}: {(incident_type_description or '').strip()}".strip(
        ": "
    )
    meta: Dict[str, Any] = {
        "provider": _REPORT_SEMANTIC_PROVIDER,
        "semantic_model_available": False,
        "incident_type": incident_type_name,
    }
    if len(desc) < 8 or not incident_type_name:
        return 50.0, meta
    if not report_semantic_llm_configured():
        return None, meta

    ck = _report_semantic_cache_key("desc_inc", json.dumps([desc, incident_text], ensure_ascii=False))
    cached = _report_semantic_cache_get(ck)
    if isinstance(cached, dict) and "score" in cached:
        return float(cached["score"]), {**meta, **cached.get("meta", {}), "cached": True}

    prompt = f"""You are validating citizen crime reports for Rwanda National Police (Musanze).

Compare the REPORT DESCRIPTION to the EXPECTED INCIDENT TYPE wording.
Return JSON only:
{{
  "similarity": <float 0.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "brief_reason": "<one short sentence>"
}}

REPORT DESCRIPTION:
{desc[:2000]}

EXPECTED INCIDENT TYPE:
{incident_text[:800]}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=180)
    if not isinstance(result, dict):
        return None, meta

    try:
        sim = _clamp01(float(result.get("similarity", 0.5)))
        conf = _clamp01(float(result.get("confidence", 0.7)))
    except (TypeError, ValueError):
        return None, meta

    score = round(sim * 100.0, 2)
    meta.update(
        {
            "semantic_model_available": True,
            "semantic_similarity": sim,
            "similarity_score": score,
            "confidence": conf,
            "incident_text": incident_text,
            "brief_reason": str(result.get("brief_reason") or "")[:300],
            "model": "llama-3.3-70b-versatile",
        }
    )
    _report_semantic_cache_set(ck, {"score": score, "meta": meta})
    return score, meta


def check_triple_semantic_alignment(
    *,
    report_description: str,
    incident_type_name: str,
    incident_type_description: str,
    evidence_semantic_text: str,
) -> Optional[Dict[str, Any]]:
    """Compare description vs evidence vs incident type via Groq/Gemini."""
    desc = (report_description or "").strip()
    evidence = (evidence_semantic_text or "").strip()
    if len(desc) < 10 or len(evidence) < 10 or not report_semantic_llm_configured():
        return None

    incident_text = (
        f"{(incident_type_name or '').strip()}: {(incident_type_description or '').strip()}"
    ).strip(": ")

    ck = _report_semantic_cache_key(
        "triple",
        json.dumps([desc, evidence, incident_text], ensure_ascii=False),
    )
    cached = _report_semantic_cache_get(ck)
    if isinstance(cached, dict) and "mismatch" in cached:
        return dict(cached)

    prompt = f"""You are validating a citizen crime report for Rwanda National Police.

Score how aligned three texts are (0.0 = unrelated, 1.0 = strongly aligned).
Return JSON only:
{{
  "description_evidence_similarity": <float 0-1>,
  "incident_evidence_similarity": <float 0-1>,
  "description_incident_similarity": <float 0-1>,
  "mismatch": <boolean>
}}

REPORT DESCRIPTION:
{desc[:1500]}

EVIDENCE SUMMARY:
{evidence[:1500]}

INCIDENT TYPE:
{incident_text[:600]}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=220)
    if not isinstance(result, dict):
        return None

    try:
        de = _clamp01(float(result.get("description_evidence_similarity", 0.5)))
        ie = _clamp01(float(result.get("incident_evidence_similarity", 0.5)))
        di = _clamp01(float(result.get("description_incident_similarity", 0.5)))
        mismatch = bool(result.get("mismatch", False))
    except (TypeError, ValueError):
        return None

    if de < 0.32 and ie < 0.34 and di < 0.38:
        mismatch = True

    out = {
        "model": _REPORT_SEMANTIC_PROVIDER,
        "description_evidence_similarity": round(de, 4),
        "incident_evidence_similarity": round(ie, 4),
        "description_incident_similarity": round(di, 4),
        "mismatch": mismatch,
    }
    _report_semantic_cache_set(ck, out)
    return out


def incident_description_mismatch_via_llm(
    description: str,
    selected_incident_type_id: Any,
    incident_types: List[Tuple[Any, str]],
) -> bool:
    """True when another incident type fits the description better than the selected one."""
    desc = (description or "").strip()
    if len(desc) < 12 or len(incident_types) < 2 or not report_semantic_llm_configured():
        return False

    lines = [f'- id="{iid}": {label[:200]}' for iid, label in incident_types[:40]]
    types_block = "\n".join(lines)

    prompt = f"""A citizen picked one incident type but wrote a free-text description.

Return JSON only:
{{
  "best_match_id": "<id from list>",
  "best_match_score": <float 0-1>,
  "selected_match_score": <float 0-1 for id "{selected_incident_type_id}">>,
  "mismatch": <true if different id is clearly better, best_match_score >= 0.42, margin >= 0.10>
}}

DESCRIPTION:
{desc[:2000]}

INCIDENT TYPES:
{types_block}

SELECTED ID: {selected_incident_type_id}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=200)
    if not isinstance(result, dict):
        return False

    try:
        best_id = str(result.get("best_match_id", "")).strip()
        best_score = float(result.get("best_match_score", 0))
        selected_score = float(result.get("selected_match_score", 0))
        mismatch_flag = bool(result.get("mismatch", False))
    except (TypeError, ValueError):
        return False

    if mismatch_flag:
        return True
    return (
        bool(best_id)
        and str(best_id) != str(selected_incident_type_id)
        and best_score >= 0.42
        and (best_score - selected_score) >= 0.10
    )


def warmup_report_semantic_llm() -> bool:
    """Startup: confirm Groq/Gemini keys (no embedding model download)."""
    if not report_semantic_llm_configured():
        logger.info(
            "Report semantic LLM: no GROQ/GEMINI key — keyword fallbacks for text matching"
        )
        return False
    logger.info("Report semantic LLM ready (Groq/Gemini)")
    return True


# Global instance
natural_language_scorer = NaturalLanguageScorer()

# Export main function for easy access
def analyze_description_quality(
    description: str,
    incident_type_name: str,
    incident_type_description: str = ""
) -> NLAnalysisResult:
    """Convenience function for natural language analysis."""
    return natural_language_scorer.analyze_description(
        description=description,
        incident_type_name=incident_type_name,
        incident_type_description=incident_type_description
    )
