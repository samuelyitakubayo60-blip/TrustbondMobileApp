"""
Stage 4: Description ↔ Evidence Validation
============================================
The most important validation stage.

Compares: Description ↔ Evidence (NOT incident type ↔ evidence)

Process:
1. Analyze evidence using YOLO, LLaVA, OCR, scene analysis → semantic evidence description
2. Generate embeddings for user description and evidence semantic description
3. Calculate semantic similarity
4. Use LLM reasoning to determine support level
5. Return match score and support classification

Rules:
- Strong contradiction → reject
- Completely unrelated evidence → reject
- Partial support → allow but lower score
- Strong support → high score
- No evidence → skip stage entirely
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Cache ────────────────────────────────────────────────────────────────────
_MATCH_LLM_CACHE: Dict[str, Dict[str, Any]] = {}
_MATCH_LLM_CACHE_MAX = 256

SUPPORT_LEVELS = ("strong", "partial", "weak", "contradictory", "unrelated")


@dataclass
class EvidenceSemanticDescription:
    """Semantic summary of what evidence contains."""
    objects: List[str] = field(default_factory=list)
    scene_summary: str = ""
    ocr_text: str = ""
    activities: List[str] = field(default_factory=list)
    audio_transcript: str = ""
    media_type: str = ""
    # Rich audio forensic summaries (from AudioForensicAnalyzer)
    audio_forensic_summaries: List[str] = field(default_factory=list)
    audio_distress_level: str = ""       # highest distress across audio files
    audio_detected_sounds: List[str] = field(default_factory=list)


@dataclass
class StageFourResult:
    """Result of description ↔ evidence matching."""
    semantic_similarity: float         # 0-100
    support_level: str                 # strong|partial|weak|contradictory|unrelated
    evidence_match_score: float        # 0-100
    decision: str                      # "accept" | "reject" | "flag"
    evidence_descriptions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    skipped: bool = False


# ── Build evidence semantic description ──────────────────────────────────────

def build_evidence_semantic_description(
    evidence_validations: List[Dict[str, Any]],
) -> EvidenceSemanticDescription:
    """
    Build a rich semantic description from Volo/YOLO analysis results.
    Reuses existing analysis infrastructure output.
    """
    all_objects: List[str] = []
    scene_parts: List[str] = []
    ocr_parts: List[str] = []
    activities: List[str] = []
    transcripts: List[str] = []
    media_types: List[str] = []
    audio_forensic_summaries: List[str] = []
    audio_detected_sounds: List[str] = []
    highest_distress = "none"
    _distress_order = {"none": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}

    for item in evidence_validations or []:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        advanced = validation.get("advanced_analysis") or {}

        # Objects detected by YOLO
        objects = summary.get("detected_objects") or []
        if isinstance(objects, list):
            all_objects.extend(str(o).strip() for o in objects[:20] if str(o).strip())

        # Extracted text (OCR)
        extracted_text = summary.get("extracted_text")
        if isinstance(extracted_text, str) and extracted_text.strip():
            ocr_parts.append(extracted_text.strip()[:300])

        # Actions detected
        actions = advanced.get("actions_detected") or []
        if isinstance(actions, list):
            activities.extend(str(a).strip() for a in actions[:10] if str(a).strip())

        # Scene context
        scene_context = advanced.get("scene_context") or {}
        scene_bits: List[str] = []
        indoor = scene_context.get("is_indoor")
        if isinstance(indoor, bool):
            scene_bits.append("indoor scene" if indoor else "outdoor scene")
        lighting = scene_context.get("lighting")
        if lighting:
            scene_bits.append(f"{lighting} lighting")
        weather = scene_context.get("weather")
        if weather:
            scene_bits.append(str(weather))
        if scene_bits:
            scene_parts.append(", ".join(scene_bits))

        # Audio transcript
        audio_meta = validation.get("audio_analysis") or {}
        transcript = (
            summary.get("extracted_text")
            or audio_meta.get("transcript")
            or ""
        )
        if isinstance(transcript, str) and transcript.strip():
            transcripts.append(transcript.strip()[:500])

        # Audio forensic analysis (from AudioForensicAnalyzer)
        forensic = validation.get("forensic_analysis") or {}
        forensic_summary = forensic.get("evidence_text_summary", "")
        if forensic_summary:
            audio_forensic_summaries.append(str(forensic_summary)[:600])

        # Audio detected sounds (both signal-based and LLM-detected)
        sound_events = forensic.get("detected_sound_events") or []
        if isinstance(sound_events, list):
            audio_detected_sounds.extend(str(s) for s in sound_events)

        # Distress level — keep highest across all audio evidence
        dlevel = str(forensic.get("distress_level", "none")).lower()
        if _distress_order.get(dlevel, 0) > _distress_order.get(highest_distress, 0):
            highest_distress = dlevel

        # Distress indicators as activities
        distress_indicators = forensic.get("distress_indicators") or []
        if isinstance(distress_indicators, list):
            activities.extend(str(d).split("(")[0].strip() for d in distress_indicators[:5])

        # Media type
        mt = summary.get("media_type")
        if mt:
            media_types.append(str(mt))

    return EvidenceSemanticDescription(
        objects=list(set(all_objects)),
        scene_summary="; ".join(scene_parts) if scene_parts else "",
        ocr_text=" | ".join(ocr_parts) if ocr_parts else "",
        activities=list(set(activities)),
        audio_transcript=" | ".join(transcripts) if transcripts else "",
        media_type=", ".join(set(media_types)) if media_types else "",
        audio_forensic_summaries=audio_forensic_summaries,
        audio_distress_level=highest_distress,
        audio_detected_sounds=list(set(audio_detected_sounds)),
    )


def _evidence_to_text(esd: EvidenceSemanticDescription) -> str:
    """Convert evidence semantic description to plain text for embedding/LLM."""
    parts: List[str] = []
    if esd.objects:
        parts.append(f"Objects detected: {', '.join(esd.objects)}")
    if esd.scene_summary:
        parts.append(f"Scene: {esd.scene_summary}")
    if esd.activities:
        parts.append(f"Activities: {', '.join(esd.activities)}")
    if esd.ocr_text:
        parts.append(f"Text found: {esd.ocr_text[:300]}")

    # Audio evidence — prefer forensic summary (rich) over raw transcript
    if esd.audio_forensic_summaries:
        parts.append(esd.audio_forensic_summaries[0][:500])
        # Include additional audio files if present
        for extra in esd.audio_forensic_summaries[1:3]:
            parts.append(extra[:300])
    elif esd.audio_transcript:
        parts.append(f"Audio transcript: {esd.audio_transcript[:300]}")

    if esd.audio_detected_sounds:
        parts.append(f"Audio sounds: {', '.join(esd.audio_detected_sounds)}")
    if esd.audio_distress_level and esd.audio_distress_level != "none":
        parts.append(f"Audio distress level: {esd.audio_distress_level}")

    return " | ".join(parts) if parts else "No evidence details available"


# ── Semantic similarity ─────────────────────────────────────────────────────

def _compute_description_evidence_similarity(
    description: str,
    evidence_text: str,
) -> float:
    """
    Compute semantic similarity between user description and evidence text.
    Uses sentence-transformers when available, falls back to TF-IDF.
    Returns 0-100.
    """
    from app.core.semantic_incident_validator import (
        compute_embedding_similarity,
    )
    return compute_embedding_similarity(description, evidence_text)


# ── LLM reasoning ───────────────────────────────────────────────────────────

def _llm_evidence_support_analysis(
    description: str,
    evidence_text: str,
) -> Optional[Dict[str, Any]]:
    """
    Use LLM to determine whether evidence supports the description.
    """
    ck = hashlib.sha256(
        f"{description[:400]}|{evidence_text[:400]}".encode()
    ).hexdigest()[:24]
    if ck in _MATCH_LLM_CACHE:
        return _MATCH_LLM_CACHE[ck]

    prompt = f"""You are analyzing whether submitted evidence supports a citizen crime report description.

IMPORTANT: Compare the EVIDENCE against the DESCRIPTION, not against any incident type.

REPORT DESCRIPTION:
{description[:1500]}

EVIDENCE ANALYSIS:
{evidence_text[:1500]}

Determine how well the evidence supports the description.

IMPORTANT AUDIO EVIDENCE GUIDELINES:
- Audio from crime scenes is often recorded while hiding, in chaos, or from a distance
- Unclear audio with screaming, fighting sounds, or distress speech IS relevant evidence
- Someone whispering/hiding while recording a break-in or assault = STRONG support
- Background chaos (impacts, shouting, sirens) matching a violent incident = STRONG support
- Audio with distress indicators during a reported crime = at least PARTIAL support
- Even without a clear transcript, sound patterns (screams, impacts) are meaningful evidence
- Do NOT penalize audio for being noisy or unclear — that is expected in real crime situations

Return JSON only:
{{
  "support_level": "<one of: strong, partial, weak, contradictory, unrelated>",
  "match_score": <integer 0-100>,
  "confidence": <float 0.0-1.0>,
  "reasoning": "<one sentence>"
}}

Definitions:
- strong: Evidence clearly shows elements described in the report
- partial: Evidence shows some elements but not all key claims
- weak: Evidence has minimal connection to description
- contradictory: Evidence directly contradicts the description
- unrelated: Evidence has no apparent connection to the described events"""

    result = _call_match_llm(prompt, max_tokens=200)
    if not isinstance(result, dict):
        return None

    try:
        support = str(result.get("support_level", "weak")).strip().lower()
        if support not in SUPPORT_LEVELS:
            support = "weak"
        out = {
            "support_level": support,
            "match_score": max(0, min(100, int(float(result.get("match_score", 50))))),
            "confidence": max(0.0, min(1.0, float(result.get("confidence", 0.5)))),
            "reasoning": str(result.get("reasoning", ""))[:300],
        }
    except (TypeError, ValueError):
        return None

    if len(_MATCH_LLM_CACHE) >= _MATCH_LLM_CACHE_MAX:
        _MATCH_LLM_CACHE.clear()
    _MATCH_LLM_CACHE[ck] = out
    return out


def _call_match_llm(prompt: str, *, max_tokens: int = 300) -> Optional[Dict[str, Any]]:
    """Call Groq or Gemini for matching analysis."""
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
            logger.warning("Groq evidence match call failed: %s", exc)

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
            logger.warning("Gemini evidence match call failed: %s", exc)

    return None


def _llm_configured() -> bool:
    return bool(
        os.getenv("GROQ_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )


# ── Main function ────────────────────────────────────────────────────────────

def match_description_to_evidence(
    description: str,
    evidence_validations: List[Dict[str, Any]],
) -> StageFourResult:
    """
    Stage 4: Compare description against evidence semantically.

    If no evidence → skip (returns skipped=True).
    If evidence contradicts or is unrelated → reject.
    If evidence partially supports → flag, lower score.
    If evidence strongly supports → accept, high score.
    """
    desc = (description or "").strip()

    if not evidence_validations:
        return StageFourResult(
            semantic_similarity=0.0,
            support_level="",
            evidence_match_score=0.0,
            decision="accept",
            skipped=True,
            metadata={"reason": "no_evidence_skipping_stage_4"},
        )

    # 1. Build evidence semantic description from Volo/YOLO outputs
    esd = build_evidence_semantic_description(evidence_validations)
    evidence_text = _evidence_to_text(esd)

    evidence_desc_dict = {
        "objects": esd.objects,
        "scene_summary": esd.scene_summary,
        "ocr_text": esd.ocr_text[:200] if esd.ocr_text else "",
        "activities": esd.activities,
        "audio_transcript": esd.audio_transcript[:200] if esd.audio_transcript else "",
        "audio_detected_sounds": esd.audio_detected_sounds,
        "audio_distress_level": esd.audio_distress_level,
    }

    if not desc or evidence_text == "No evidence details available":
        return StageFourResult(
            semantic_similarity=50.0,
            support_level="weak",
            evidence_match_score=50.0,
            decision="accept",
            evidence_descriptions=[evidence_desc_dict],
            metadata={"reason": "insufficient_data_for_matching"},
        )

    # 2. Compute semantic similarity (embeddings)
    semantic_sim = _compute_description_evidence_similarity(desc, evidence_text)

    # 3. LLM reasoning pass
    llm_available = False
    llm_support = "weak"
    llm_score = 50.0
    llm_confidence = 0.3
    llm_reasoning = ""

    if _llm_configured():
        llm_result = _llm_evidence_support_analysis(desc, evidence_text)
        if llm_result:
            llm_available = True
            llm_support = llm_result["support_level"]
            llm_score = float(llm_result["match_score"])
            llm_confidence = float(llm_result["confidence"])
            llm_reasoning = llm_result.get("reasoning", "")

    # 4. Determine final support level and score
    if llm_available:
        # Combine embedding similarity with LLM score
        final_score = (semantic_sim * 0.4) + (llm_score * 0.6)
        support_level = llm_support
    else:
        # Embedding-only assessment
        final_score = semantic_sim
        if semantic_sim >= 60:
            support_level = "strong"
        elif semantic_sim >= 40:
            support_level = "partial"
        elif semantic_sim >= 20:
            support_level = "weak"
        else:
            support_level = "unrelated"

    final_score = round(max(0.0, min(100.0, final_score)), 2)

    # 5. Decision based on support level
    if support_level == "contradictory":
        decision = "reject"
    elif support_level == "unrelated":
        decision = "reject"
    elif support_level == "weak":
        decision = "flag"
    elif support_level == "partial":
        decision = "flag" if final_score < 40 else "accept"
    else:  # strong
        decision = "accept"

    metadata = {
        "evidence_text_preview": evidence_text[:300],
        "llm_available": llm_available,
        "llm_support_level": llm_support if llm_available else None,
        "llm_reasoning": llm_reasoning,
        "llm_confidence": llm_confidence if llm_available else None,
        "embedding_similarity": round(semantic_sim, 2),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Stage 4 evidence matching: sim=%.1f llm_score=%.1f final=%.1f "
        "support=%s decision=%s",
        semantic_sim, llm_score, final_score, support_level, decision,
    )

    return StageFourResult(
        semantic_similarity=round(semantic_sim, 2),
        support_level=support_level,
        evidence_match_score=final_score,
        decision=decision,
        evidence_descriptions=[evidence_desc_dict],
        metadata=metadata,
    )
