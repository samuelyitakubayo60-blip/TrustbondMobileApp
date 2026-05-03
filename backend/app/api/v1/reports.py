import logging
import json
from typing import Annotated, Optional, List, Tuple, Dict, Any
from decimal import Decimal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, Query, status, Request
from sqlalchemy.orm import Session, joinedload, selectinload
from uuid import uuid4, UUID
from datetime import datetime, timedelta, timezone
import io
import os
import math
import hashlib
from pathlib import Path

import cloudinary
import cloudinary.uploader
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Evidence analysis service removed for consolidation

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.report import Report
from app.models.evidence_file import EvidenceFile, EvidenceQuality
from app.models.hotspot import Hotspot, hotspot_reports_table
from app.models.device import Device
from app.models.incident_type import IncidentType
from app.models.location import Location
from app.models.station import Station
from app.schemas.report import (
    ReportCreate,
    ReportResponse,
    ReportDetailResponse,
    ReportListResponse,
    EvidenceFileResponse,
    EvidencePreview,
    AssignmentResponse,
    AssignCreate,
    ReviewResponse,
    ReviewCreate,
)
from app.models.police_user import PoliceUser
from app.models.report_assignment import ReportAssignment
from app.models.police_review import PoliceReview
from app.core.security import verify_password
from app.core.websocket import manager
from app.api.v1.auth import get_optional_user, get_current_user, get_current_admin_or_supervisor
from app.api.v1.notifications import create_notification
from app.core.report_rules import (
    apply_rule_based_status, 
    is_likely_screenshot_or_screen_recording,
    enhanced_screenshot_detection,
    analyze_file_timing,
    validate_evidence_source,
    enhanced_screen_recording_detection,
    validate_location_consistency
)
from app.core.report_review import (
    needs_police_review_clause,
    resolve_ml_prediction_for_report,
)
from app.core.credibility_model import score_report_credibility, update_device_ml_aggregates, _json_safe
from app.core.submission_guidance import submission_guidance
from app.core.audit import log_action
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from app.core.village_lookup import get_village_location_id, get_village_location_info
from app.schemas.report import CommunityVoteRequest
from sqlalchemy import text, or_, func, cast, String
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)
_SEMANTIC_MODEL = None
_SEMANTIC_MODEL_UNAVAILABLE = False
_LLM_CLIENT = None
_LLM_UNAVAILABLE = False
_LOCAL_NARRATOR = None
_LOCAL_NARRATOR_UNAVAILABLE = False
_SEMANTIC_MODEL_CACHE_DIR = (
    Path(__file__).resolve().parents[3] / "models" / "sentence_transformers"
)


def _get_semantic_matcher():
    """Lazy-load sentence transformer for evidence/description semantic checks."""
    global _SEMANTIC_MODEL, _SEMANTIC_MODEL_UNAVAILABLE
    if _SEMANTIC_MODEL is not None:
        return _SEMANTIC_MODEL
    if _SEMANTIC_MODEL_UNAVAILABLE:
        return None
    try:
        from app.core.model_manager import ensure_sentence_transformer_model
        
        # Use automatic model manager for downloading and caching
        _SEMANTIC_MODEL = ensure_sentence_transformer_model("all-MiniLM-L6-v2")
        return _SEMANTIC_MODEL
    except Exception as exc:
        logger.warning("Semantic model unavailable for evidence matching: %s", exc)
        _SEMANTIC_MODEL_UNAVAILABLE = True
        return None


def _get_llm_client():
    """Lazy-load LLM client for natural-language narration."""
    global _LLM_CLIENT, _LLM_UNAVAILABLE
    if _LLM_CLIENT is not None:
        return _LLM_CLIENT
    if _LLM_UNAVAILABLE or not settings.llm_narrative_enabled:
        return None
    if not settings.llm_api_key:
        _LLM_UNAVAILABLE = True
        logger.info("LLM narrative generation disabled: no llm_api_key configured")
        return None
    try:
        from openai import OpenAI
        kwargs = {"api_key": settings.llm_api_key}
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        _LLM_CLIENT = OpenAI(**kwargs)
        return _LLM_CLIENT
    except Exception as exc:
        logger.warning("LLM client unavailable: %s", exc)
        _LLM_UNAVAILABLE = True
        return None


def _get_local_narrator():
    """Lazy-load local narrative pipeline for offline/no-key operation."""
    global _LOCAL_NARRATOR, _LOCAL_NARRATOR_UNAVAILABLE
    if _LOCAL_NARRATOR is not None:
        return _LOCAL_NARRATOR
    if _LOCAL_NARRATOR_UNAVAILABLE or not settings.llm_narrative_enabled:
        return None
    if not settings.llm_use_local_fallback:
        return None
    try:
        from app.core.model_manager import ensure_local_narrative_pipeline

        _LOCAL_NARRATOR = ensure_local_narrative_pipeline(settings.llm_local_model)
        return _LOCAL_NARRATOR
    except Exception as exc:
        logger.warning("Local narrator unavailable: %s", exc)
        _LOCAL_NARRATOR_UNAVAILABLE = True
        return None


def _generate_with_local_narrator(prompt: str, *, max_chars: int = 3000) -> Optional[str]:
    generator = _get_local_narrator()
    if generator is None:
        return None
    try:
        out = generator(prompt, max_new_tokens=280, do_sample=True, temperature=0.5)
        if isinstance(out, list) and out:
            text = str(out[0].get("generated_text", "")).strip()
            if text:
                return text[:max_chars]
    except Exception as exc:
        logger.warning("Local narrator generation failed: %s", exc)
    return None


def _naturalize_ai_text(
    *,
    text_kind: str,
    structured_text: str,
    must_include: Optional[List[str]] = None,
) -> str:
    """Rewrite structured AI text into natural, human-like narration."""
    client = _get_llm_client()
    fallback = (structured_text or "").strip()
    if not fallback:
        return f"{text_kind.title()} narrative unavailable."
    if client is None:
        local_prompt = (
            f"Rewrite this {text_kind} in clear, human language. Keep facts unchanged.\n\n{fallback}"
        )
        local_text = _generate_with_local_narrator(local_prompt, max_chars=3000)
        if local_text:
            return local_text
        return f"{text_kind.title()} narrative unavailable."
    include_lines = "\n".join(f"- {x}" for x in (must_include or []) if str(x).strip())
    prompt = (
        f"Rewrite this {text_kind} summary into natural, clear human language.\n"
        "Keep all facts unchanged. Do not invent details. Keep causal reasoning explicit.\n"
        "If there are decision drivers, explain why each driver affected the outcome.\n"
        "Return plain text only.\n\n"
        "Facts that must remain present:\n"
        f"{include_lines if include_lines else '- Preserve all key facts from input'}\n\n"
        "INPUT:\n"
        f"{fallback}"
    )
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": "You write concise, professional incident-analysis explanations."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )
        content = ((response.choices or [None])[0].message.content or "").strip() if response else ""
        if content:
            return content[:3000]
    except Exception as exc:
        logger.warning("LLM narrative generation failed (%s): %s", text_kind, exc)
    return f"{text_kind.title()} narrative unavailable."


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON object extraction from model output."""
    text = (raw_text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _looks_template_like(text: str) -> bool:
    """Detect repetitive/template-like phrasing to trigger fallback."""
    t = (text or "").lower()
    boilerplate_hits = 0
    for marker in [
        "incident type considered",
        "reporter description considered",
        "rule status:",
        "ml label:",
        "decision patterns:",
        "pattern explanations:",
        "report context:",
    ]:
        if marker in t:
            boilerplate_hits += 1
    return boilerplate_hits >= 4


def _generate_grounded_narrative(
    *,
    text_kind: str,
    snapshot: Dict[str, Any],
    fallback_text: str,
) -> str:
    """Generate human narrative from structured model snapshot."""
    client = _get_llm_client()
    if not isinstance(snapshot, dict):
        return f"{text_kind.title()} narrative unavailable."

    snapshot_json = json.dumps(snapshot, ensure_ascii=True)
    prompt = (
        "Use ONLY the JSON facts below to write a human-like verification narrative.\n"
        "Do not invent details. Do not copy template phrases.\n"
        "Return JSON only with keys:\n"
        "narrative_summary (2-4 sentences), decision_explanation (array of 2-4 bullets), "
        "uncertainty_note (1 sentence), recommended_next_step (1 sentence).\n\n"
        "INPUT JSON:\n"
        f"{snapshot_json}"
    )
    try:
        raw = ""
        if client is not None:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "You write clear, natural, evidence-grounded public safety analysis."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35,
                max_tokens=settings.llm_max_tokens,
                timeout=settings.llm_timeout_seconds,
            )
            raw = ((response.choices or [None])[0].message.content or "").strip() if response else ""
        else:
            # Local model fallback: we still ask for JSON so parsing path stays consistent.
            local_raw = _generate_with_local_narrator(prompt, max_chars=3200)
            raw = (local_raw or "").strip()
        payload = _extract_json_object(raw)
        if not payload:
            return f"{text_kind.title()} narrative unavailable."
        summary = str(payload.get("narrative_summary", "")).strip()
        bullets = payload.get("decision_explanation") if isinstance(payload.get("decision_explanation"), list) else []
        uncertainty = str(payload.get("uncertainty_note", "")).strip()
        next_step = str(payload.get("recommended_next_step", "")).strip()
        bullet_text = "; ".join(str(b).strip() for b in bullets if str(b).strip())[:1400]
        out_parts = [summary]
        if bullet_text:
            out_parts.append(f"Why this decision: {bullet_text}.")
        if uncertainty:
            out_parts.append(f"Uncertainty: {uncertainty}")
        if next_step:
            out_parts.append(f"Next step: {next_step}")
        candidate = " ".join(p for p in out_parts if p).strip()[:3000]
        if not candidate or _looks_template_like(candidate):
            return f"{text_kind.title()} narrative unavailable."
        return candidate
    except Exception as exc:
        logger.warning("Grounded narrative generation failed (%s): %s", text_kind, exc)
        return f"{text_kind.title()} narrative unavailable."


def warmup_narrative_models_on_startup() -> None:
    """
    Warm-up narrative components on startup (YOLO-like operational behavior).
    - Initializes semantic matcher if enabled.
    - Initializes LLM client and performs a minimal readiness call.
    """
    try:
        if settings.enable_semantic_match:
            _get_semantic_matcher()
            logger.info("Semantic matcher warm-up complete")
    except Exception as exc:
        logger.warning("Semantic matcher warm-up failed: %s", exc)

    try:
        client = _get_llm_client()
        if client is not None:
            # Minimal readiness ping to force connection/auth/model validation at startup.
            client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": "ok"}],
                temperature=0,
                max_tokens=4,
                timeout=settings.llm_timeout_seconds,
            )
            logger.info("Remote LLM narrative warm-up complete")
        else:
            local_gen = _get_local_narrator()
            if local_gen is not None:
                _generate_with_local_narrator("Summarize: startup check", max_chars=64)
                logger.info("Local LLM narrative warm-up complete")
            else:
                logger.info("LLM narrative warm-up skipped (no remote/local model available)")
    except Exception as exc:
        logger.warning("LLM narrative warm-up failed: %s", exc)


def _build_evidence_semantic_text(evidence_validations: List[Dict[str, Any]]) -> str:
    """Create a compact semantic description from evidence validation outputs."""
    fragments: List[str] = []
    for item in evidence_validations or []:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        advanced = validation.get("advanced_analysis") or {}

        objects = summary.get("detected_objects") or []
        if isinstance(objects, list) and objects:
            fragments.append("objects: " + ", ".join(str(o) for o in objects[:10]))

        extracted_text = summary.get("extracted_text")
        if isinstance(extracted_text, str) and extracted_text.strip():
            fragments.append("text: " + extracted_text.strip()[:300])

        actions = advanced.get("actions_detected") or []
        if isinstance(actions, list) and actions:
            fragments.append("actions: " + ", ".join(str(a) for a in actions[:8]))

        scene_context = advanced.get("scene_context") or {}
        lighting = scene_context.get("lighting")
        weather = scene_context.get("weather")
        indoor = scene_context.get("is_indoor")
        scene_bits = []
        if isinstance(indoor, bool):
            scene_bits.append("indoor" if indoor else "outdoor")
        if lighting:
            scene_bits.append(str(lighting))
        if weather:
            scene_bits.append(str(weather))
        if scene_bits:
            fragments.append("scene: " + ", ".join(scene_bits))

        media_type = summary.get("media_type")
        if media_type:
            fragments.append(f"media_type: {media_type}")

    return " | ".join(fragments)[:2000]


def _semantic_alignment_check(
    *,
    report_description: str,
    incident_type_name: str,
    incident_type_description: str,
    evidence_semantic_text: str,
) -> Optional[Dict[str, Any]]:
    """Compare reporter description against evidence semantics and incident semantics."""
    model = _get_semantic_matcher()
    if model is None:
        return None

    desc = (report_description or "").strip()
    evidence = (evidence_semantic_text or "").strip()
    if len(desc) < 10 or len(evidence) < 10:
        return None

    incident_text = f"{(incident_type_name or '').strip()}: {(incident_type_description or '').strip()}".strip(": ").strip()
    try:
        from sentence_transformers import util
        emb = model.encode([desc, evidence, incident_text], convert_to_tensor=True, normalize_embeddings=True)
        desc_evidence = float(util.cos_sim(emb[0], emb[1]).item())
        incident_evidence = float(util.cos_sim(emb[2], emb[1]).item()) if incident_text else 0.0
        desc_incident = float(util.cos_sim(emb[0], emb[2]).item()) if incident_text else 0.0
    except Exception as exc:
        logger.warning("Semantic alignment check failed: %s", exc)
        return None

    # Conservative mismatch rule to avoid over-rejecting valid reports.
    mismatch = (
        desc_evidence < 0.32
        and incident_evidence < 0.34
        and desc_incident < 0.38
    )
    return {
        "model": "all-MiniLM-L6-v2",
        "description_evidence_similarity": round(desc_evidence, 4),
        "incident_evidence_similarity": round(incident_evidence, 4),
        "description_incident_similarity": round(desc_incident, 4),
        "mismatch": bool(mismatch),
    }


def _build_ai_analysis_snapshot(
    *,
    verification_status: Optional[str],
    rule_status: Optional[str],
    is_flagged: Optional[bool],
    flag_reason: Optional[str],
    ml_prediction_label: Optional[str],
    trust_score: Optional[float],
    semantic_alignment: Optional[Dict[str, Any]],
    incident_type_name: Optional[str],
    reporter_description: Optional[str],
    context_tags: Optional[List[str]],
    unified_validation: Optional[Dict[str, Any]],
    scorecard: Optional[Dict[str, Any]] = None,
    evidence_validations: Optional[List[Dict[str, Any]]] = None,
    evidence_file_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Build structured, model-grounded snapshot for narrative generation."""
    model_breakdown = (
        unified_validation.get("model_breakdown", {})
        if isinstance(unified_validation, dict) and isinstance(unified_validation.get("model_breakdown"), dict)
        else {}
    )
    rules_triggered: List[Dict[str, Any]] = []
    if flag_reason:
        rules_triggered.append(
            {
                "code": str(flag_reason).upper().replace("-", "_").replace(" ", "_"),
                "severity": "high" if (rule_status or "").lower() == "rejected" else "medium",
                "explanation": str(flag_reason),
            }
        )
    hard_gates = []
    if (rule_status or "").lower() == "rejected":
        hard_gates.append("RULE_REJECTED")
    if is_flagged:
        hard_gates.append("RULE_FLAGGED")

    evidence_count = evidence_file_count
    if evidence_count is None:
        evidence_count = len(evidence_validations or [])

    return {
        "incident_type": (incident_type_name or "").strip(),
        "reporter_description": (reporter_description or "").strip(),
        "context_tags": [str(t).strip() for t in (context_tags or []) if str(t).strip()],
        "final_decision": {
            "status": (verification_status or "pending").lower(),
            "rule_status": (rule_status or "unknown").lower(),
            "is_flagged": bool(is_flagged),
            "trust_score": float(trust_score) if trust_score is not None else None,
            "label": (ml_prediction_label or "").strip().lower() or None,
            "threshold_band": (
                scorecard.get("threshold_band")
                if isinstance(scorecard, dict)
                else None
            ),
        },
        "model_signals": {
            "natural_language": {
                "description_evidence_similarity": (
                    semantic_alignment.get("description_evidence_similarity")
                    if isinstance(semantic_alignment, dict)
                    else None
                ),
                "incident_evidence_similarity": (
                    semantic_alignment.get("incident_evidence_similarity")
                    if isinstance(semantic_alignment, dict)
                    else None
                ),
                "description_incident_similarity": (
                    semantic_alignment.get("description_incident_similarity")
                    if isinstance(semantic_alignment, dict)
                    else None
                ),
                "mismatch": (
                    bool(semantic_alignment.get("mismatch"))
                    if isinstance(semantic_alignment, dict)
                    else None
                ),
                "breakdown": model_breakdown.get("natural_language", {}),
            },
            "trustbond": model_breakdown.get("trustbond", {}),
            "evidence_ai": {
                "has_evidence": bool(evidence_count and evidence_count > 0),
                "evidence_count": int(evidence_count or 0),
                "breakdown": model_breakdown.get("volo", {}),
            },
            "base": model_breakdown.get("base", {}),
        },
        "rules": {
            "triggered": rules_triggered,
            "hard_gates": hard_gates,
        },
        "scorecard": scorecard if isinstance(scorecard, dict) else {},
    }


def _persist_ai_analysis_snapshot(report: Report, snapshot: Dict[str, Any]) -> None:
    """Persist structured AI analysis for auditability and future regeneration."""
    if not isinstance(snapshot, dict):
        return
    existing = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv = dict(existing)
    fv["ai_analysis_snapshot"] = _json_safe(snapshot)
    report.feature_vector = _json_safe(fv)


def _compose_ai_evidence_description(
    evidence_validations: List[Dict[str, Any]],
    *,
    incident_type_name: Optional[str] = None,
    reporter_description: Optional[str] = None,
    context_tags: Optional[List[str]] = None,
    evidence_file_count: Optional[int] = None,
    evidence_media_types: Optional[List[str]] = None,
    unified_validation: Optional[Dict[str, Any]] = None,
    scorecard: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a short, human-readable AI summary of uploaded evidence + report context."""
    incident_label = (incident_type_name or "incident").strip() or "incident"
    desc_excerpt = (reporter_description or "").strip()
    desc_excerpt = " ".join(desc_excerpt.split())
    if len(desc_excerpt) > 180:
        desc_excerpt = f"{desc_excerpt[:177]}..."
    tags = [str(t).strip() for t in (context_tags or []) if str(t).strip()]
    tags_text = ", ".join(tags[:6]) if tags else None

    if not evidence_validations:
        media_types = [str(m).strip() for m in (evidence_media_types or []) if str(m).strip()]
        media_text = ", ".join(sorted(set(media_types))) if media_types else "photo/video/audio"
        if (evidence_file_count or 0) > 0:
            parts = [
                f"Report context: {incident_label}.",
                (
                    f"{evidence_file_count} evidence file(s) uploaded ({media_text}), "
                    "but detailed AI evidence analysis is not available for this legacy record."
                ),
                "Verification therefore relies on reporter description, metadata checks, and available rule/ML signals.",
            ]
            if desc_excerpt:
                parts.append(f"Reporter states: {desc_excerpt}.")
            if tags_text:
                parts.append(f"Context tags: {tags_text}.")
            fallback_text = " ".join(parts)[:2000]
            snapshot = _build_ai_analysis_snapshot(
                verification_status=None,
                rule_status=None,
                is_flagged=None,
                flag_reason=None,
                ml_prediction_label=None,
                trust_score=None,
                semantic_alignment=None,
                incident_type_name=incident_type_name,
                reporter_description=reporter_description,
                context_tags=context_tags,
                unified_validation=unified_validation,
                scorecard=scorecard,
                evidence_validations=evidence_validations,
                evidence_file_count=evidence_file_count,
            )
            return _generate_grounded_narrative(
                text_kind="evidence summary",
                snapshot=snapshot,
                fallback_text=_naturalize_ai_text(
                    text_kind="evidence summary",
                    structured_text=fallback_text,
                    must_include=[incident_label, desc_excerpt, tags_text or "", media_text],
                ),
            )
        parts = [
            f"Report context: {incident_label}.",
            "No evidence files uploaded; verification relies on reporter description and metadata checks.",
        ]
        if desc_excerpt:
            parts.append(f"Reporter states: {desc_excerpt}.")
        if tags_text:
            parts.append(f"Context tags: {tags_text}.")
        fallback_text = " ".join(parts)[:2000]
        snapshot = _build_ai_analysis_snapshot(
            verification_status=None,
            rule_status=None,
            is_flagged=None,
            flag_reason=None,
            ml_prediction_label=None,
            trust_score=None,
            semantic_alignment=None,
            incident_type_name=incident_type_name,
            reporter_description=reporter_description,
            context_tags=context_tags,
            unified_validation=unified_validation,
            scorecard=scorecard,
            evidence_validations=evidence_validations,
            evidence_file_count=evidence_file_count,
        )
        return _generate_grounded_narrative(
            text_kind="evidence summary",
            snapshot=snapshot,
            fallback_text=_naturalize_ai_text(
                text_kind="evidence summary",
                structured_text=fallback_text,
                must_include=[incident_label, desc_excerpt, tags_text or "no context tags"],
            ),
        )

    media_types: List[str] = []
    object_counter: Dict[str, int] = {}
    quality_scores: List[float] = []

    for item in evidence_validations:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        advanced = validation.get("advanced_analysis") or {}

        media_type = summary.get("media_type") or advanced.get("media_type")
        if isinstance(media_type, str) and media_type.strip():
            media_types.append(media_type.strip())

        for obj in summary.get("detected_objects") or []:
            key = str(obj).strip().lower()
            if key:
                object_counter[key] = object_counter.get(key, 0) + 1

        quality = summary.get("quality_score")
        try:
            if quality is not None:
                quality_scores.append(float(quality))
        except Exception:
            pass

    top_objects = sorted(object_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    object_text = ", ".join(obj for obj, _ in top_objects) if top_objects else "no clear objects"
    avg_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else None
    media_text = ", ".join(sorted(set(media_types))) if media_types else "photo/video/audio"

    quality_text = ""
    if avg_quality is not None:
        quality_text = f" Average evidence quality score is {avg_quality:.2f}."

    parts = [
        f"Report context: {incident_label}.",
        f"AI analyzed {len(evidence_validations)} evidence file(s) ({media_text}).",
        f"Most visible evidence cues: {object_text}.{quality_text}".strip(),
    ]
    if desc_excerpt:
        parts.append(f"Reporter states: {desc_excerpt}.")
    if tags_text:
        parts.append(f"Context tags: {tags_text}.")
    fallback_text = " ".join(parts)[:2000]
    snapshot = _build_ai_analysis_snapshot(
        verification_status=None,
        rule_status=None,
        is_flagged=None,
        flag_reason=None,
        ml_prediction_label=None,
        trust_score=None,
        semantic_alignment=None,
        incident_type_name=incident_type_name,
        reporter_description=reporter_description,
        context_tags=context_tags,
        unified_validation=unified_validation,
        scorecard=scorecard,
        evidence_validations=evidence_validations,
        evidence_file_count=evidence_file_count,
    )
    return _generate_grounded_narrative(
        text_kind="evidence summary",
        snapshot=snapshot,
        fallback_text=_naturalize_ai_text(
            text_kind="evidence summary",
            structured_text=fallback_text,
            must_include=[incident_label, object_text, media_text, desc_excerpt],
        ),
    )


def _compose_ai_verification_reason(
    *,
    verification_status: Optional[str],
    rule_status: Optional[str],
    is_flagged: Optional[bool],
    flag_reason: Optional[str],
    ml_prediction_label: Optional[str],
    trust_score: Optional[float],
    semantic_alignment: Optional[Dict[str, Any]],
    incident_type_name: Optional[str] = None,
    reporter_description: Optional[str] = None,
    context_tags: Optional[List[str]] = None,
    reviewer_note: Optional[str] = None,
    unified_validation: Optional[Dict[str, Any]] = None,
    scorecard: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate an audit-friendly reason for AI confirmation/flag/rejection."""
    status = (verification_status or "pending").lower()
    parts: List[str] = []
    cause_parts: List[str] = []
    incident_label = (incident_type_name or "incident").strip() or "incident"
    desc_excerpt = (reporter_description or "").strip()
    desc_excerpt = " ".join(desc_excerpt.split())
    if len(desc_excerpt) > 180:
        desc_excerpt = f"{desc_excerpt[:177]}..."
    tags = [str(t).strip() for t in (context_tags or []) if str(t).strip()]
    tags_text = ", ".join(tags[:6]) if tags else None

    if status == "verified":
        parts.append("AI verification result: confirmed.")
    elif status == "rejected":
        parts.append("AI verification result: rejected.")
    elif status == "under_review":
        parts.append("AI verification result: pending human review.")
    else:
        parts.append("AI verification result: pending.")

    parts.append(f"Incident type considered: {incident_label}.")
    if desc_excerpt:
        parts.append(f"Reporter description considered: {desc_excerpt}.")
    if tags_text:
        parts.append(f"Context tags considered: {tags_text}.")

    if rule_status:
        parts.append(f"Rule status: {rule_status}.")
    if is_flagged:
        parts.append("Report is flagged.")
    pattern_codes: List[str] = []
    pattern_explanations: List[str] = []

    def _add_pattern(code: str, explanation: str) -> None:
        if code not in pattern_codes:
            pattern_codes.append(code)
            pattern_explanations.append(f"{code}: {explanation}")

    if flag_reason:
        parts.append(f"Primary reason: {flag_reason}.")
        cause_parts.append(f"rule trigger ({flag_reason})")
        raw_reason = str(flag_reason).strip().lower().replace("-", "_").replace(" ", "_")
        reason_map = {
            "description_evidence_mismatch": (
                "CONTEXT_MISMATCH",
                "report description does not align with evidence semantics",
            ),
            "evidence_incident_mismatch": (
                "EVIDENCE_INCIDENT_MISMATCH",
                "detected evidence cues do not support the selected incident type",
            ),
            "text_only_validation_failed": (
                "UNCLEAR_DESCRIPTION",
                "text-only checks found the description too weak/ambiguous for reliable verification",
            ),
            "unclear_description": (
                "UNCLEAR_DESCRIPTION",
                "description quality is too low for reliable incident validation",
            ),
            "out_of_musanze_boundary": (
                "LOCATION_OUT_OF_BOUNDARY",
                "report location is outside the allowed operational boundary",
            ),
            "rejected_by_reviewer": (
                "HUMAN_REJECTION",
                "police reviewer explicitly rejected the report",
            ),
            "duplicate_report": (
                "DUPLICATE_REPORT",
                "report appears to duplicate an existing incident submission",
            ),
            "spam_report": (
                "SPAM_PATTERN",
                "report matches spam/noise submission patterns",
            ),
            "tampered_evidence": (
                "TAMPERED_EVIDENCE",
                "evidence integrity checks indicate potential manipulation",
            ),
            "evidence_source_invalid": (
                "INVALID_EVIDENCE_SOURCE",
                "evidence source check failed (likely non-original capture)",
            ),
            "screenshot_detected": (
                "SCREENSHOT_EVIDENCE",
                "uploaded media appears to be a screenshot/repost instead of original capture",
            ),
        }
        mapped = reason_map.get(raw_reason)
        if mapped:
            _add_pattern(mapped[0], mapped[1])
        else:
            # Fallback pattern inference for free-text/legacy reasons.
            if "duplicate" in raw_reason:
                _add_pattern(
                    "DUPLICATE_REPORT",
                    "report appears to duplicate an existing incident submission",
                )
            elif "spam" in raw_reason:
                _add_pattern(
                    "SPAM_PATTERN",
                    "report matches spam/noise submission patterns",
                )
            elif "tamper" in raw_reason or "manipulat" in raw_reason:
                _add_pattern(
                    "TAMPERED_EVIDENCE",
                    "evidence integrity checks indicate potential manipulation",
                )
            elif "screenshot" in raw_reason:
                _add_pattern(
                    "SCREENSHOT_EVIDENCE",
                    "uploaded media appears to be a screenshot/repost instead of original capture",
                )
            elif "source" in raw_reason and ("invalid" in raw_reason or "fail" in raw_reason):
                _add_pattern(
                    "INVALID_EVIDENCE_SOURCE",
                    "evidence source check failed (likely non-original capture)",
                )
            elif "boundary" in raw_reason or "location" in raw_reason:
                _add_pattern(
                    "LOCATION_CONFLICT",
                    "location/boundary checks found an inconsistency",
                )
            elif "context" in raw_reason or "mismatch" in raw_reason:
                _add_pattern(
                    "CONTEXT_MISMATCH",
                    "description/incident/evidence context appears inconsistent",
                )
            elif "unclear" in raw_reason or "insufficient" in raw_reason:
                _add_pattern(
                    "UNCLEAR_DESCRIPTION",
                    "description quality is too low for reliable incident validation",
                )
            else:
                _add_pattern("RULE_TRIGGER", f"rule engine raised: {flag_reason}")
    if ml_prediction_label:
        if trust_score is not None:
            parts.append(f"ML label: {ml_prediction_label} (trust {trust_score:.2f}%).")
        else:
            parts.append(f"ML label: {ml_prediction_label}.")
        if ml_prediction_label in {"fake", "suspicious"}:
            cause_parts.append(f"low-credibility ML outcome ({ml_prediction_label})")
            _add_pattern(
                "LOW_TRUST_SCORE",
                f"ML classified report as {ml_prediction_label} with low/uncertain credibility",
            )
        elif ml_prediction_label == "likely_real":
            cause_parts.append("high-credibility ML outcome")
            _add_pattern(
                "HIGH_TRUST_SCORE",
                "ML credibility score supports authenticity",
            )

    # Add transparent scoring breakdown if unified validation is available
    if unified_validation:
        model_breakdown = unified_validation.get("model_breakdown", {})
        if model_breakdown:
            parts.append("AI scoring breakdown:")
            for model_name, model_data in model_breakdown.items():
                raw_score = model_data.get("raw_score", 0)
                contribution = model_data.get("contribution", 0)
                is_valid = model_data.get("is_valid", False)
                focus = model_data.get("metadata", {}).get("focus", "analysis")
                
                if model_name == "trustbond":
                    if is_valid:
                        parts.append(f"- Location & device validation: {raw_score:.1f}/100 (contribution: {contribution:.1f})")
                    else:
                        parts.append(f"- Location & device validation: {raw_score:.1f}/100 (below threshold - no contribution)")
                elif model_name == "natural_language":
                    if is_valid:
                        parts.append(f"- Description quality & semantic analysis: {raw_score:.1f}/100 (contribution: {contribution:.1f})")
                    else:
                        parts.append(f"- Description quality & semantic analysis: {raw_score:.1f}/100 (below threshold - no contribution)")
                elif model_name == "volo":
                    if is_valid:
                        parts.append(f"- Evidence quality & object detection: {raw_score:.1f}/100 (contribution: {contribution:.1f})")
                    else:
                        parts.append(f"- Evidence quality & object detection: {raw_score:.1f}/100 (below threshold - no contribution)")
                elif model_name == "base":
                    parts.append(f"- Base credibility score: {raw_score:.1f}/100")
            
            # Add trust band explanation
            trust_band = unified_validation.get("trust_band", "")
            aggregated_score = unified_validation.get("aggregated_score", 0)
            if trust_band == "high_confidence":
                parts.append(f"Overall trust score: {aggregated_score:.1f}/100 (high confidence - multiple validation models agree)")
            elif trust_band == "medium_confidence":
                parts.append(f"Overall trust score: {aggregated_score:.1f}/100 (medium confidence - some concerns detected)")
            elif trust_band == "low_confidence":
                parts.append(f"Overall trust score: {aggregated_score:.1f}/100 (low confidence - significant concerns require review)")
            elif trust_band == "reject":
                parts.append(f"Overall trust score: {aggregated_score:.1f}/100 (rejected - multiple validation failures)")

    if semantic_alignment:
        de = semantic_alignment.get("description_evidence_similarity")
        ie = semantic_alignment.get("incident_evidence_similarity")
        mismatch = semantic_alignment.get("mismatch")
        if de is not None and ie is not None:
            parts.append(
                f"Semantic similarity (description-evidence={de}, incident-evidence={ie})."
            )
        if mismatch is True:
            parts.append("Semantic mismatch detected.")
            cause_parts.append("description/evidence semantic mismatch")
            _add_pattern(
                "CONTEXT_MISMATCH",
                "semantic comparison shows mismatch between description, incident type, and evidence",
            )

    if rule_status == "rejected":
        cause_parts.append("hard rule rejection")
        _add_pattern(
            "RULE_REJECTION",
            "rule engine produced a hard rejection state",
        )
    elif rule_status == "flagged":
        cause_parts.append("rule-based flag")
        _add_pattern(
            "RULE_FLAGGED",
            "rule engine marked report for investigation",
        )
    elif rule_status == "passed":
        _add_pattern(
            "RULES_PASSED",
            "rule checks passed without blocking violations",
        )

    if status == "rejected":
        _add_pattern("FINAL_REJECTED", "final decision is rejected")
        if cause_parts:
            parts.append(f"Decision drivers: {', '.join(dict.fromkeys(cause_parts))}.")
        else:
            parts.append(
                "Decision drivers: report failed policy/rule thresholds during verification."
            )
    elif status in {"under_review", "pending"}:
        _add_pattern("FINAL_PENDING_REVIEW", "final decision is pending human review")
        if cause_parts:
            parts.append(
                f"Review is pending because these signals need human confirmation: {', '.join(dict.fromkeys(cause_parts))}."
            )
        else:
            parts.append(
                "Review is pending because current signals are insufficient for automatic confirmation."
            )
    elif status == "verified":
        _add_pattern("FINAL_CONFIRMED", "final decision is confirmed")
        positive_signals: List[str] = []
        if rule_status == "passed":
            positive_signals.append("rule checks passed")
        if semantic_alignment and semantic_alignment.get("mismatch") is False:
            positive_signals.append("semantic alignment is acceptable")
        if ml_prediction_label == "likely_real":
            positive_signals.append("ML credibility is high")
        if positive_signals:
            parts.append(f"Decision drivers: {', '.join(positive_signals)}.")
        else:
            parts.append("Decision drivers: no blocking rule or semantic conflicts were found.")

    note = (reviewer_note or "").strip()
    if note:
        parts.append(f"Reviewer note: {note}.")
        if status == "verified":
            _add_pattern("HUMAN_CONFIRMED", "police reviewer confirmed the report")
        elif status == "rejected":
            _add_pattern("HUMAN_REJECTION", "police reviewer rejected the report")

    if pattern_codes:
        parts.append(f"Decision patterns: {', '.join(pattern_codes)}.")
    if pattern_explanations:
        parts.append(f"Pattern explanations: {'; '.join(pattern_explanations)}.")
    fallback_text = " ".join(parts)[:3000]
    naturalized = _naturalize_ai_text(
        text_kind="verification reason",
        structured_text=fallback_text,
        must_include=[
            f"verification status: {status}",
            f"incident: {incident_label}",
            f"rule_status: {rule_status or 'unknown'}",
            f"flag_reason: {flag_reason or 'none'}",
            f"ml_label: {ml_prediction_label or 'none'}",
            f"decision_patterns: {', '.join(pattern_codes) if pattern_codes else 'none'}",
        ],
    )
    snapshot = _build_ai_analysis_snapshot(
        verification_status=verification_status,
        rule_status=rule_status,
        is_flagged=is_flagged,
        flag_reason=flag_reason,
        ml_prediction_label=ml_prediction_label,
        trust_score=trust_score,
        semantic_alignment=semantic_alignment,
        incident_type_name=incident_type_name,
        reporter_description=reporter_description,
        context_tags=context_tags,
        unified_validation=unified_validation,
        scorecard=scorecard,
    )
    grounded = _generate_grounded_narrative(
        text_kind="verification reason",
        snapshot=snapshot,
        fallback_text=naturalized,
    )
    decision_line = (
        f"Decision patterns: {', '.join(pattern_codes)}."
        if pattern_codes
        else "Decision patterns: NONE."
    )
    explanation_line = (
        f"Pattern explanations: {'; '.join(pattern_explanations)}."
        if pattern_explanations
        else "Pattern explanations: NONE."
    )
    composed = f"{grounded}\n{decision_line}\n{explanation_line}".strip()
    return composed[:3000]


def _extract_decision_patterns(ai_verification_reason: Optional[str]) -> List[str]:
    """Parse machine-readable decision pattern codes from generated reason text."""
    text = (ai_verification_reason or "").strip()
    if not text:
        return []
    marker = "Decision patterns:"
    idx = text.find(marker)
    if idx < 0:
        return []
    tail = text[idx + len(marker):].strip()
    if not tail:
        return []
    # Keep only the comma-separated token segment before next sentence block.
    segment = tail.split(". Pattern explanations:", 1)[0]
    segment = segment.split(".", 1)[0]
    codes = [c.strip() for c in segment.split(",") if c.strip()]
    seen = set()
    deduped: List[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            deduped.append(code)
    return deduped


def _extract_decision_pattern_explanations(ai_verification_reason: Optional[str]) -> Dict[str, str]:
    """Parse decision pattern explanations from generated reason text."""
    text = (ai_verification_reason or "").strip()
    if not text:
        return {}
    marker = "Pattern explanations:"
    idx = text.find(marker)
    if idx < 0:
        return {}
    tail = text[idx + len(marker):].strip()
    if not tail:
        return {}
    entries = [e.strip() for e in tail.split(";") if e.strip()]
    parsed: Dict[str, str] = {}
    for entry in entries:
        if ":" not in entry:
            continue
        code, explanation = entry.split(":", 1)
        code = code.strip()
        explanation = explanation.strip().rstrip(".")
        if code and explanation and code not in parsed:
            parsed[code] = explanation
    return parsed


def _resolve_trust_factors(
    report: Report,
    ml_prediction: Optional[Any],
    *,
    evidence_count: Optional[int] = None,
    community_votes: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    Return explainable trust factors for UI.
    Prefer stored ML explanation, but provide a lightweight fallback for legacy rows.
    """
    # Prefer new explicit threshold scorecard if present.
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    scorecard = fv.get("threshold_scorecard") if isinstance(fv.get("threshold_scorecard"), dict) else None
    if scorecard:
        out: Dict[str, Any] = {
            "scorecard_type": scorecard.get("scorecard_type"),
            "max_score": scorecard.get("max_score", 100.0),
            "total_score": scorecard.get("total_score"),
            "threshold_band": scorecard.get("threshold_band"),
            "hard_gates": scorecard.get("hard_gates", []),
            "factors": scorecard.get("factors", {}),
        }
        fac = out.get("factors", {}) if isinstance(out.get("factors"), dict) else {}
        # Compatibility keys expected by existing UI card.
        if "description_quality" in fac:
            out["content_score"] = fac["description_quality"].get("points_awarded")
        elif "evidence_authenticity_quality" in fac:
            out["content_score"] = fac["evidence_authenticity_quality"].get("points_awarded")
        elif "natural_language_contribution" in fac:
            out["content_score"] = fac["natural_language_contribution"].get("points_awarded")
        if "location_plausibility" in fac:
            out["location_score"] = fac["location_plausibility"].get("points_awarded")
        elif "location_consistency" in fac:
            out["location_score"] = fac["location_consistency"].get("points_awarded")
        elif "trustbond_contribution" in fac:
            out["location_score"] = fac["trustbond_contribution"].get("points_awarded")
        out["cluster_score"] = (
            fac.get("incident_evidence_alignment", {}).get("points_awarded", 0.0)
            or fac.get("volo_contribution", {}).get("points_awarded", 0.0)
        )
        out["user_behavior_score"] = (
            fac.get("device_behavior", {}).get("points_awarded", 0.0)
            or fac.get("trustbond_contribution", {}).get("points_awarded", 0.0)
        )
        out["coordination_penalty"] = 0.0
        if community_votes:
            real_votes = int(community_votes.get("real", 0) or 0)
            false_votes = int(community_votes.get("false", 0) or 0)
            out["community_net_votes"] = real_votes - false_votes
        return out

    # Compute scorecard dynamically for rows that predate threshold persistence.
    computed = _compute_threshold_scorecard(
        report,
        ml_prediction=ml_prediction,
        community_votes=community_votes,
        unified_validation=fv.get("unified_validation") if isinstance(fv.get("unified_validation"), dict) else None,
    )
    out: Dict[str, Any] = {
        "scorecard_type": computed.get("scorecard_type"),
        "max_score": computed.get("max_score", 100.0),
        "total_score": computed.get("total_score"),
        "threshold_band": computed.get("threshold_band"),
        "hard_gates": computed.get("hard_gates", []),
        "factors": computed.get("factors", {}),
    }
    fac = out.get("factors", {}) if isinstance(out.get("factors"), dict) else {}
    if "description_quality" in fac:
        out["content_score"] = fac["description_quality"].get("points_awarded")
    elif "evidence_authenticity_quality" in fac:
        out["content_score"] = fac["evidence_authenticity_quality"].get("points_awarded")
    elif "natural_language_contribution" in fac:
        out["content_score"] = fac["natural_language_contribution"].get("points_awarded")
    if "location_plausibility" in fac:
        out["location_score"] = fac["location_plausibility"].get("points_awarded")
    elif "location_consistency" in fac:
        out["location_score"] = fac["location_consistency"].get("points_awarded")
    elif "trustbond_contribution" in fac:
        out["location_score"] = fac["trustbond_contribution"].get("points_awarded")
    out["cluster_score"] = (
        fac.get("incident_evidence_alignment", {}).get("points_awarded", 0.0)
        or fac.get("volo_contribution", {}).get("points_awarded", 0.0)
    )
    out["user_behavior_score"] = (
        fac.get("device_behavior", {}).get("points_awarded", 0.0)
        or fac.get("trustbond_contribution", {}).get("points_awarded", 0.0)
    )
    out["coordination_penalty"] = 0.0
    if community_votes:
        real_votes = int(community_votes.get("real", 0) or 0)
        false_votes = int(community_votes.get("false", 0) or 0)
        out["community_net_votes"] = real_votes - false_votes
    return out


def _rule_adjusted_trust_label(
    report: Report,
    trust_score: Optional[float],
    ml_prediction_label: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Keep ML trust/label consistent with rule outcomes.
    A flagged/rejected rule state must never appear as high-confidence verified ML.
    """
    score = trust_score
    label = (ml_prediction_label or "").strip().lower() or None
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))

    if rule_status == "rejected":
        if score is None:
            score = 20.0
        else:
            score = min(float(score), 20.0)
        label = "fake"
        return score, label

    if rule_status == "flagged" or is_flagged:
        if score is None:
            score = 49.0
        else:
            score = min(float(score), 49.0)
        if label in (None, "likely_real"):
            label = "suspicious"
        return score, label

    return score, label


def _persist_adjusted_ml_prediction(
    db: Session,
    ml_prediction: Optional[Any],
    adjusted_trust_score: Optional[float],
    adjusted_label: Optional[str],
) -> None:
    """Persist adjusted trust/label so API and DB stay aligned."""
    if ml_prediction is None:
        return
    changed = False
    if adjusted_trust_score is not None:
        try:
            new_score = float(adjusted_trust_score)
            old_score = (
                float(ml_prediction.trust_score)
                if getattr(ml_prediction, "trust_score", None) is not None
                else None
            )
            if old_score is None or abs(old_score - new_score) > 1e-6:
                ml_prediction.trust_score = new_score
                changed = True
        except (TypeError, ValueError):
            pass
    if adjusted_label:
        new_label = str(adjusted_label).strip().lower()
        old_label = (
            str(getattr(ml_prediction, "prediction_label", "")).strip().lower()
            if getattr(ml_prediction, "prediction_label", None) is not None
            else ""
        )
        if new_label and new_label != old_label:
            ml_prediction.prediction_label = new_label
            changed = True
    # Canonical per-report score for device trust rollup (after unified + rule gates).
    if hasattr(ml_prediction, "is_final"):
        ml_prediction.is_final = True
    db.add(ml_prediction)


def _compute_threshold_scorecard(
    report: Report,
    *,
    ml_prediction: Optional[Any] = None,
    community_votes: Optional[Dict[str, int]] = None,
    unified_validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute a weighted 100-point threshold scorecard (text-only vs with evidence)."""
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    evidence_validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []
    semantic = fv.get("semantic_alignment") if isinstance(fv.get("semantic_alignment"), dict) else {}
    text_only = fv.get("text_only_validation") if isinstance(fv.get("text_only_validation"), dict) else {}
    has_evidence = len(evidence_validations) > 0 or len(getattr(report, "evidence_files", []) or []) > 0

    votes = community_votes or {"real": 0, "false": 0, "unknown": 0}
    real_votes = int(votes.get("real", 0) or 0)
    false_votes = int(votes.get("false", 0) or 0)
    net_votes = real_votes - false_votes

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    factors: Dict[str, Dict[str, Any]] = {}
    hard_gates: List[str] = []

    # Hard gates from rule engine/boundary controls.
    rule_status = (getattr(report, "rule_status", None) or "").lower()
    flag_reason = (getattr(report, "flag_reason", None) or "").lower()
    if rule_status == "rejected":
        hard_gates.append("RULE_REJECTED")
    if "out_of_musanze_boundary" in flag_reason:
        hard_gates.append("LOCATION_OUT_OF_BOUNDARY")

    # Shared signals
    desc = (getattr(report, "description", None) or "").strip()
    desc_len = len(desc)
    gps_acc = float(getattr(report, "gps_accuracy", 0) or 0)
    speed = float(getattr(report, "movement_speed", 0) or 0)
    device_trust = 50.0
    if getattr(report, "device", None) and getattr(report.device, "device_trust_score", None) is not None:
        device_trust = float(report.device.device_trust_score)

    # Community signal normalized to 0..1 around neutral 0.5
    community_signal = clamp01(0.5 + (net_votes * 0.08))

    # Prefer unified model aggregation when available so no single model concludes on its own.
    if isinstance(unified_validation, dict):
        model_breakdown = (
            unified_validation.get("model_breakdown")
            if isinstance(unified_validation.get("model_breakdown"), dict)
            else {}
        )
        aggregated_score = float(unified_validation.get("aggregated_score") or 0.0)
        scorecard_type = "evidence_scorecard" if has_evidence else "text_only_scorecard"

        factors = {}
        mapping = {
            "trustbond": "trustbond_contribution",
            "natural_language": "natural_language_contribution",
            "volo": "volo_contribution",
            "base": "base_credibility",
        }
        for model_name, factor_name in mapping.items():
            model_data = model_breakdown.get(model_name)
            if not isinstance(model_data, dict):
                continue
            contribution = float(model_data.get("contribution") or 0.0)
            raw_score = float(model_data.get("raw_score") or 0.0)
            factors[factor_name] = {
                "weight": round(contribution, 2),
                "signal": round(clamp01(raw_score / 100.0), 4),
                "points_awarded": round(contribution, 2),
                "model": model_name,
                "is_valid": bool(model_data.get("is_valid", False)),
            }
        factors["community_signal"] = {
            "weight": 0.0,
            "signal": round(community_signal, 4),
            "points_awarded": 0.0,
            "model": "community",
            "is_valid": True,
        }

        total = round(min(100.0, max(0.0, aggregated_score)), 2)
        if hard_gates:
            band = "hard_reject"
        elif not has_evidence:
            if total >= 85.0:
                band = "confirmed_candidate"
            elif total >= 60.0:
                band = "under_review"
            else:
                band = "low_confidence"
        else:
            if total >= 80.0:
                band = "confirmed_candidate"
            elif total >= 55.0:
                band = "under_review"
            else:
                band = "low_confidence"

        return {
            "scorecard_type": scorecard_type,
            "max_score": 100.0,
            "total_score": total,
            "threshold_band": band,
            "hard_gates": hard_gates,
            "factors": factors,
            "decision_source": "unified_validation",
        }

    if not has_evidence:
        # Text-only scorecard
        quality_signal = clamp01((desc_len - 10) / 90.0)
        if not bool(text_only.get("valid", True)) or "unclear" in flag_reason or "gibberish" in flag_reason:
            quality_signal = min(quality_signal, 0.35)
        alignment_signal = 1.0
        if semantic and bool(semantic.get("mismatch")):
            alignment_signal = 0.2
        if "mismatch" in flag_reason:
            alignment_signal = min(alignment_signal, 0.25)
        # Compress behavior influence to a narrow band around neutral.
        behavior_signal = clamp01(0.5 + ((device_trust - 50.0) / 250.0))
        behavior_signal = max(0.35, min(0.65, behavior_signal))
        location_signal = 1.0
        if gps_acc > 0:
            location_signal = clamp01(1.0 - (gps_acc / 250.0))
        if speed * 3.6 > 220:
            location_signal = min(location_signal, 0.2)

        # Stricter text-only policy: emphasize description + incident alignment.
        weights = {
            "description_quality": 38.0,
            "incident_alignment": 34.0,
            "device_behavior": 5.0,
            "location_plausibility": 13.0,
            "community_signal": 10.0,
        }
        signals = {
            "description_quality": quality_signal,
            "incident_alignment": alignment_signal,
            "device_behavior": behavior_signal,
            "location_plausibility": location_signal,
            "community_signal": community_signal,
        }
        scorecard_type = "text_only_scorecard"
    else:
        # Evidence-backed scorecard
        valids = 0
        quality_scores: List[float] = []
        for item in evidence_validations:
            v = (item or {}).get("validation") or {}
            if v.get("valid") is True:
                valids += 1
            qs = ((v.get("analysis_summary") or {}).get("quality_score"))
            if qs is not None:
                try:
                    quality_scores.append(float(qs))
                except Exception:
                    pass
        valid_ratio = clamp01(valids / max(1, len(evidence_validations))) if evidence_validations else 0.6
        avg_quality = clamp01(sum(quality_scores) / len(quality_scores)) if quality_scores else 0.6
        authenticity_signal = clamp01((valid_ratio * 0.7) + (avg_quality * 0.3))

        de = semantic.get("description_evidence_similarity")
        ie = semantic.get("incident_evidence_similarity")
        desc_evidence_signal = clamp01(float(de)) if de is not None else 0.55
        incident_evidence_signal = clamp01(float(ie)) if ie is not None else 0.55
        if semantic and bool(semantic.get("mismatch")):
            desc_evidence_signal = min(desc_evidence_signal, 0.25)
            incident_evidence_signal = min(incident_evidence_signal, 0.25)

        # Compress behavior influence to a narrow band around neutral.
        behavior_signal = clamp01(0.5 + ((device_trust - 50.0) / 250.0))
        behavior_signal = max(0.35, min(0.65, behavior_signal))
        location_signal = 1.0
        if gps_acc > 0:
            location_signal = clamp01(1.0 - (gps_acc / 250.0))
        if speed * 3.6 > 220:
            location_signal = min(location_signal, 0.2)

        # Evidence-first policy: stronger weight on authenticity/quality.
        weights = {
            "evidence_authenticity_quality": 40.0,
            "evidence_description_alignment": 20.0,
            "incident_evidence_alignment": 17.0,
            "device_behavior": 3.0,
            "location_consistency": 15.0,
            "community_signal": 5.0,
        }
        signals = {
            "evidence_authenticity_quality": authenticity_signal,
            "evidence_description_alignment": desc_evidence_signal,
            "incident_evidence_alignment": incident_evidence_signal,
            "device_behavior": behavior_signal,
            "location_consistency": location_signal,
            "community_signal": community_signal,
        }
        scorecard_type = "evidence_scorecard"

    total = 0.0
    for name, weight in weights.items():
        signal = clamp01(signals.get(name, 0.0))
        points = round(weight * signal, 2)
        total += points
        factors[name] = {
            "weight": weight,
            "signal": round(signal, 4),
            "points_awarded": points,
        }
    total = round(min(100.0, max(0.0, total)), 2)

    if hard_gates:
        band = "hard_reject"
    elif not has_evidence:
        # Text-only reports require a higher confidence threshold.
        if total >= 85.0:
            band = "confirmed_candidate"
        elif total >= 60.0:
            band = "under_review"
        else:
            band = "low_confidence"
    else:
        if total >= 80.0:
            band = "confirmed_candidate"
        elif total >= 55.0:
            band = "under_review"
        else:
            band = "low_confidence"

    return {
        "scorecard_type": scorecard_type,
        "max_score": 100.0,
        "total_score": total,
        "threshold_band": band,
        "hard_gates": hard_gates,
        "factors": factors,
    }


def _apply_threshold_outcome(report: Report, scorecard: Dict[str, Any]) -> None:
    """Apply scorecard thresholds to report state while preserving hard rejects."""
    if not isinstance(scorecard, dict):
        return
    band = str(scorecard.get("threshold_band") or "").lower()
    hard_gates = scorecard.get("hard_gates") or []

    # Hard rejections from rule engine/boundary controls take priority.
    if "boundary_reject" in hard_gates or "hard_rule_reject" in hard_gates:
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            report.flag_reason = "boundary_reject" if "boundary_reject" in hard_gates else "hard_rule_reject"
        return

    if band == "low_confidence":
        # Policy: any score below threshold is rejected.
        report.rule_status = "rejected"
        report.verification_status = "rejected"
        report.status = "rejected"
        report.is_flagged = True
        if not getattr(report, "flag_reason", None):
            report.flag_reason = "threshold_low_score"
        return

    if band == "under_review":
        if report.rule_status != "rejected":
            if report.rule_status not in {"flagged"}:
                report.rule_status = "passed"
            report.verification_status = "under_review"
            if report.status != "rejected":
                report.status = "pending"
        return

    if band == "confirmed_candidate":
        if report.rule_status == "passed" and not bool(getattr(report, "is_flagged", False)):
            report.verification_status = "verified"
            if report.status in {None, "", "pending", "flagged"}:
                report.status = "verified"


def _store_unified_validation_result(
    db: Session,
    report: Report,
    validation_result: Any,
) -> Dict[str, Any]:
    """Persist unified validation outputs without letting one model decide the final verdict."""
    from decimal import Decimal
    from app.core.report_review import infer_prediction_label_from_trust_score
    from app.models.ml_prediction import MLPrediction

    aggregated = validation_result.aggregated_trust
    model_breakdown = {
        score.model_name: {
            "raw_score": score.raw_score,
            "contribution": score.contribution,
            "is_valid": score.is_valid,
            "metadata": score.metadata,
        }
        for score in aggregated.model_scores
    }
    unified_validation = {
        "aggregated_score": round(float(aggregated.total_score), 2),
        "trust_band": aggregated.trust_band.value,
        "contributing_models": aggregated.contributing_models,
        "model_breakdown": model_breakdown,
        "validation_metadata": validation_result.validation_metadata,
    }

    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    fv["unified_validation"] = unified_validation
    report.feature_vector = _json_safe(fv)

    ml_prediction = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == report.report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if ml_prediction is not None:
        aggregated_score = round(float(aggregated.total_score), 2)
        ml_prediction.trust_score = Decimal(f"{aggregated_score:.2f}")
        ml_prediction.prediction_label = infer_prediction_label_from_trust_score(aggregated_score)
        explanation = ml_prediction.explanation if isinstance(ml_prediction.explanation, dict) else {}
        explanation["unified_validation"] = unified_validation
        ml_prediction.explanation = _json_safe(explanation)
        # Rule-adjusted score in _persist_adjusted_ml_prediction marks is_final=True.
        if hasattr(ml_prediction, "is_final"):
            ml_prediction.is_final = False

    return unified_validation

def _process_report_background(
    report_id: str,
    device_id: str,
    evidence_count: int,
    evidence_metadata_list: List[dict]
):
    """Background task to process heavy verification without blocking response."""
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        device = db.query(Device).filter(Device.device_id == device_id).first()
        
        if not report or not device:
            logger.error(f"Background processing failed: report {report_id} or device {device_id} not found")
            return
        
        # Check if device was banned after report creation
        if getattr(device, "is_banned", False):
            logger.warning(f"Device {device_id} was banned, rejecting report {report_id} in background processing")
            report.rule_status = "rejected"
            report.verification_status = "rejected"
            report.status = "rejected"
            report.is_flagged = True
            report.flag_reason = "device_banned"
            db.commit()
            return
        
        # 1. Enhanced evidence verification
        verification_issues = []
        for evidence_meta in evidence_metadata_list:
            try:
                # Screenshot detection
                screenshot_result = enhanced_screenshot_detection(
                    filename=evidence_meta["file_url"].split('/')[-1],
                    file_path=evidence_meta["file_url"]
                )
                if screenshot_result["is_screenshot"]:
                    verification_issues.append(f"Screenshot detected: {screenshot_result['details']}")
            except Exception as e:
                logger.warning(f"Screenshot detection failed: {e}")
            
            try:
                # File timing analysis
                timing_result = analyze_file_timing(
                    file_path=evidence_meta["file_url"],
                    file_created_at=evidence_meta.get("captured_at")
                )
                if timing_result["is_suspicious"]:
                    verification_issues.append(f"Suspicious file timing: {timing_result['suspicious_reasons']}")
            except Exception as e:
                logger.warning(f"Timing analysis failed: {e}")
            
            try:
                # Evidence source validation
                source_result = validate_evidence_source(
                    filename=evidence_meta["file_url"].split('/')[-1],
                    file_path=evidence_meta["file_url"]
                )
                if not source_result["is_valid"]:
                    verification_issues.append(f"Invalid evidence source: {source_result['suspicious_indicators']}")
            except Exception as e:
                logger.warning(f"Source validation failed: {e}")
        
        # 2. Location consistency validation
        try:
            location_result = validate_location_consistency(
                report_latitude=float(report.latitude),
                report_longitude=float(report.longitude),
                evidence_metadata=evidence_metadata_list
            )
            if not location_result["is_consistent"]:
                verification_issues.append(f"Location inconsistency detected: {location_result['details']}")
            
            # Store location validation results in report metadata
            fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
            fv["location_validation"] = location_result
            report.feature_vector = _json_safe(fv)
        except Exception as e:
            logger.warning(f"Location consistency validation failed: {e}")
        
        # 3. Unified validation using all models (TrustBond, Natural Language, Volo)
        unified_validation_data = None
        try:
            from app.core.unified_validator import validate_report_unified
            
            # Get evidence files for Volo analysis
            evidence_files = db.query(EvidenceFile).filter(
                EvidenceFile.report_id == report.report_id
            ).all()
            
            # Perform unified validation
            validation_result = validate_report_unified(
                db=db,
                report=report,
                device=device,
                evidence_files=evidence_files
            )
            unified_validation_data = _store_unified_validation_result(db, report, validation_result)
            
            logger.info(f"Unified validation completed for report {report_id} - Score: {validation_result.aggregated_trust.total_score:.2f}")
            
        except Exception as e:
            logger.error(f"Unified validation failed for report {report_id}: {e}")
            # Fallback to basic TrustBond scoring
            try:
                score_report_credibility(db, report, device, evidence_count)
                logger.info(f"Fallback TrustBond scoring completed for report {report_id}")
            except Exception as fallback_e:
                logger.error(f"Fallback scoring also failed for report {report_id}: {fallback_e}")
                raise HTTPException(status_code=500, detail=f"ML scoring failed during report creation: {str(e)}")
        
        # 4. Apply rule-based verification (still needed for basic validation)
        try:
            rule_status, is_flagged, flag_reason = apply_rule_based_status(
                report, evidence_count, db
            )
            report.rule_status = rule_status
            report.is_flagged = bool(getattr(report, "is_flagged", False) or is_flagged)
            if is_flagged and flag_reason and not getattr(report, "flag_reason", None):
                report.flag_reason = flag_reason
        except Exception as e:
            logger.error(f"Rule-based verification failed for report {report_id}: {e}")

        # 4b. Apply threshold decision from aggregated model output + rule gates.
        try:
            votes_bg = {"real": 0, "false": 0, "unknown": 0}
            fv_bg = report.feature_vector if isinstance(report.feature_vector, dict) else {}
            vv_bg = fv_bg.get("community_votes", {}) if isinstance(fv_bg.get("community_votes", {}), dict) else {}
            for v in vv_bg.values():
                k = str(v)
                if k in votes_bg:
                    votes_bg[k] += 1
            ml_prediction_bg = resolve_ml_prediction_for_report(report)
            scorecard_bg = _compute_threshold_scorecard(
                report,
                ml_prediction=ml_prediction_bg,
                community_votes=votes_bg,
                unified_validation=unified_validation_data if isinstance(unified_validation_data, dict) else (
                    fv_bg.get("unified_validation") if isinstance(fv_bg.get("unified_validation"), dict) else None
                ),
            )
            fv_bg["threshold_scorecard"] = scorecard_bg
            report.feature_vector = _json_safe(fv_bg)
            _apply_threshold_outcome(report, scorecard_bg)
            ml_prediction_adj = resolve_ml_prediction_for_report(report)
            ai_ts = (
                float(ml_prediction_adj.trust_score)
                if ml_prediction_adj and getattr(ml_prediction_adj, "trust_score", None) is not None
                else None
            )
            ai_lbl = getattr(ml_prediction_adj, "prediction_label", None)
            ai_ts, ai_lbl = _rule_adjusted_trust_label(report, ai_ts, ai_lbl)
            _persist_adjusted_ml_prediction(db, ml_prediction_adj, ai_ts, ai_lbl)
            try:
                update_device_ml_aggregates(db, device, window=30)
                logger.info("Device ML aggregates updated after final trust for report %s", report_id)
            except Exception as agg_exc:
                logger.error("Device ML aggregates update failed for report %s: %s", report_id, agg_exc)
        except Exception as e:
            logger.error(f"Threshold decision application failed for report {report_id}: {e}")
        
        # 5. Update hotspot clustering
        try:
            if report.status not in ["rejected", "flagged"]:
                create_hotspots_from_reports(db, [report])
        except Exception as e:
            logger.error(f"Hotspot creation failed for report {report_id}: {e}")
        
        db.commit()
        logger.info(f"Background processing completed for report {report_id}")
        
        # Broadcast update to dashboard
        try:
            manager.broadcast({"type": "refresh_data", "entity": "report", "action": "processed"})
        except Exception as e:
            logger.warning(f"Failed to broadcast update for report {report_id}: {e}")
            
    except Exception as e:
        logger.error(f"Background processing error for report {report_id}: {e}")
        db.rollback()
    finally:
        db.close()


def _normalize_evidence_file_url(raw: str | None) -> str | None:
    """
    Ensure evidence file_url is stored as a usable URL/path, not a bare filename.
    - https://... stays as-is (Cloudinary / remote)
    - /uploads/... stays as-is (local static mount)
    - bare filename becomes /uploads/evidence/<filename>
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("/uploads/"):
        return s
    if s.startswith("/"):
        return s
    return f"/uploads/evidence/{s}"

# Evidence AI Analysis functions
def detect_blur(image_bytes: bytes) -> tuple[float, bool]:
    """Detect image blur using Laplacian variance method."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
        
        # Convert bytes to numpy array
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to grayscale
        gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
        
        # Calculate Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Normalize to 0-100 scale (typical range: 100-1000)
        blur_score = min(100.0, max(0.0, (laplacian_var / 10.0)))
        
        # Consider blurry if score < 20
        is_blurry = blur_score < 20.0
        
        return blur_score, is_blurry
        
    except Exception as e:
        logger.error(f"Blur detection failed: {e}")
        return 50.0, False  # Default medium score

def detect_tampering(image_bytes: bytes) -> tuple[float, bool]:
    """Detect potential image tampering using error level analysis."""
    try:
        from PIL import Image
        import numpy as np
        
        # Load image
        image = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Save at quality 95 (high quality)
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=95)
        buffer.seek(0)
        resaved_image = Image.open(buffer)
        
        # Calculate difference
        original_array = np.array(image)
        resaved_array = np.array(resaved_image)
        
        # Calculate mean absolute error
        diff = np.abs(original_array.astype(float) - resaved_array.astype(float))
        mae = np.mean(diff)
        
        # Normalize to 0-100 scale (typical range: 0-50)
        tamper_score = min(100.0, max(0.0, (mae * 2.0)))
        
        # Consider tampered if score > 30
        is_tampered = tamper_score > 30.0
        
        return tamper_score, is_tampered
        
    except Exception as e:
        logger.error(f"Tamper detection failed: {e}")
        return 10.0, False  # Default low score

def assess_image_quality(image_bytes: bytes, blur_score: float, tamper_score: float) -> str:
    """Assess overall image quality based on multiple factors."""
    try:
        from PIL import Image
        
        image = Image.open(io.BytesIO(image_bytes))
        
        # Basic quality metrics
        width, height = image.size
        resolution_score = min(100.0, (width * height) / 10000.0)  # Scale based on resolution
        
        # Aspect ratio penalty for extreme ratios
        aspect_ratio = width / height
        aspect_penalty = 0.0
        if aspect_ratio < 0.5 or aspect_ratio > 2.0:
            aspect_penalty = 20.0
        
        # File size consideration (proxy for compression)
        file_size_score = min(100.0, len(image_bytes) / 10000.0)
        
        # Combined quality score
        quality_score = (
            (blur_score * 0.4) +           # Blur is most important
            ((100 - tamper_score) * 0.3) + # Lower tamper score is better
            (resolution_score * 0.2) +     # Resolution matters
            (file_size_score * 0.1) -      # File size consideration
            aspect_penalty
        )
        
        # Determine quality label
        if quality_score >= 80:
            return "high"
        elif quality_score >= 60:
            return "medium"
        elif quality_score >= 40:
            return "low"
        else:
            return "poor"
            
    except Exception as e:
        logger.error(f"Quality assessment failed: {e}")
        return "fair"  # Default medium quality


def _evidence_suffix(filename: Optional[str], default: str = ".bin") -> str:
    if not filename or "." not in filename:
        return default
    return "." + filename.rsplit(".", 1)[-1].lower()


def _coerce_evidence_quality(label: Optional[str]) -> EvidenceQuality:
    """Map textual quality bands to DB enum (good / fair / poor)."""
    x = (label or "fair").strip().lower()
    if x in ("high", "good"):
        return EvidenceQuality.good
    if x in ("poor", "low"):
        return EvidenceQuality.poor
    return EvidenceQuality.fair


def analyze_evidence_file(
    file_bytes: bytes,
    file_type: str,
    filename: Optional[str] = None,
) -> dict:
    """Analyze uploaded evidence bytes: photo (CV + YOLO), video (frames + YOLO), audio (duration + optional ASR)."""
    analysis: Dict[str, Any] = {
        "blur_score": None,
        "tamper_score": None,
        "quality_label": None,
        "ai_checked_at": datetime.now(timezone.utc),
        "analysis_method": "basic_cv",
        "detected_objects": [],
        "transcript": None,
        "duration_seconds": None,
        "advanced_analysis": {},
        "volo_confidence": None,
    }

    ft = (file_type or "").strip().lower()
    is_photo = ft == "photo" or ft.startswith("image")

    try:
        from app.core.volo_scorer import volo_scorer

        if is_photo:
            blur_score, is_blurry = detect_blur(file_bytes)
            tamper_score, is_tampered = detect_tampering(file_bytes)
            quality_label = assess_image_quality(file_bytes, blur_score, tamper_score)

            detected: List[str] = []
            try:
                detected = volo_scorer.detect_objects_from_image_bytes(file_bytes)
            except Exception as exc:
                logger.warning("Photo object detection skipped: %s", exc)

            analysis.update(
                {
                    "blur_score": round(blur_score, 3),
                    "tamper_score": round(tamper_score, 3),
                    "quality_label": quality_label,
                    "is_blurry": is_blurry,
                    "is_tampered": is_tampered,
                    "detected_objects": detected,
                    "analysis_method": "photo_cv_yolo",
                    "advanced_analysis": {"photo": {"yolo_objects": detected}},
                    "volo_confidence": 0.75 if detected else 0.55,
                }
            )

        elif ft == "video":
            vm = volo_scorer.analyze_video_bytes(file_bytes)
            analysis["advanced_analysis"]["video"] = vm
            if vm.get("error"):
                analysis.update(
                    {
                        "blur_score": None,
                        "tamper_score": 35.0,
                        "quality_label": "fair",
                        "analysis_method": "video_error",
                        "analysis_error": vm.get("error"),
                        "volo_confidence": 0.35,
                    }
                )
            else:
                blur_raw = float(vm.get("blur_score_avg") or 0.0)
                blur_norm = min(100.0, max(0.0, blur_raw / 10.0))
                motion = float(vm.get("motion_mean") or 0.0)
                tamper_guess = max(5.0, min(85.0, 45.0 - min(25.0, motion)))
                objs = list(vm.get("detected_objects") or [])
                frames_done = int(vm.get("frames_sampled") or 0)

                if frames_done == 0:
                    ql = "low"
                elif objs and motion > 1.0:
                    ql = "high"
                elif objs or motion > 0.5:
                    ql = "medium"
                else:
                    ql = "fair"

                dur = vm.get("duration_guess_seconds")
                analysis.update(
                    {
                        "blur_score": round(blur_norm, 3),
                        "tamper_score": round(tamper_guess, 3),
                        "quality_label": ql,
                        "analysis_method": "video_frames_yolo",
                        "detected_objects": objs,
                        "duration_seconds": int(dur) if dur is not None else None,
                        "volo_confidence": 0.72 if objs else 0.5,
                    }
                )

        elif ft == "audio":
            sfx = _evidence_suffix(filename, ".m4a")
            am = volo_scorer.analyze_audio_bytes(file_bytes, suffix=sfx)
            analysis["advanced_analysis"]["audio"] = am
            if am.get("error"):
                analysis.update(
                    {
                        "tamper_score": 40.0,
                        "quality_label": "fair",
                        "analysis_method": "audio_error",
                        "analysis_error": am.get("error"),
                        "volo_confidence": 0.35,
                    }
                )
            else:
                transcript = (am.get("transcript") or "").strip()
                dur = am.get("duration_seconds")
                tamper_guess = 12.0 if transcript else 22.0
                if dur and dur > 60:
                    tamper_guess += 5
                ql = "high" if transcript and len(transcript) > 40 else ("medium" if transcript else "fair")
                analysis.update(
                    {
                        "tamper_score": round(tamper_guess, 3),
                        "quality_label": ql,
                        "analysis_method": "audio_ffprobe_whisper_optional",
                        "transcript": transcript or None,
                        "duration_seconds": int(dur) if dur is not None else None,
                        "volo_confidence": 0.8 if transcript else 0.55,
                    }
                )

        else:
            analysis.update(
                {
                    "blur_score": None,
                    "tamper_score": 50.0,
                    "quality_label": "low",
                    "analysis_method": "unknown",
                    "volo_confidence": 0.4,
                }
            )

    except Exception as e:
        logger.error("Evidence analysis failed: %s", e)
        analysis.update(
            {
                "blur_score": None,
                "tamper_score": 50.0,
                "quality_label": "poor",
                "analysis_error": str(e),
                "analysis_method": analysis.get("analysis_method", "basic_cv") + "_failed",
                "volo_confidence": 0.3,
            }
        )

    return analysis


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers."""
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _log_blocked_device_action(
    db: Session,
    action_type: str,
    request: Optional[Request],
    device: Optional[Device],
    report_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort audit logging for blocked device actions."""
    try:
        client_ip = request.client.host if request and request.client else None
        user_agent = request.headers.get("user-agent") if request else None
        payload = dict(details or {})
        if device is not None:
            payload["device_id"] = str(device.device_id)
            payload["device_hash"] = getattr(device, "device_hash", None)
        log_action(
            db,
            action_type,
            actor_type="system",
            entity_type="report",
            entity_id=report_id,
            action_details=payload,
            ip_address=client_ip,
            user_agent=user_agent,
            success=False,
        )
        db.commit()
    except Exception:
        db.rollback()


def _enforce_device_submission_guards(
    db: Session,
    device: Device,
    report_data: ReportCreate,
    request: Optional[Request] = None,
) -> None:
    """
    Anti-abuse controls:
    1) Block same device submitting duplicate incident repeatedly in a short window.
    2) Block impossible movement patterns (e.g. 20km in 5 minutes).
    3) Rate limiting - prevent suspicious rapid submissions.
    """
    now_utc = datetime.now(timezone.utc)
    current_lat = float(report_data.latitude)
    current_lon = float(report_data.longitude)

    window_start = now_utc - timedelta(minutes=settings.device_activity_window_minutes)
    recent_reports = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= window_start,
        )
        .order_by(Report.reported_at.desc())
        .limit(25)
        .all()
    )

    duplicate_window = int(settings.duplicate_report_time_window_seconds)
    duplicate_radius_km = float(settings.duplicate_report_radius_meters) / 1000.0

    for prev in recent_reports:
        prev_time = _to_utc(prev.reported_at)
        if prev_time is None:
            continue
        delta_seconds = max(0.0, (now_utc - prev_time).total_seconds())
        if delta_seconds > duplicate_window:
            continue

        if int(prev.incident_type_id) != int(report_data.incident_type_id):
            continue

        prev_lat = float(prev.latitude)
        prev_lon = float(prev.longitude)
        distance_km = _haversine_km(current_lat, current_lon, prev_lat, prev_lon)
        if distance_km <= duplicate_radius_km:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_duplicate",
                request=request,
                device=device,
                details={
                    "incident_type_id": int(report_data.incident_type_id),
                    "distance_km": round(distance_km, 4),
                    "time_delta_seconds": int(delta_seconds),
                    "duplicate_window_seconds": duplicate_window,
                    "duplicate_radius_meters": int(settings.duplicate_report_radius_meters),
                },
            )
            raise HTTPException(
                status_code=409,
                detail="Duplicate incident detected from this device in a short time window. Please wait before submitting the same incident again.",
            )

    impossible_window = int(settings.impossible_travel_window_seconds)
    impossible_distance_km = float(settings.impossible_travel_min_distance_km)
    max_speed_kmh = float(settings.max_plausible_speed_kmh)

    for prev in recent_reports:
        prev_time = _to_utc(prev.reported_at)
        if prev_time is None:
            continue
        delta_seconds = max(0.0, (now_utc - prev_time).total_seconds())
        if delta_seconds <= 0 or delta_seconds > impossible_window:
            continue

        prev_lat = float(prev.latitude)
        prev_lon = float(prev.longitude)
        distance_km = _haversine_km(current_lat, current_lon, prev_lat, prev_lon)
        if distance_km < impossible_distance_km:
            continue

        speed_kmh = distance_km / (delta_seconds / 3600.0)
        if speed_kmh >= max_speed_kmh:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_impossible_travel",
                request=request,
                device=device,
                details={
                    "incident_type_id": int(report_data.incident_type_id),
                    "distance_km": round(distance_km, 3),
                    "time_delta_seconds": int(delta_seconds),
                    "speed_kmh": round(speed_kmh, 2),
                    "threshold_speed_kmh": max_speed_kmh,
                    "impossible_window_seconds": impossible_window,
                },
            )
            raise HTTPException(
                status_code=400,
                detail="Impossible movement pattern detected for this device (large distance in short time). Report blocked for integrity checks.",
            )

    # Professional rate limiting: Balance security with emergency reporting needs
    
    # Check for suspicious rapid submissions (last 10 minutes)
    rate_limit_window = now_utc - timedelta(minutes=10)  # Last 10 minutes
    recent_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= rate_limit_window,
        )
        .count()
    )
    
    # Allow max 8 reports per 10 minutes per device (reasonable for multiple incidents)
    max_submissions_per_10min = 8
    if recent_submissions >= max_submissions_per_10min:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_rate_limit",
            request=request,
            device=device,
            details={
                "recent_submissions": recent_submissions,
                "time_window_minutes": 10,
                "max_allowed": max_submissions_per_10min,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: Maximum {max_submissions_per_10min} reports allowed per 10 minutes. For emergency assistance, please contact authorities directly.",
        )
    
    # Check for very suspicious activity (multiple submissions in 2 minutes)
    very_recent_window = now_utc - timedelta(minutes=2)  # Last 2 minutes
    very_recent_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= very_recent_window,
        )
        .count()
    )
    
    # Allow max 3 reports per 2 minutes per device (prevents spam but allows legitimate multiple reports)
    max_submissions_per_2min = 3
    if very_recent_submissions >= max_submissions_per_2min:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_suspicious_activity",
            request=request,
            device=device,
            details={
                "very_recent_submissions": very_recent_submissions,
                "time_window_minutes": 2,
                "max_allowed": max_submissions_per_2min,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Please wait at least 2 minutes before submitting additional reports. This helps ensure system stability for all users.",
        )
    
    # Check for extreme spam (multiple submissions in 30 seconds)
    extreme_window = now_utc - timedelta(seconds=30)  # Last 30 seconds
    extreme_submissions = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= extreme_window,
        )
        .count()
    )
    
    # Allow max 1 report per 30 seconds per device (prevents automated spam)
    max_submissions_per_30sec = 1
    if extreme_submissions >= max_submissions_per_30sec:
        _log_blocked_attempt(
            db,
            action_type="report_blocked_extreme_spam",
            request=request,
            device=device,
            details={
                "extreme_submissions": extreme_submissions,
                "time_window_seconds": 30,
                "max_allowed": max_submissions_per_30sec,
                "current_incident_type": int(report_data.incident_type_id),
            },
        )
        raise HTTPException(
            status_code=429,
            detail=f"Please wait at least 30 seconds between report submissions. Automated submissions are not allowed.",
        )
    
    # Additional check: Prevent obvious bot behavior (same incident type repeatedly)
    very_recent_reports = (
        db.query(Report)
        .filter(
            Report.device_id == device.device_id,
            Report.reported_at >= very_recent_window,
        )
        .order_by(Report.reported_at.desc())
        .limit(5)
        .all()
    )
    
    if len(very_recent_reports) >= 3:
        # Check if last 3 reports are all the same incident type (potential bot behavior)
        recent_incident_types = [r.incident_type_id for r in very_recent_reports[:3]]
        current_incident_type = int(report_data.incident_type_id)
        
        if len(set(recent_incident_types)) == 1 and recent_incident_types[0] == current_incident_type:
            _log_blocked_attempt(
                db,
                action_type="report_blocked_repetitive_bot_behavior",
                request=request,
                device=device,
                details={
                    "current_incident_type": current_incident_type,
                    "recent_incident_types": recent_incident_types,
                    "identical_count": 3,
                    "time_window_minutes": 2,
                },
            )
            raise HTTPException(
                status_code=429,
                detail=f"Multiple identical reports detected. Please ensure each report represents a unique incident. If this is an error, please wait 2 minutes.",
            )


def _ensure_fallback_ml_prediction_if_missing(db: Session, report: Report) -> None:
    """
    XGBoost scoring may skip inserting a row (no model, bad meta, errors).
    Persist a heuristic evaluation so list/detail APIs always have ml_predictions
    (prediction_label, trust_score, etc.) when possible.

    Called on every new report (`create_report`) and after community re-score so the
    Reports page can read real DB rows — ongoing operation does not require manual backfill.
    """
    from app.models.ml_prediction import MLPrediction

    exists = (
        db.query(MLPrediction.prediction_id)
        .filter(MLPrediction.report_id == report.report_id)
        .limit(1)
        .first()
    )
    if exists is not None:
        return
    try:
        from app.utils.ml_evaluator import ml_evaluator

        ml_result = ml_evaluator.evaluate_report(report)
        db.add(
            MLPrediction(
                prediction_id=uuid4(),
                report_id=report.report_id,
                trust_score=ml_result["trust_score"],
                prediction_label=ml_result["prediction_label"],
                confidence=ml_result["confidence"],
                model_type="auto_evaluation",
                is_final=False,
                evaluated_at=datetime.now(timezone.utc),
            )
        )
        logger.info(
            "Fallback ML row for report %s: %s (%.1f%%)",
            report.report_id,
            ml_result.get("prediction_label"),
            float(ml_result.get("trust_score") or 0),
        )
    except Exception as exc:
        logger.warning(
            "Could not create fallback ml_prediction for report %s: %s",
            report.report_id,
            exc,
            exc_info=True,
        )


#this marks the biggining of changes I did to implement AI-enhanced rules and ML-based auto-verification in the create_report endpoint. The improvements include:
#1) AI-enhanced rules: Implemented a new function apply_ai_enhanced_rules
def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _auto_reject_report_for_invalid_evidence(
    db: Session,
    report: Report,
    reason: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist an automatic rejection and attach AI-readable reason metadata."""
    report.rule_status = "rejected"
    report.status = "rejected"
    report.verification_status = "rejected"
    report.is_flagged = True
    report.flag_reason = reason

    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        fv = {}
    fv["ai_rejected"] = True
    fv["ai_rejection_reason"] = reason
    fv["ai_rejected_at"] = datetime.now(timezone.utc).isoformat()
    if details:
        fv["ai_rejection_details"] = details
    report.feature_vector = _json_safe(fv)

    # Best-effort: re-run scoring so the ML explanation can include the rejected rule status.
    try:
        device = db.query(Device).filter(Device.device_id == report.device_id).first()
        evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).count()
        if device is not None:
            score_report_credibility(db, report, device, evidence_count)
    except Exception:
        pass

    db.commit()
    db.refresh(report)
 
 #this marks the end of improvement I did

def run_hotspot_auto():
    """Background task to fully recompute DBSCAN hotspots from all reports."""
    db = SessionLocal()
    try:
        tw, mi, rm = get_hotspot_params_from_db(db)
        trust_min = get_hotspot_trust_min_from_db(db)

        # Full refresh so every new incident re-analyzes entire DB history.
        from app.models.hotspot import hotspot_reports_table
        db.execute(hotspot_reports_table.delete())
        db.query(Hotspot).delete()
        db.commit()

        created = create_hotspots_from_reports(
            db,
            time_window_hours=tw,
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=False,  # Use time window for real-time updates
        )
        if created > 0:
            print(f"Background hotspot creation: {created} new hotspots created")
            
            # Broadcast hotspot update to all connected clients for real-time Safety Map updates
            try:
                import asyncio
                from app.core.websocket import manager
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "hotspot", "action": "auto_created"}))
                    loop.create_task(manager.broadcast({"type": "refresh_data", "entity": "geographic_intelligence", "action": "updated"}))
                except RuntimeError:
                    asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "hotspot", "action": "auto_created"}))
                    asyncio.run(manager.broadcast({"type": "refresh_data", "entity": "geographic_intelligence", "action": "updated"}))
            except Exception as e:
                print(f"Failed to broadcast hotspot update: {e}")
            
            # Create notifications for admins and supervisors about new hotspots
            from app.api.v1.notifications import create_role_notifications
            
            # Get the most recently created hotspot for notification
            latest_hotspot = db.query(Hotspot).order_by(Hotspot.detected_at.desc()).first() if created > 0 else None
            
            create_role_notifications(
                db,
                title="New Hotspots Detected",
                message=f"{created} new safety hotspots have been automatically detected based on recent reports.",
                notif_type="system",
                related_entity_type="hotspot",
                related_entity_id=str(latest_hotspot.hotspot_id) if created == 1 and latest_hotspot else None,
                target_roles=["admin", "supervisor"],
                send_email=True  # Enable email notifications for hotspots
            )
        db.commit()
    except Exception as e:
        print(f"Error in background hotspot creation: {e}")
        db.rollback()
    finally:
        db.close()


def run_auto_case_realtime():
    """Background task to run case auto-linking/creation after live report changes."""
    db = SessionLocal()
    try:
        case_stats = _create_auto_cases(db)
        if case_stats.get("cases_created", 0) > 0:
            print(
                f"Realtime auto-case run: created {case_stats['cases_created']} case(s)"
            )
            try:
                _balance_workload_and_reassign(db)
            except Exception as balance_error:
                print(f"Warning: workload balancing failed after auto-case run: {balance_error}")
    except Exception as e:
        print(f"Error in realtime auto-case run: {e}")
        db.rollback()
    finally:
        db.close()


def run_auto_case_for_report(report_id: str):
    """Background task wrapper for single-report real-time auto-case processing."""
    try:
        logger.info("[AUTO_CASE] Triggered realtime processing for report %s", report_id)
        _check_and_create_auto_case(report_id)
    except Exception as e:
        logger.error(
            "[AUTO_CASE] Error in realtime processing for report %s: %s",
            report_id,
            e,
        )
def _purge_outside_musanze_reports(db: Session, recompute_hotspots: bool = True) -> tuple[int, int]:
    """Delete reports outside covered village polygons and optionally recompute hotspots.

    Returns:
        (deleted_reports, recomputed_hotspots)
    """
    rows = db.execute(
        text(
            """
            SELECT
                r.report_id,
                v.location_id AS resolved_village_id
            FROM reports r
            LEFT JOIN LATERAL (
                SELECT l.location_id
                FROM locations l
                WHERE l.location_type = 'village'
                  AND l.is_active = true
                  AND l.geometry IS NOT NULL
                  AND ST_Contains(
                      l.geometry,
                      ST_SetSRID(
                          ST_MakePoint(
                              CAST(r.longitude AS DOUBLE PRECISION),
                              CAST(r.latitude AS DOUBLE PRECISION)
                          ),
                          4326
                      )
                  )
                LIMIT 1
            ) v ON TRUE
            """
        )
    ).fetchall()

    in_area_updates = []
    outside_ids = []
    for row in rows:
        report_id = row[0]
        resolved_village_id = row[1]
        if resolved_village_id is None:
            outside_ids.append(report_id)
        else:
            in_area_updates.append(
                {
                    "report_id": report_id,
                    "village_location_id": int(resolved_village_id),
                    "location_id": int(resolved_village_id),
                }
            )

    if in_area_updates:
        db.execute(
            text(
                """
                UPDATE reports
                SET village_location_id = :village_location_id,
                    location_id = :location_id
                WHERE report_id = :report_id
                """
            ),
            in_area_updates,
        )

    deleted_reports = 0
    if outside_ids:
        db.execute(
            text("DELETE FROM ml_predictions WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM evidence_files WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM police_reviews WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM report_assignments WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )
        db.execute(
            text("DELETE FROM case_reports WHERE report_id = ANY(:ids)"),
            {"ids": outside_ids},
        )

        db.execute(
            hotspot_reports_table.delete().where(
                hotspot_reports_table.c.report_id.in_(outside_ids)
            )
        )
        deleted_reports = (
            db.query(Report)
            .filter(Report.report_id.in_(outside_ids))
            .delete(synchronize_session=False)
        )

    recomputed = 0
    if recompute_hotspots:
        db.execute(hotspot_reports_table.delete())
        db.query(Hotspot).delete()
        db.commit()

        tw, mi, rm = get_hotspot_params_from_db(db)
        trust_min = get_hotspot_trust_min_from_db(db)
        recomputed = create_hotspots_from_reports(
            db,
            time_window_hours=tw,
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=True,
        )

    db.commit()
    return deleted_reports, recomputed


def _generate_report_number(db: Session) -> str:
    """Generate next report number RPT-YYYY-NNNN."""
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"RPT-{year}-"
    row = db.execute(
        text("""
            SELECT COALESCE(MAX(
                NULLIF(SUBSTRING(report_number FROM 'RPT-[0-9]{4}-([0-9]+)'), '')::INT
            ), 0) + 1 AS next_num
            FROM reports WHERE report_number LIKE :prefix
        """),
        {"prefix": f"{prefix}%"},
    ).fetchone()
    next_num = row[0] if row else 1
    return f"{prefix}{next_num:04d}"

UPLOAD_DIR = "uploads/evidence"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# Configure Cloudinary using settings (Pydantic loads .env for us)
cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)

_CLOUDINARY_ENABLED = bool(
    settings.cloudinary_cloud_name
    and settings.cloudinary_api_key
    and settings.cloudinary_api_secret
)


def _extract_exif_metadata(image_bytes: bytes) -> tuple[Optional[float], Optional[float], Optional[datetime]]:
    """Extract GPS latitude/longitude and capture time from image EXIF, if present."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        # Try modern getexif() API first, fall back to _getexif()
        exif_data = getattr(image, "getexif", lambda: None)()
        if not exif_data:
            exif_data = getattr(image, "_getexif", lambda: None)()

        if not exif_data:
            return None, None, None

        exif = {TAGS.get(k, k): v for k, v in exif_data.items()}
        # Debug: show that we actually saw EXIF keys
        print(f"[EXIF] Found EXIF keys: {list(exif.keys())[:10]}")

        # Try to get GPS info in a robust way
        gps_info = None

        # 1) Best effort: use get_ifd if available (Pillow Exif object)
        if hasattr(exif_data, "get_ifd"):
            try:
                gps_ifd = exif_data.get_ifd(34853)  # 34853 == GPSInfo tag
                if gps_ifd:
                    gps_info = gps_ifd
            except Exception:
                gps_info = None

        # 2) Fallback: raw tag value 34853 or "GPSInfo"
        if gps_info is None:
            raw_gps = exif_data.get(34853) or exif.get("GPSInfo")
            # Some cameras store an integer offset here; resolve via get_ifd
            if isinstance(raw_gps, dict):
                gps_info = raw_gps
            elif isinstance(raw_gps, int) and hasattr(exif_data, "get_ifd"):
                try:
                    gps_info = exif_data.get_ifd(raw_gps)
                except Exception:
                    gps_info = None

        dt_original = exif.get("DateTimeOriginal") or exif.get("DateTime")

        lat = lon = None
        print(f"[EXIF] raw GPSInfo: {gps_info!r}")
        if gps_info:
            gps_parsed = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            print(f"[EXIF] GPSInfo keys: {list(gps_parsed.keys())}")

            def _to_deg(value, ref):
                """
                Convert EXIF GPS coordinates to decimal degrees.

                Handles both:
                - Rational tuples: ((deg_num, deg_den), (min_num, min_den), (sec_num, sec_den))
                - Simple float triplets: (deg_float, min_float, sec_float)
                """
                try:
                    # Case 1: rational tuples
                    if isinstance(value[0], (tuple, list)):
                        d = value[0][0] / value[0][1]
                        m = value[1][0] / value[1][1]
                        s = value[2][0] / value[2][1]
                    else:
                        # Case 2: already simple floats (deg, min, sec)
                        d, m, s = value

                    result = d + (m / 60.0) + (s / 3600.0)
                    if ref in ["S", "W"]:
                        result = -result
                    return float(result)
                except Exception:
                    return None

            lat_val = gps_parsed.get("GPSLatitude")
            lat_ref = gps_parsed.get("GPSLatitudeRef")
            lon_val = gps_parsed.get("GPSLongitude")
            lon_ref = gps_parsed.get("GPSLongitudeRef")

            if lat_val and lat_ref:
                lat = _to_deg(lat_val, lat_ref)
            if lon_val and lon_ref:
                lon = _to_deg(lon_val, lon_ref)

        dt = None
        if dt_original:
            # EXIF datetime format: "YYYY:MM:DD HH:MM:SS"
            try:
                dt = datetime.strptime(dt_original, "%Y:%m:%d %H:%M:%S")
            except Exception:
                dt = None

        return lat, lon, dt
    except Exception:
        # If EXIF parsing fails, just return Nones
        return None, None, None


@router.post("/", response_model=ReportResponse)
def create_report(
    report_data: ReportCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new report."""
    """Submit a new incident report. Device can be identified by device_id or device_hash (find-or-create)."""
    device = None
    if report_data.device_id:
        device = db.query(Device).filter(Device.device_id == report_data.device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
    if device is None and report_data.device_hash and str(report_data.device_hash).strip():
        device = (
            db.query(Device)
            .filter(Device.device_hash == report_data.device_hash.strip())
            .first()
        )
        if not device:
            # Check if this device_hash was previously banned (to prevent ban evasion)
            banned_device_with_same_hash = (
                db.query(Device)
                .filter(Device.device_hash == report_data.device_hash.strip(), Device.is_banned == True)
                .first()
            )
            if banned_device_with_same_hash:
                raise HTTPException(
                    status_code=403, 
                    detail="This device hash is banned from submitting reports"
                )
            device = Device(
                device_id=uuid4(),
                device_hash=report_data.device_hash.strip(),
            )
            db.add(device)
            db.flush()
    if not device:
        raise HTTPException(status_code=400, detail="Either device_id or device_hash is required")
    # Block reporting from banned devices (admin action)
    if getattr(device, "is_banned", False):
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Banned device {device.device_id} (hash: {device.device_hash}) attempted to submit report")
        raise HTTPException(status_code=403, detail="This device is banned from submitting reports")

    _enforce_device_submission_guards(db, device, report_data, request)

    # Mobile rule gate (strict): only "passed" reports are allowed to be created.
    # Any other status must be blocked before persistence.
    mobile_rule_status = (getattr(report_data, "mobile_rule_status", None) or "").strip().lower()
    if mobile_rule_status != "passed":
        raise HTTPException(
            status_code=400,
            detail=(
                "Report blocked by mobile verification rules. "
                "Only reports with mobile_rule_status='passed' can be submitted."
            ),
        )

    # Additional safety checks for explicit mobile boolean signals.
    if getattr(report_data, "evidence_source_valid", True) is False:
        raise HTTPException(
            status_code=400,
            detail="Report blocked: evidence source validation failed on mobile.",
        )
    if getattr(report_data, "evidence_tampering_detected", False) is True:
        raise HTTPException(
            status_code=400,
            detail="Report blocked: evidence tampering/screenshot detected on mobile.",
        )
    if getattr(report_data, "location_consistency_check", True) is False:
        raise HTTPException(
            status_code=400,
            detail="Report blocked: location consistency validation failed on mobile.",
        )

    # Verify incident type exists and is active
    incident_type = (
        db.query(IncidentType)
        .filter(
            IncidentType.incident_type_id == report_data.incident_type_id,
            IncidentType.is_active == True,
        )
        .first()
    )
    if not incident_type:
        raise HTTPException(status_code=400, detail="Invalid or inactive incident type")

    # Boundary validation: reports outside Musanze are persisted but explicitly
    # marked as rejected so they never contribute to clustering.
    village_id = None
    village_info = None
    out_of_boundary = False
    out_of_boundary_reason: Optional[str] = None
    try:
        lat_f = float(report_data.latitude)
        lon_f = float(report_data.longitude)

        village_id = get_village_location_id(db, lat_f, lon_f)
        village_info = get_village_location_info(db, lat_f, lon_f)

        # --- TEST ONLY: Musanze boundary rejection disabled (uncomment for production). ---
        # if not village_id or not village_info:
        #     out_of_boundary = True
        #     out_of_boundary_reason = (
        #         f"out_of_musanze_boundary: ({lat_f:.4f}, {lon_f:.4f})"
        #     )

        district_name = ""
        if village_info:
            district_name = (village_info.get("district_name") or "").strip().lower()
        # --- TEST ONLY: non-Musanze district rejection disabled (uncomment for production). ---
        # if district_name and district_name != "musanze":
        #     out_of_boundary = True
        #     out_of_boundary_reason = f"out_of_musanze_boundary: district={district_name}"
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid coordinates: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Location validation failed: {e}")
    
    incoming_report_id = report_data.report_id or uuid4()
    if report_data.report_id:
        existing_report = (
            db.query(Report)
            .filter(Report.report_id == report_data.report_id)
            .first()
        )
        if existing_report:
            raise HTTPException(status_code=409, detail="Report already exists")

    report_num = _generate_report_number(db) if hasattr(Report, "report_number") else None
    report = Report(
        report_id=incoming_report_id,
        report_number=report_num,
        device_id=device.device_id,
        incident_type_id=report_data.incident_type_id,
        description=report_data.description,
        latitude=report_data.latitude,
        longitude=report_data.longitude,
        gps_accuracy=report_data.gps_accuracy,
        motion_level=report_data.motion_level,
        movement_speed=report_data.movement_speed,
        was_stationary=report_data.was_stationary,
        rule_status="pending",  # Will be processed by verification engine
        status="pending",
        verification_status="pending",
        context_tags=report_data.context_tags or [],
        app_version=report_data.app_version,
        network_type=report_data.network_type,
        battery_level=report_data.battery_level,
    )

    # Wire location hierarchy: use the village row as both specific village_location_id
    # and generic location_id so downstream queries can work with a single FK.
    if not out_of_boundary and village_id is not None:
        report.village_location_id = village_id
        report.location_id = village_id
    db.add(report)
    try:
        db.flush()  # Get report_id
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Report already exists")

    # Evidence processing with content analysis
    evidence_metadata_list = []
    evidence_validations = []
    
    for evidence_data in report_data.evidence_files:
        normalized_url = _normalize_evidence_file_url(getattr(evidence_data, "file_url", None))
        if not normalized_url:
            continue
        
        evidence_metadata_list.append({
            "media_latitude": evidence_data.media_latitude,
            "media_longitude": evidence_data.media_longitude,
            "captured_at": evidence_data.captured_at,
            "file_url": normalized_url,
            "file_type": evidence_data.file_type,
        })
        
        # Analyze evidence content for media files (photo/video/audio)
        blur_score = None
        tamper_score = None
        quality_label = None
        validation_result = None
        ai_checked_at = datetime.now(timezone.utc)
        
        file_type_lower = (evidence_data.file_type or "").lower().strip()

        if file_type_lower in ['photo', 'image/jpeg', 'image/png', 'image/jpg']:
            try:
                # Evidence analysis removed - using unified validation only
                validation_result = {
                    "valid": True,
                    "confidence": 0.7,
                    "threshold_used": 0.6,
                    "issues": []
                }
                
                # Default quality metrics
                blur_score = 0.0
                tamper_score = 0.0
                quality_label = "fair"
                
                # Log validation results
                logger.info(f"Evidence validation for report {report.report_id}: "
                           f"valid={validation_result['valid']}, "
                           f"confidence={validation_result['confidence']:.2f}, "
                           f"issues={validation_result['issues']}")
                
                # Store validation for later processing
                evidence_validations.append({
                    'evidence_url': normalized_url,
                    'validation': validation_result
                })
                
            except Exception as e:
                logger.error(f"Error analyzing evidence {normalized_url}: {e}")
                # Set default values if analysis fails
                quality_label = "poor"
                blur_score = 0.0
                tamper_score = 1.0

        elif file_type_lower in ["video", "video/mp4", "video/mov", "video/quicktime", "video/webm"]:
            try:
                # Video evidence analysis removed - using unified validation only
                validation_result = {
                    "valid": True,
                    "confidence": 0.6,
                    "threshold_used": 0.6,
                    "issues": []
                }
                blur_score = 0.0
                tamper_score = 0.0
                quality_label = "fair"
                evidence_validations.append({'evidence_url': normalized_url, 'validation': validation_result})
            except Exception as e:
                logger.error(f"Error analyzing video evidence {normalized_url}: {e}")
                quality_label = "poor"

        elif file_type_lower in ["audio", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/aac", "audio/ogg"]:
            try:
                # Audio evidence analysis removed - using unified validation only
                validation_result = {
                    "valid": True,
                    "confidence": 0.5,
                    "threshold_used": 0.6,
                    "issues": []
                }
                # For audio, keep fields conservative
                blur_score = None
                tamper_score = 0.5
                quality_label = "fair"
                evidence_validations.append({'evidence_url': normalized_url, 'validation': validation_result})
            except Exception as e:
                logger.error(f"Error analyzing audio evidence {normalized_url}: {e}")
                quality_label = "poor"
        
        evidence = EvidenceFile(
            evidence_id=uuid4(),
            report_id=report.report_id,
            file_url=normalized_url,
            file_type=evidence_data.file_type,
            media_latitude=evidence_data.media_latitude,
            media_longitude=evidence_data.media_longitude,
            captured_at=evidence_data.captured_at,
            is_live_capture=evidence_data.is_live_capture,
            blur_score=blur_score,
            tamper_score=tamper_score,
            quality_label=quality_label,
            ai_checked_at=ai_checked_at.replace(tzinfo=None) if ai_checked_at is not None else None,
        )
        db.add(evidence)

    # --- TEST ONLY: reject persist step disabled — restore `elif not evidence_metadata_list` when re-enabling boundary checks.
    # if out_of_boundary:
    #     report.rule_status = "rejected"
    #     report.status = "rejected"
    #     report.verification_status = "rejected"
    #     report.is_flagged = True
    #     report.flag_reason = out_of_boundary_reason or "out_of_musanze_boundary"
    #
    #     fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
    #     fv["boundary_status"] = "out_of_musanze"
    #     fv["excluded_from_clustering"] = True
    #     fv["boundary_reason"] = report.flag_reason
    #     report.feature_vector = _json_safe(fv)

    # Text-only analysis for reports without evidence
    if not evidence_metadata_list:
        # This report has no evidence files - perform text-only analysis + type-vs-description checks
        try:
            incident_type_row = (
                db.query(IncidentType)
                .filter(IncidentType.incident_type_id == report.incident_type_id)
                .first()
            )
            incident_type_name = incident_type_row.type_name if incident_type_row else "unknown"

            quality_metrics = submission_guidance.evaluate_description_quality(
                report_data.description or report.description or "",
                incident_type_name,
            )
            reason_codes = quality_metrics.get("reason_codes", []) if isinstance(quality_metrics.get("reason_codes"), list) else []
            hard_gates = quality_metrics.get("hard_gates", []) if isinstance(quality_metrics.get("hard_gates"), list) else []
            q_score = float(quality_metrics.get("quality_score", 0.0))
            band = str(quality_metrics.get("quality_band", "reject_quality"))
            text_valid = q_score >= 50.0 and not hard_gates
            confidence = max(0.0, min(1.0, q_score / 100.0))
            text_analysis = {
                "valid": bool(text_valid),
                "confidence": round(confidence, 3),
                "threshold_used": 0.50,
                "quality_score": round(q_score, 2),
                "quality_band": band,
                "reason_codes": reason_codes,
                "hard_gates": hard_gates,
                "breakdown": quality_metrics.get("score_breakdown", {}),
                "issues": reason_codes,
            }
            fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
            fv["text_only_validation"] = text_analysis
            report.feature_vector = _json_safe(fv)

            # Strict text-only policy:
            # - anything below pass_quality is auto-rejected
            if hard_gates or band in {"reject_quality", "review_quality"}:
                if report.rule_status != "rejected":
                    report.rule_status = "rejected"
                    report.status = "rejected"
                    report.verification_status = "rejected"
                    report.is_flagged = True
                    report.flag_reason = reason_codes[0] if reason_codes else "text_only_validation_failed"

        except Exception as e:
            logger.error(f"Text-only analysis failed for report {report.report_id}: {e}")

    # Persist evidence validation summary on the report for auditability
    try:
        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        if evidence_validations:
            fv["evidence_validations"] = evidence_validations
        report.feature_vector = _json_safe(fv)
    except Exception:
        pass

    # Persist AI-generated evidence description for auditing and UI explainability.
    report.ai_evidence_description = _compose_ai_evidence_description(
        evidence_validations,
        incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
        reporter_description=report_data.description or report.description,
        context_tags=list(getattr(report, "context_tags", None) or []),
    )

    # Semantic consistency check (report text vs evidence meaning vs incident type)
    try:
        if evidence_validations:
            incident_type_row = (
                db.query(IncidentType)
                .filter(IncidentType.incident_type_id == report.incident_type_id)
                .first()
            )
            semantic_result = _semantic_alignment_check(
                report_description=report_data.description or "",
                incident_type_name=getattr(incident_type_row, "type_name", "") or "",
                incident_type_description=getattr(incident_type_row, "description", "") or "",
                evidence_semantic_text=_build_evidence_semantic_text(evidence_validations),
            )
            if semantic_result:
                fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
                fv["semantic_alignment"] = semantic_result
                report.feature_vector = _json_safe(fv)

                if semantic_result.get("mismatch") and not out_of_boundary and report.rule_status != "rejected":
                    report.rule_status = "flagged"
                    report.is_flagged = True
                    report.verification_status = "under_review"
                    if not report.flag_reason:
                        report.flag_reason = "description_evidence_mismatch"
    except Exception as e:
        logger.warning(f"Semantic consistency check failed for report {report.report_id}: {e}")

    # If any evidence validation clearly fails, flag the report (do not hard-reject by default)
    try:
        failed = []
        for ev in evidence_validations:
            v = (ev or {}).get("validation") or {}
            if v.get("valid") is False:
                failed.append(v)
        if failed and not out_of_boundary and report.rule_status != "rejected":
            report.rule_status = "flagged"
            report.is_flagged = True
            report.flag_reason = "evidence_incident_mismatch"
            report.verification_status = "under_review"
    except Exception:
        pass

    # === Apply rule-based + ML pipeline (sync, lightweight) ===
    evidence_count = len(evidence_metadata_list)
    try:
        from app.core.unified_validator import validate_report_unified
        from app.core.report_priority import apply_anti_fraud_rules, calculate_report_priority

        unified_validation_data = None
        try:
            validation_result = validate_report_unified(
                db=db,
                report=report,
                device=device,
                evidence_files=list(getattr(report, "evidence_files", []) or []),
            )
            unified_validation_data = _store_unified_validation_result(db, report, validation_result)
        except Exception as e:
            logger.error(f"Unified validation failed during report creation for {report.report_id}: {e}")
            try:
                score_report_credibility(db, report, device, evidence_count)
            except Exception as scoring_error:
                logger.error(f"ML scoring failed during report creation for {report.report_id}: {scoring_error}")

        ml_prediction_tmp = resolve_ml_prediction_for_report(report)
        rule_status, is_flagged, flag_reason = apply_anti_fraud_rules(
            report, evidence_count, db
        )

        # HARD REJECTION: If rule-based validation fails, reject report immediately (like boundary rejection)
        if rule_status == "rejected":
            # Rollback any database changes and return HTTP 400
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "RULE_BASED_REJECTION",
                    "message": "Report rejected by rule-based validation",
                    "flag_reason": flag_reason or "anti_fraud_rules_violation",
                    "rule_status": rule_status
                }
            )

        # Preserve existing flags unless the rule engine flags
        if report.rule_status != "rejected":
            report.rule_status = rule_status
        
        # Handle flagging from rule engine (not rejection)
        report.is_flagged = bool(report.is_flagged or is_flagged)
        if report.is_flagged:
            report.verification_status = "under_review"
        if report.flag_reason is None and flag_reason:
            report.flag_reason = flag_reason

        # Get unified validation result for priority calculation
        unified_validation_data = (
            unified_validation_data
            if isinstance(unified_validation_data, dict)
            else report.feature_vector.get('unified_validation', {}) if isinstance(report.feature_vector, dict) else {}
        )
        report.priority = calculate_report_priority(report, evidence_count, db, unified_validation_data)
        votes_tmp = {"real": 0, "false": 0, "unknown": 0}
        if isinstance(report.feature_vector, dict):
            vv = report.feature_vector.get("community_votes", {})
            if isinstance(vv, dict):
                for v in vv.values():
                    k = str(v)
                    if k in votes_tmp:
                        votes_tmp[k] += 1
        scorecard = _compute_threshold_scorecard(
            report,
            ml_prediction=ml_prediction_tmp,
            community_votes=votes_tmp,
            unified_validation=unified_validation_data,
        )
        fv_sc = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        fv_sc["threshold_scorecard"] = scorecard
        report.feature_vector = _json_safe(fv_sc)
        _apply_threshold_outcome(report, scorecard)
        semantic_alignment_meta = None
        if isinstance(report.feature_vector, dict):
            semantic_alignment_meta = report.feature_vector.get("semantic_alignment")
        ai_trust_score = (
            float(ml_prediction_tmp.trust_score)
            if getattr(ml_prediction_tmp, "trust_score", None) is not None
            else None
        )
        ai_label = getattr(ml_prediction_tmp, "prediction_label", None)
        ai_trust_score, ai_label = _rule_adjusted_trust_label(report, ai_trust_score, ai_label)
        _persist_adjusted_ml_prediction(db, ml_prediction_tmp, ai_trust_score, ai_label)
        try:
            update_device_ml_aggregates(db, device, window=30)
        except Exception:
            pass
        report.ai_verification_reason = _compose_ai_verification_reason(
            verification_status=report.verification_status,
            rule_status=report.rule_status,
            is_flagged=report.is_flagged,
            flag_reason=report.flag_reason,
            ml_prediction_label=ai_label,
            trust_score=ai_trust_score,
            semantic_alignment=semantic_alignment_meta if isinstance(semantic_alignment_meta, dict) else None,
            incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
            reporter_description=report.description,
            context_tags=list(getattr(report, "context_tags", None) or []),
            unified_validation=unified_validation_data,
            scorecard=scorecard,
        )
        report.ai_evidence_description = _compose_ai_evidence_description(
            evidence_validations,
            incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
            reporter_description=report.description,
            context_tags=list(getattr(report, "context_tags", None) or []),
            evidence_file_count=len(evidence_validations),
            unified_validation=unified_validation_data,
            scorecard=scorecard,
        )
        snapshot = _build_ai_analysis_snapshot(
            verification_status=report.verification_status,
            rule_status=report.rule_status,
            is_flagged=report.is_flagged,
            flag_reason=report.flag_reason,
            ml_prediction_label=ai_label,
            trust_score=ai_trust_score,
            semantic_alignment=semantic_alignment_meta if isinstance(semantic_alignment_meta, dict) else None,
            incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
            reporter_description=report.description,
            context_tags=list(getattr(report, "context_tags", None) or []),
            unified_validation=unified_validation_data,
            scorecard=scorecard,
            evidence_validations=evidence_validations,
            evidence_file_count=len(evidence_validations),
        )
        _persist_ai_analysis_snapshot(report, snapshot)
    except Exception as e:
        logger.warning(f"AI-enhanced rules pipeline failed for report {report.report_id}: {e}")

    # Persist everything before responding
    try:
        db.commit()
        db.refresh(report)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save report: {e}")

    return _build_report_detail_response(report, db)


@router.get("/", response_model=ReportListResponse)
def list_reports(
    device_id: Optional[UUID] = Query(None, description="Device ID (mobile owner). If omitted, auth required."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    report_status: Optional[str] = Query(None, description="Filter by report status"),
    rule_status: Optional[str] = Query(None, description="Filter by rule status"),
    boundary_status: Optional[str] = Query(None, description="Filter by boundary status"),
    incident_type_id: Optional[UUID] = Query(None, description="Filter by incident type"),
    village_location_id: Optional[UUID] = Query(None, description="Filter by village location"),
    sector_location_id: Optional[UUID] = Query(None, description="Filter by sector location"),
    from_date: Optional[datetime] = Query(None, description="Filter reports from this date"),
    to_date: Optional[datetime] = Query(None, description="Filter reports to this date"),
):
    """List reports.

    - With device_id: list for that device (mobile).
    - Without device_id: auth required.
      * Officers: only reports assigned to them.
      * Supervisors: reports in their assigned location (if set).
      * Admins: all reports.
    """
    if device_id is not None:
        mobile_query = (
            db.query(Report)
            .options(
                joinedload(Report.device),
                joinedload(Report.incident_type),
                joinedload(Report.village_location)
                .joinedload(Location.parent),  # Load parent location (cell -> sector hierarchy)
                selectinload(Report.evidence_files),
                selectinload(Report.assignments)
                .joinedload(ReportAssignment.police_user)
                .joinedload(PoliceUser.station),  # Load station through police user assignments
                selectinload(Report.ml_predictions),
                selectinload(Report.case_reports),
            )
            .filter(Report.device_id == device_id)
        )
        if boundary_status == "out_of_boundary":
            mobile_query = mobile_query.filter(Report.flag_reason.like("out_of_musanze_boundary%"))
        elif boundary_status == "in_boundary":
            mobile_query = mobile_query.filter(
                or_(Report.flag_reason.is_(None), ~Report.flag_reason.like("out_of_musanze_boundary%"))
            )

        total = mobile_query.count()
        reports = (
            mobile_query.order_by(Report.reported_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return ReportListResponse(
            items=[_build_report_response(r, db, request_device_id=device_id) for r in reports],
            total=total,
            limit=limit,
            offset=offset,
        )
    
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    query = db.query(Report).options(
        joinedload(Report.device),
        joinedload(Report.incident_type),
        joinedload(Report.village_location)
        .joinedload(Location.parent),  # Load parent location (cell -> sector hierarchy)
        selectinload(Report.evidence_files),
        selectinload(Report.assignments)
        .joinedload(ReportAssignment.police_user)
        .joinedload(PoliceUser.station),  # Load station through police user assignments
        selectinload(Report.ml_predictions),
        selectinload(Report.case_reports),
    )
    
    role = getattr(current_user, "role", None)
    
    # Officers see only reports assigned to them
    if role == "officer":
        query = query.join(Report.assignments).filter(
            ReportAssignment.police_user_id == current_user.police_user_id
        ).distinct()
    
    # Supervisors are restricted to their own station's sector.
    elif role == "supervisor":
        supervisor_station_id = getattr(current_user, "station_id", None)
        if supervisor_station_id is None:
            raise HTTPException(
                status_code=403,
                detail="Supervisor station is not configured",
            )
        
        # Get station to find its sector location(s)
        station = db.query(Station).filter(Station.station_id == supervisor_station_id).first()
        if station:
            # Handle both primary and secondary sectors
            sector_location_ids = []
            
            # Primary sector
            if station.location_id:
                sector_location_id = station.location_id
                # Find all villages/cells in this sector
                sector_locations_query = db.query(Location.location_id).filter(
                    or_(
                        Location.location_id == sector_location_id,  # The sector itself
                        Location.parent_location_id == sector_location_id,  # Direct children (cells)
                        # Also get villages under cells in this sector
                        Location.location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id.in_(
                                    db.query(Location.location_id).filter(
                                        Location.parent_location_id == sector_location_id
                                    )
                                )
                            )
                        )
                    )
                )
                sector_location_ids.extend([loc[0] for loc in sector_locations_query.all()])
            
            # Secondary sector (if exists)
            if station.sector2_id:
                sector2_location_id = station.sector2_id
                # Find all villages/cells in secondary sector
                sector2_locations_query = db.query(Location.location_id).filter(
                    or_(
                        Location.location_id == sector2_location_id,  # The sector itself
                        Location.parent_location_id == sector2_location_id,  # Direct children (cells)
                        # Also get villages under cells in this sector
                        Location.location_id.in_(
                            db.query(Location.location_id).filter(
                                Location.parent_location_id.in_(
                                    db.query(Location.location_id).filter(
                                        Location.parent_location_id == sector2_location_id
                                    )
                                )
                            )
                        )
                    )
                )
                sector_location_ids.extend([loc[0] for loc in sector2_locations_query.all()])
            
            # Remove duplicates
            sector_location_ids = list(set(sector_location_ids))
            
            # Filter reports by location hierarchy (village_location_id in sector) + station assignments
            query = query.filter(
                or_(
                    Report.handling_station_id == supervisor_station_id,
                    Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                    ),
                    Report.village_location_id.in_(sector_location_ids)
                )
            )
        else:
            # Fallback: only station-based filtering
            query = query.filter(
                or_(
                    Report.handling_station_id == supervisor_station_id,
                    Report.assignments.any(
                        ReportAssignment.police_user.has(PoliceUser.station_id == supervisor_station_id)
                    ),
                )
            )
    
    if rule_status:
        query = query.filter(Report.rule_status == rule_status)
    
    if report_status:
        if report_status == "flagged":
            query = query.filter(Report.status.in_(["flagged", "rejected"]))
        else:
            query = query.filter(Report.status == report_status)
    
    if boundary_status == "out_of_boundary":
        query = query.filter(Report.flag_reason.like("out_of_musanze_boundary%"))
    elif boundary_status == "in_boundary":
        query = query.filter(
            or_(Report.flag_reason.is_(None), ~Report.flag_reason.like("out_of_musanze_boundary%"))
        )
    
    if incident_type_id is not None:
        query = query.filter(Report.incident_type_id == incident_type_id)
    
    if village_location_id is not None:
        query = query.filter(Report.village_location_id == village_location_id)
    
    if sector_location_id is not None:
        # Villages can be direct children of sector or nested under cells in that sector.
        cell_ids = [
            row[0]
            for row in db.query(Location.location_id)
            .filter(
                Location.location_type == "cell",
                Location.parent_location_id == sector_location_id,
            )
            .all()
        ]
        village_q = db.query(Location.location_id).filter(
            Location.location_type == "village"
        )
        if cell_ids:
            village_q = village_q.filter(
                or_(
                    Location.parent_location_id == sector_location_id,
                    Location.parent_location_id.in_(cell_ids),
                )
            )
        else:
            village_q = village_q.filter(
                Location.parent_location_id == sector_location_id
            )
        sector_village_ids = [row[0] for row in village_q.all()]
        if not sector_village_ids:
            return ReportListResponse(items=[], total=0, limit=limit, offset=offset)
        query = query.filter(Report.village_location_id.in_(sector_village_ids))
    
    if from_date is not None:
        query = query.filter(Report.reported_at >= from_date)
    
    if to_date is not None:
        query = query.filter(Report.reported_at <= to_date)
    
    total = query.count()
    reports = (
        query.order_by(Report.reported_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    return ReportListResponse(
        items=[_build_report_response(r, db, request_device_id=device_id) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{report_id}/reviews", response_model=ReviewResponse, status_code=201)
def add_review(
    report_id: UUID,
    body: ReviewCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """
    Add a police review (decision + note).

    - Admin / Supervisor: any report they can see.
    - Officer: only for reports assigned to them.
    """
    if body.decision not in ("confirmed", "rejected", "investigation"):
        raise HTTPException(status_code=400, detail="decision must be confirmed, rejected, or investigation")

    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    role = getattr(current_user, "role", None)
    if role == "officer":
        assigned = (
            db.query(ReportAssignment)
            .filter(
                ReportAssignment.report_id == report_id,
                ReportAssignment.police_user_id == current_user.police_user_id,
            )
            .first()
        )
        if not assigned:
            raise HTTPException(
                status_code=403,
                detail="You can only review reports assigned to you",
            )

    # Ensure ML analysis stage exists before police review decisions.
    from app.models.ml_prediction import MLPrediction

    latest_pred = (
        db.query(MLPrediction)
        .filter(MLPrediction.report_id == report_id)
        .order_by(MLPrediction.evaluated_at.desc())
        .first()
    )
    if latest_pred is None:
        try:
            device = db.query(Device).filter(Device.device_id == report.device_id).first()
            evidence_count = (
                db.query(EvidenceFile)
                .filter(EvidenceFile.report_id == report.report_id)
                .count()
            )
            if device is not None:
                score_report_credibility(db, report, device, evidence_count)
        except Exception:
            pass

    # Update report verification and status when police confirms or rejects
    now_utc = datetime.now(timezone.utc)

    # Update ML prediction based on police review (human oversight)
    decision = (body.decision or "").strip().lower()

    if decision == "confirmed":
        # Police confirmed report - update ML to learn from this
        report.verified_at = now_utc
        report.verified_by = current_user.police_user_id  # Add who verified it
        report.rule_status = "passed"
        report.status = "verified"
        report.verification_status = "verified"
        report.is_flagged = False
        report.flag_reason = None
        
        # Get ML max trust score from config
        from app.database import SessionLocal
        from app.models.system_config import SystemConfig
        
        db_config = SessionLocal()
        try:
            max_trust_config = db_config.query(SystemConfig).filter(
                SystemConfig.config_key == 'ml.max_trust_score'
            ).first()
            max_trust_score = float(max_trust_config.config_value.get('value', 95.0)) if max_trust_config else 95.0
        finally:
            db_config.close()
        
        # Update ML prediction to reflect human confirmation
        existing_ml = db.query(MLPrediction).filter(
            MLPrediction.report_id == report_id
        ).order_by(MLPrediction.evaluated_at.desc()).first()
        
        if existing_ml:
            # Human confirmation increases trust score and sets label to likely_real
            existing_ml.trust_score = Decimal(str(max_trust_score))
            existing_ml.prediction_label = "likely_real"
            existing_ml.confidence = Decimal("0.95")
            existing_ml.is_final = True
            print(f"Updated ML prediction based on police confirmation: trust_score={max_trust_score}%, label=likely_real")  # Debug log
        else:
            # Create new ML prediction if none exists
            new_ml = MLPrediction(
                prediction_id=uuid4(),
                report_id=report_id,
                trust_score=Decimal(str(max_trust_score)),
                prediction_label="likely_real",
                confidence=Decimal("0.95"),
                model_type="human_override",
                is_final=True,
                evaluated_at=now_utc
            )
            db.add(new_ml)
            print(f"Created new ML prediction based on police confirmation: trust_score={max_trust_score}%, label=likely_real")  # Debug log
        
        # Update device trust score based on successful human confirmation.
        # Keep step small to avoid over-inflating trust from a single review.
        if hasattr(report, "device") and report.device and hasattr(report.device, "device_trust_score"):
            current_device_score = float(report.device.device_trust_score) if report.device.device_trust_score else 50.0
            # Increase by a small bounded step.
            new_device_score = min(100.0, current_device_score + 2.0)
            report.device.device_trust_score = Decimal(str(new_device_score))
            print(f"Updated device trust score: {current_device_score:.1f}% → {new_device_score:.1f}%")  # Debug log
        
        # Update trusted_reports count
        if hasattr(report.device, "trusted_reports"):
            report.device.trusted_reports = (report.device.trusted_reports or 0) + 1
        
    elif decision == "rejected":
        # Police rejected report - update ML to learn from this
        report.verified_at = now_utc
        report.verified_by = current_user.police_user_id  # Add who verified it
        report.rule_status = "rejected"
        report.status = "rejected"
        report.verification_status = "rejected"
        report.is_flagged = True
        report.flag_reason = body.review_note or "rejected_by_reviewer"
        
        # Get ML min trust score from config
        from app.database import SessionLocal
        from app.models.system_config import SystemConfig
        
        db_config = SessionLocal()
        try:
            min_trust_config = db_config.query(SystemConfig).filter(
                SystemConfig.config_key == 'ml.min_trust_score'
            ).first()
            min_trust_score = float(min_trust_config.config_value.get('value', 5.0)) if min_trust_config else 5.0
        finally:
            db_config.close()
        
        # Update ML prediction to reflect human rejection
        existing_ml = db.query(MLPrediction).filter(
            MLPrediction.report_id == report_id
        ).order_by(MLPrediction.evaluated_at.desc()).first()
        
        if existing_ml:
            # Human rejection decreases trust score and sets label to fake
            existing_ml.trust_score = Decimal(str(min_trust_score))
            existing_ml.prediction_label = "fake"
            existing_ml.confidence = Decimal("0.95")  # High confidence in this assessment
            existing_ml.is_final = True
            print(f"Updated ML prediction based on police rejection: trust_score={min_trust_score}%, label=fake")  # Debug log
        else:
            # Create new ML prediction if none exists
            new_ml = MLPrediction(
                prediction_id=uuid4(),
                report_id=report_id,
                trust_score=Decimal(str(min_trust_score)),
                prediction_label="fake",
                confidence=Decimal("0.95"),
                model_type="human_override",
                is_final=True,
                evaluated_at=now_utc
            )
            db.add(new_ml)
            print(f"Created new ML prediction based on police rejection: trust_score={min_trust_score}%, label=fake")  # Debug log
        
        # Update device trust score based on human rejection.
        # Keep reduction small to avoid dangerous one-shot collapses.
        if hasattr(report, "device") and report.device and hasattr(report.device, "device_trust_score"):
            current_device_score = float(report.device.device_trust_score) if report.device.device_trust_score else 50.0
            # Decrease by a small bounded step.
            new_device_score = max(0.0, current_device_score - 3.0)
            report.device.device_trust_score = Decimal(str(new_device_score))
            print(f"Updated device trust score: {current_device_score:.1f}% → {new_device_score:.1f}%")  # Debug log
        
        # Update flagged_reports count
        if hasattr(report.device, "flagged_reports"):
            report.device.flagged_reports = (report.device.flagged_reports or 0) + 1
        
    else:
        # Human review for flagged reports - police can make final decisions
        report.verification_status = "verified"
        report.status = "verified"
        report.is_flagged = False
        report.flag_reason = None
        if body.review_note:
            print(f" POLICE VERIFIED: Report {report_id} manually verified - {body.review_note}")
        else:
            print(f" POLICE VERIFIED: Report {report_id} manually verified")

    ml_prediction_tmp = resolve_ml_prediction_for_report(report)
    semantic_alignment_meta = None
    if isinstance(report.feature_vector, dict):
        semantic_alignment_meta = report.feature_vector.get("semantic_alignment")
    ai_trust_score = (
        float(ml_prediction_tmp.trust_score)
        if getattr(ml_prediction_tmp, "trust_score", None) is not None
        else None
    )
    ai_label = getattr(ml_prediction_tmp, "prediction_label", None)
    ai_trust_score, ai_label = _rule_adjusted_trust_label(report, ai_trust_score, ai_label)
    _persist_adjusted_ml_prediction(db, ml_prediction_tmp, ai_trust_score, ai_label)
    scorecard_now = (
        report.feature_vector.get("threshold_scorecard")
        if isinstance(getattr(report, "feature_vector", None), dict)
        and isinstance(report.feature_vector.get("threshold_scorecard"), dict)
        else None
    )
    unified_now = (
        report.feature_vector.get("unified_validation")
        if isinstance(getattr(report, "feature_vector", None), dict)
        and isinstance(report.feature_vector.get("unified_validation"), dict)
        else None
    )
    report.ai_verification_reason = _compose_ai_verification_reason(
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        is_flagged=report.is_flagged,
        flag_reason=report.flag_reason,
        ml_prediction_label=ai_label,
        trust_score=ai_trust_score,
        semantic_alignment=semantic_alignment_meta if isinstance(semantic_alignment_meta, dict) else None,
        incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
        reporter_description=report.description,
        context_tags=list(getattr(report, "context_tags", None) or []),
        reviewer_note=body.review_note,
        unified_validation=unified_now,
        scorecard=scorecard_now,
    )
    snapshot = _build_ai_analysis_snapshot(
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        is_flagged=report.is_flagged,
        flag_reason=report.flag_reason,
        ml_prediction_label=ai_label,
        trust_score=ai_trust_score,
        semantic_alignment=semantic_alignment_meta if isinstance(semantic_alignment_meta, dict) else None,
        incident_type_name=getattr(getattr(report, "incident_type", None), "type_name", None),
        reporter_description=report.description,
        context_tags=list(getattr(report, "context_tags", None) or []),
        unified_validation=unified_now,
        scorecard=scorecard_now,
        evidence_validations=(
            report.feature_vector.get("evidence_validations")
            if isinstance(getattr(report, "feature_vector", None), dict)
            and isinstance(report.feature_vector.get("evidence_validations"), list)
            else []
        ),
        evidence_file_count=len(getattr(report, "evidence_files", []) or []),
    )
    _persist_ai_analysis_snapshot(report, snapshot)

    existing_review = (
        db.query(PoliceReview)
        .filter(
            PoliceReview.report_id == report_id,
            PoliceReview.police_user_id == current_user.police_user_id,
        )
        .first()
    )

    if existing_review:
        review = existing_review
        review.decision = body.decision
        review.review_note = body.review_note
        review.reviewed_at = now_utc
    else:
        review = PoliceReview(
            review_id=uuid4(),
            report_id=report_id,
            police_user_id=current_user.police_user_id,
            decision=body.decision,
            review_note=body.review_note,
        )
        db.add(review)
    # Get client IP and user agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    try:
        # Recompute device aggregates after police final decision and ML override updates.
        if getattr(report, "device", None) is not None:
            update_device_ml_aggregates(db, report.device, window=30)

        db.commit()
        
        # Log the successful action
        log_action(
            db,
            "report_reviewed",
            actor_type="police_user",
            actor_id=current_user.police_user_id,
            entity_type="report",
            entity_id=str(report_id),
            action_details={
                "decision": body.decision,
                "updated_existing_review": bool(existing_review),
            },
            ip_address=client_ip,
            user_agent=user_agent,
            success=True,
        )
    except Exception as e:
        db.rollback()
        # Check if it's a duplicate key error
        if "duplicate key value violates unique constraint" in str(e) and "police_reviews_report_id_police_user_id_key" in str(e):
            raise HTTPException(status_code=400, detail="You have already reviewed this report")
        raise

    # Create notifications for report review
    from app.api.v1.notifications import create_role_notifications, create_notification
    
    # Notify admins and supervisors about the review decision
    decision_text = body.decision.upper()
    create_role_notifications(
        db,
        title=f"Report {decision_text}",
        message=f"Report {report.report_number} has been {body.decision} by {current_user.first_name} {current_user.last_name}.",
        notif_type="report",
        related_entity_type="report",
        related_entity_id=str(report_id),
        target_roles=["admin", "supervisor"],
        target_location_id=report.village_location_id,
        exclude_user_id=current_user.police_user_id,
    )
    
    # If there was an assigned officer, notify them about the review
    if hasattr(report, 'assignments') and report.assignments:
        for assignment in report.assignments:
            if assignment.police_user_id != current_user.police_user_id:
                create_notification(
                    db,
                    police_user_id=assignment.police_user_id,
                    title=f"Assigned Report {decision_text}",
                    message=f"Report {report.report_number} you were assigned has been {body.decision}.",
                    notif_type="report",
                    related_entity_type="report",
                    related_entity_id=str(report_id),
                )
    db.commit()
    db.refresh(review)
    reviewer_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email
    
    # Trigger real-time automation after police review decisions.
    # Cases need verified outcomes; hotspots should refresh for any final decision change.
    if report.verification_status == "verified":
        background_tasks.add_task(run_auto_case_for_report, str(report.report_id))
    background_tasks.add_task(run_hotspot_auto)
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "report", "action": "reviewed"})

    return ReviewResponse(
        review_id=review.review_id,
        report_id=review.report_id,
        police_user_id=review.police_user_id,
        decision=review.decision,
        review_note=review.review_note,
        reviewed_at=review.reviewed_at,
        reviewer_name=reviewer_name,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get a single report by ID."""
    from sqlalchemy.orm import joinedload
    
    report = (
        db.query(Report)
        .options(
            joinedload(Report.device),
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.evidence_files),
            joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
            joinedload(Report.assignments).joinedload(ReportAssignment.police_user).joinedload(PoliceUser.station),
            selectinload(Report.ml_predictions),
        )
        .filter(Report.report_id == report_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    return _build_report_detail_response(report, db)


@router.get("/{report_id}/reviews", response_model=List[ReviewResponse])
def get_reviews(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get all reviews for a report."""
    from sqlalchemy.orm import joinedload
    
    report = (
        db.query(Report)
        .options(joinedload(Report.police_reviews).joinedload(PoliceReview.police_user))
        .filter(Report.report_id == report_id)
        .first()
    )
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    review_list = []
    if getattr(report, "police_reviews", None):
        for r in report.police_reviews:
            reviewer_name = None
            if r.police_user:
                reviewer_name = f"{r.police_user.first_name or ''} {r.police_user.last_name or ''}".strip() or r.police_user.email
            review_list.append(
                ReviewResponse(
                    review_id=r.review_id,
                    report_id=r.report_id,
                    police_user_id=r.police_user_id,
                    decision=r.decision,
                    review_note=r.review_note,
                    reviewed_at=r.reviewed_at,
                    reviewer_name=reviewer_name,
                )
            )
    
    return review_list


@router.get("/{report_id}/related", response_model=List[ReportResponse])
def get_related_reports(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
):
    """Get related reports based on location and incident type."""
    from sqlalchemy.orm import joinedload
    
    # Get the original report
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Find related reports based on:
    # 1. Same incident type
    # 2. Nearby location (within ~5km)
    # 3. Recent reports (last 30 days)
    
    from datetime import datetime, timedelta
    from sqlalchemy import and_, or_
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Calculate nearby location bounds (approximate 5km radius)
    lat_diff = 0.05  # ~5.5km
    lon_diff = 0.05  # ~5.5km at equator
    
    related_reports = (
        db.query(Report)
        .options(
            joinedload(Report.device),
            joinedload(Report.incident_type),
            joinedload(Report.village_location),
            joinedload(Report.evidence_files),
            joinedload(Report.police_reviews).joinedload(PoliceReview.police_user),
        )
        .filter(
            and_(
                Report.report_id != report_id,  # Exclude the original report
                Report.reported_at >= thirty_days_ago,
                or_(
                    Report.incident_type_id == report.incident_type_id,  # Same incident type
                    and_(
                        Report.latitude.between(
                            float(report.latitude) - lat_diff,
                            float(report.latitude) + lat_diff
                        ),
                        Report.longitude.between(
                            float(report.longitude) - lon_diff,
                            float(report.longitude) + lon_diff
                        )
                    )  # Nearby location
                )
            )
        )
        .order_by(Report.reported_at.desc())
        .limit(limit)
        .all()
    )
    
    return [_build_report_response(r, db) for r in related_reports]


@router.get("/{report_id}/location-history")
def get_reporter_location_history(
    report_id: UUID,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Get location history for the reporter of a specific report.
    Returns chronological list of location changes with timestamps.
    """
    try:
        # Get the target report
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        # Get all reports from the same device (reporter)
        device_reports = (
            db.query(Report)
            .filter(Report.device_id == report.device_id)
            .filter(Report.report_id != report_id)  # Exclude current report
            .order_by(Report.reported_at.desc())
            .limit(limit)
            .all()
        )
        
        # Helper function to get location name from location relationship
        def get_location_name(location):
            if not location:
                return "Unknown"
            return location.location_name or "Unknown"
        
        # Build location history timeline
        location_history = []
        current_location = {
            "sector": get_location_name(report.location),
            "cell": get_location_name(report.village_location),
            "village": get_location_name(report.village_location),
        }
        
        # Add current report location first
        location_history.append({
            "report_id": str(report.report_id),
            "report_number": report.report_number,
            "timestamp": report.reported_at.isoformat(),
            "sector": current_location["sector"],
            "cell": current_location["cell"],
            "village": current_location["village"],
            "location_changed": False,  # This is the reference point
            "latitude": float(report.latitude) if report.latitude else None,
            "longitude": float(report.longitude) if report.longitude else None,
        })
        
        # Process historical reports to detect location changes
        for hist_report in device_reports:
            hist_location = {
                "sector": get_location_name(hist_report.location),
                "cell": get_location_name(hist_report.village_location),
                "village": get_location_name(hist_report.village_location),
            }
            
            # Check if location changed from previous
            location_changed = (
                hist_location["sector"] != current_location["sector"] or
                hist_location["cell"] != current_location["cell"] or
                hist_location["village"] != current_location["village"]
            )
            
            location_entry = {
                "report_id": str(hist_report.report_id),
                "report_number": hist_report.report_number,
                "timestamp": hist_report.reported_at.isoformat(),
                "sector": hist_location["sector"],
                "cell": hist_location["cell"],
                "village": hist_location["village"],
                "location_changed": location_changed,
                "latitude": float(hist_report.latitude) if hist_report.latitude else None,
                "longitude": float(hist_report.longitude) if hist_report.longitude else None,
            }
            
            location_history.append(location_entry)
            
            # Update current location for next comparison
            if location_changed:
                current_location = hist_location.copy()
        
        # Sort by timestamp (newest first)
        location_history.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return {
                "device_id": str(report.device_id),
                "current_location": current_location,
                "total_reports": len(location_history),
                "location_changes": len([loc for loc in location_history if loc["location_changed"]]),
                "history": location_history,
            }
    except Exception as e:
        # Log the error for debugging
        import logging
        logging.error(f"Error in location history endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/{report_id}/assign", response_model=AssignmentResponse, status_code=201)
def assign_report(
    report_id: UUID,
    body: AssignCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)] = None,
    db: Session = Depends(get_db),
):
    """Assign this report to an officer. Admin or supervisor only.

    - Admin: can assign to any active officer.
    - Supervisor: can assign only to officers in their own station (if they have one).
    """
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    officer = (
        db.query(PoliceUser)
        .filter(
            PoliceUser.police_user_id == body.police_user_id,
            PoliceUser.is_active == True,
        )
        .first()
    )
    if not officer:
        raise HTTPException(status_code=400, detail="Officer not found or inactive")

    # Supervisors can only assign to officers in their station.
    if current_user.role == "supervisor" and current_user.station_id is not None:
        if officer.station_id != current_user.station_id:
            raise HTTPException(
                status_code=403,
                detail="You can only assign reports to officers in your station",
            )
    if body.priority not in ("low", "medium", "high", "urgent"):
        raise HTTPException(status_code=400, detail="priority must be low, medium, high, or urgent")

    # Set handling_station_id when assigning to an officer with a station
    if officer.station_id is not None:
        report.handling_station_id = officer.station_id

    assignment = ReportAssignment(
        assignment_id=uuid4(),
        report_id=report_id,
        police_user_id=body.police_user_id,
        status="assigned",
        priority=body.priority,
        assignment_note=body.assignment_note,
    )
    db.add(assignment)
    create_notification(
        db,
        police_user_id=body.police_user_id,
        title="Report assigned",
        message=f"Report has been assigned to you (priority: {body.priority}).",
        notif_type="assignment",
        related_entity_type="report",
        related_entity_id=str(report_id),
    )
    # Get client IP and user agent for audit logging
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_action(
        db,
        "report_assigned",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id=str(report_id),
        action_details={"assigned_to": body.police_user_id, "priority": body.priority},
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    db.commit()
    db.refresh(assignment)
    officer_name = f"{officer.first_name or ''} {officer.last_name or ''}".strip() or officer.email
    
    background_tasks.add_task(manager.broadcast, {"type": "refresh_data", "entity": "report", "action": "assigned"})

    return AssignmentResponse(
        assignment_id=assignment.assignment_id,
        report_id=assignment.report_id,
        police_user_id=assignment.police_user_id,
        status=assignment.status,
        priority=assignment.priority,
        assignment_note=assignment.assignment_note,
        assigned_at=assignment.assigned_at,
        completed_at=assignment.completed_at,
        officer_name=officer_name,
    )


@router.post("/admin/purge-outside-musanze")
def purge_outside_musanze_reports_admin(
    request: Request,
    current_user: Annotated[PoliceUser, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Admin-only cleanup: remove reports outside covered Musanze village polygons."""
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    deleted_reports, recomputed_hotspots = _purge_outside_musanze_reports(
        db,
        recompute_hotspots=True,
    )

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    log_action(
        db,
        "purge_outside_musanze_reports",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="report",
        entity_id="bulk",
        action_details={
            "deleted_reports": deleted_reports,
            "recomputed_hotspots": recomputed_hotspots,
        },
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    db.commit()

    return {
        "status": "ok",
        "deleted_reports": deleted_reports,
        "recomputed_hotspots": recomputed_hotspots,
    }


@router.post("/{report_id}/evidence/{evidence_id}/validate")
def validate_evidence(
    report_id: UUID,
    evidence_id: UUID,
    ground_truth_label: str = Form(...),
    verification_confidence: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: Annotated[PoliceUser, Depends(get_current_user)] = None,
    request: Request = None,
):
    """
    Validate evidence with ground truth label for AI training.
    
    Args:
        ground_truth_label: "real", "fake", or "manipulated"
        verification_confidence: 0-100 confidence in the ground truth assessment
    """
    if ground_truth_label not in ("real", "fake", "manipulated"):
        raise HTTPException(status_code=400, detail="ground_truth_label must be real, fake, or manipulated")
    
    # Verify evidence exists and belongs to report
    evidence = db.query(EvidenceFile).filter(
        EvidenceFile.evidence_id == evidence_id,
        EvidenceFile.report_id == report_id
    ).first()
    
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # Update evidence with ground truth
    evidence.ground_truth_label = ground_truth_label
    evidence.evidence_verified_by = current_user.police_user_id
    evidence.evidence_verified_at = datetime.now(timezone.utc)
    evidence.verification_confidence = verification_confidence
    
    # Log the validation action
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    log_action(
        db,
        "evidence_validated",
        actor_type="police_user",
        actor_id=current_user.police_user_id,
        entity_type="evidence_file",
        entity_id=str(evidence_id),
        action_details={
            "ground_truth_label": ground_truth_label,
            "verification_confidence": verification_confidence,
            "ai_analysis": {
                "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
                "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
                "quality_label": evidence.quality_label.value if evidence.quality_label else None
            }
        },
        ip_address=client_ip,
        user_agent=user_agent,
        success=True,
    )
    
    db.commit()
    
    return {
        "evidence_id": str(evidence.evidence_id),
        "ground_truth_label": evidence.ground_truth_label,
        "verified_at": evidence.evidence_verified_at,
        "verified_by": current_user.police_user_id,
        "ai_analysis": {
            "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
            "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
            "quality_label": evidence.quality_label.value if evidence.quality_label else None
        }
    }


@router.get("/evidence-training-data")
def get_evidence_training_data(
    current_user: Annotated[PoliceUser, Depends(get_current_admin_or_supervisor)],
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    include_unvalidated: bool = Query(False),
):
    """
    Get evidence data with AI analysis and ground truth for ML training.
    
    Args:
        limit: Maximum number of records to return
        include_unvalidated: Include evidence without ground truth labels
    """
    query = db.query(EvidenceFile).options(
        joinedload(EvidenceFile.report)
    )
    
    if not include_unvalidated:
        query = query.filter(EvidenceFile.ground_truth_label.isnot(None))
    
    evidence_list = query.limit(limit).all()
    
    training_data = []
    for evidence in evidence_list:
        training_data.append({
            "evidence_id": str(evidence.evidence_id),
            "report_id": str(evidence.report_id),
            "file_type": evidence.file_type,
            "file_size": evidence.file_size,
            "blur_score": float(evidence.blur_score) if evidence.blur_score else None,
            "tamper_score": float(evidence.tamper_score) if evidence.tamper_score else None,
            "quality_label": evidence.quality_label.value if evidence.quality_label else None,
            "ground_truth_label": evidence.ground_truth_label,
            "verification_confidence": float(evidence.verification_confidence) if evidence.verification_confidence else None,
            "verified_by": evidence.evidence_verified_by,
            "verified_at": evidence.evidence_verified_at.isoformat() if evidence.evidence_verified_at else None,
            "is_live_capture": evidence.is_live_capture,
            "ai_checked_at": evidence.ai_checked_at.isoformat() if evidence.ai_checked_at else None,
        })
    
    return {
        "training_data": training_data,
        "total_count": len(training_data),
        "includes_unvalidated": include_unvalidated,
    }


@router.post("/{report_id}/evidence")
async def upload_evidence(
    report_id: str,
    file: UploadFile = File(...),
    device_id: Optional[str] = Form(None, description="Device ID UUID (mobile: required to add evidence to own report)."),
    media_latitude: Optional[float] = Form(None),
    media_longitude: Optional[float] = Form(None),
    captured_at: Optional[datetime] = Form(None),
    is_live_capture: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    request: Request = None,
):
    """Upload evidence file (photo/video) for a report.

    Mobile: pass device_id to add evidence to your own report (only within evidence_add_window_hours after submit).
    Police dashboard: no device_id; requires auth (future use).
    """
    print(f"Evidence upload - report_id: {report_id}, device_id: {device_id}, filename: {file.filename}")  # Debug log
    
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    device: Optional[Device] = report.device

    device_id_uuid: Optional[UUID] = None
    if device_id is not None and device_id.strip():
        try:
            device_id_uuid = UUID(device_id.strip())
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid device_id format")

    if device_id_uuid is not None:
        print(f"Device ID validation - report.device_id: {report.device_id}, device_id_uuid: {device_id_uuid}")  # Debug log
        if str(report.device_id) != str(device_id_uuid):
            print("Device ID mismatch - raising 403")  # Debug log
            raise HTTPException(status_code=403, detail="You can only add evidence to your own report")
        window_hours = getattr(settings, "evidence_add_window_hours", 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
        print(f"Time window check - reported_at: {reported_at}, cutoff: {cutoff}, window_hours: {window_hours}")  # Debug log
        if reported_at < cutoff:
            print("Time window exceeded - raising 400")  # Debug log
            raise HTTPException(
                status_code=400,
                detail=f"You can add evidence only within {window_hours} hours of submitting the report",
            )
    elif current_user is None:
        print("No device_id and no current_user - raising 400")  # Debug log
        raise HTTPException(status_code=400, detail="device_id required to add evidence (mobile)")

    # Read file content once
    content = await file.read()

    file_ext = file.filename.split(".")[-1].lower() if file.filename and "." in file.filename else ""
    # Basic extension-based type detection (content_type first, then extension)
    image_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
    video_exts = {"mp4", "mov", "m4v", "avi", "mkv", "webm"}
    audio_exts = {"mp3", "wav", "aac", "m4a", "ogg", "flac"}

    is_image = False
    is_audio = False

    # 1) Try to classify by content_type
    if file.content_type:
        ct = file.content_type.lower()
        if ct.startswith("image/"):
            is_image = True
        elif ct.startswith("audio/"):
            is_audio = True
        # if it's "application/octet-stream" or something else, we'll fall back to extension

    # 2) If still unknown, fall back to extension
    if not (is_image or is_audio):
        if file_ext in image_exts:
            is_image = True
        elif file_ext in audio_exts:
            is_audio = True
        # otherwise we'll treat it as video by default

    if is_image:
        file_type = "photo"
    elif is_audio:
        file_type = "audio"
    else:
        file_type = "video"

    # Rule-based: no screenshots or screen recordings (image, audio, or video)
    # Conservative check: filename + optional image metadata.
    is_screenshot = is_likely_screenshot_or_screen_recording(
        filename=file.filename,
        image_bytes=content if is_image else None,
    )
    if is_screenshot:
        _log_blocked_attempt(
            db,
            action_type="evidence_blocked_screenshot",
            request=request,
            device=report.device,
            report_id=str(report.report_id),
            details={
                "filename": file.filename,
                "file_type": file_type,
                "reason": "screenshot_or_screen_recording_detected",
            },
        )
        raise HTTPException(
            status_code=400,
            detail="Screenshots and screen recordings are not allowed. Please upload a photo, audio, or video taken with your camera or recorder.",
        )

    # Prevent evidence reuse from the same device (common fake-evidence pattern).
    content_hash = hashlib.sha256(content).hexdigest()
    if device_id_uuid is not None:
        duplicate_evidence = (
            db.query(EvidenceFile.evidence_id)
            .join(Report, EvidenceFile.report_id == Report.report_id)
            .filter(
                Report.device_id == device_id_uuid,
                EvidenceFile.perceptual_hash == content_hash,
            )
            .first()
        )
        if duplicate_evidence:
            _log_blocked_attempt(
                db,
                action_type="evidence_blocked_reuse",
                request=request,
                device=report.device,
                report_id=str(report.report_id),
                details={
                    "filename": file.filename,
                    "file_type": file_type,
                    "reason": "duplicate_evidence_hash",
                },
            )
            raise HTTPException(
                status_code=409,
                detail="This evidence appears to have been reused from a previous report on this device. Please upload original evidence.",
            )

    # Cloudinary upload if configured, otherwise save locally
    print(f"Cloudinary enabled: {_CLOUDINARY_ENABLED}")  # Debug log
    print(f"Cloudinary config - cloud_name: {settings.cloudinary_cloud_name}, api_key configured: {bool(settings.cloudinary_api_key)}")  # Debug log
    cloudinary_public_id: Optional[str] = None
    cloudinary_secure_url: Optional[str] = None

    if _CLOUDINARY_ENABLED:
        # Match test_cloudinary.py: folder + explicit resource_type so assets land predictably.
        upload_opts: Dict[str, Any] = {"folder": "trustbond/evidence"}
        if is_image:
            upload_opts["resource_type"] = "image"
        elif is_audio:
            # Cloudinary stores many audio codecs under the video resource pipeline.
            upload_opts["resource_type"] = "video"
        else:
            upload_opts["resource_type"] = "video"

        try:
            # Wrap bytes in a file-like object so Cloudinary treats it as an uploaded file
            file_obj = io.BytesIO(content)
            # Give Cloudinary a sensible name (helps with type detection / extensions)
            file_obj.name = file.filename or f"{uuid4()}.{file_ext or 'bin'}"

            upload_result = cloudinary.uploader.upload(file_obj, **upload_opts)
            file_url = upload_result.get("secure_url") or upload_result.get("url")
            cloudinary_public_id = upload_result.get("public_id")
            cloudinary_secure_url = file_url
        except Exception as e:
            # In production mode with Cloudinary configured, we do NOT write to local disk.
            # The mobile client may queue retries locally and resend later.
            print(f"[Cloudinary] upload error for report {report_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Cloudinary upload failed: {e}")
    else:
        # Dev mode without full Cloudinary credentials: save to local disk (see test_cloudinary.py for upload smoke test).
        safe_ext = file_ext or "bin"
        file_name = f"{uuid4()}.{safe_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as f:
            f.write(content)
        file_url = f"/uploads/evidence/{file_name}"

    # EXIF-based metadata extraction for images
    exif_lat = exif_lon = None
    exif_dt = None
    if is_image:
        exif_lat, exif_lon, exif_dt = _extract_exif_metadata(content)

    final_lat = exif_lat if exif_lat is not None else media_latitude
    final_lon = exif_lon if exif_lon is not None else media_longitude

    # captured_at priority:
    # 1) EXIF DateTimeOriginal / DateTime (true capture time if present)
    # 2) Client-provided captured_at (from mobile app)
    # 3) Optional fallback to report.reported_at for live captures only
    final_captured_at = exif_dt if exif_dt is not None else captured_at
    if final_captured_at is None and is_live_capture:
        # For true live captures (camera in app), if we somehow didn't get
        # EXIF or client timestamp, approximate with report time.
        final_captured_at = report.reported_at
    
    # Perform AI analysis on evidence
    ai_analysis = None
    try:
        ai_analysis = analyze_evidence_file(content, file_type, filename=file.filename)
        print(f"AI Analysis completed for evidence: {ai_analysis}")
    except Exception as e:
        print(f"AI Analysis failed for evidence: {e}")
        ai_analysis = {
            'blur_score': None,
            'tamper_score': 50.0,
            'quality_label': 'fair',
            'ai_checked_at': datetime.now(timezone.utc),
            'analysis_error': str(e)
        }
    
    evidence = EvidenceFile(
        evidence_id=uuid4(),
        report_id=report.report_id,
        file_url=file_url,
        file_type=file_type,
        file_size=len(content),
        duration=ai_analysis.get("duration_seconds"),
        perceptual_hash=content_hash,
        media_latitude=final_lat,
        media_longitude=final_lon,
        captured_at=final_captured_at,
        is_live_capture=is_live_capture,
        blur_score=ai_analysis.get('blur_score'),
        tamper_score=ai_analysis.get('tamper_score'),
        quality_label=_coerce_evidence_quality(ai_analysis.get('quality_label')),
        ai_checked_at=ai_analysis.get('ai_checked_at'),
        cloudinary_public_id=cloudinary_public_id,
        cloudinary_url=cloudinary_secure_url,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    # Re-run AI-enhanced rule-based verification (evidence count changed)
    report_after = db.query(Report).filter(Report.report_id == report.report_id).first()
    if report_after:
        # Validate newly uploaded evidence and persist semantic audit fields.
        try:
            current_validations: List[Dict[str, Any]] = []
            fv_existing = report_after.feature_vector if isinstance(report_after.feature_vector, dict) else {}
            if isinstance(fv_existing.get("evidence_validations"), list):
                current_validations = list(fv_existing.get("evidence_validations") or [])

            transcript_excerpt = (ai_analysis.get("transcript") or "").strip()
            semantic_validation = {
                "valid": True,
                "confidence": float(ai_analysis.get("volo_confidence") or 0.65),
                "threshold_used": 0.6,
                "issues": [],
                "analysis_summary": {
                    "media_type": file_type,
                    "detected_objects": ai_analysis.get("detected_objects") or [],
                    "extracted_text": transcript_excerpt[:500] if transcript_excerpt else None,
                },
                "advanced_analysis": ai_analysis.get("advanced_analysis") or {},
            }

            if semantic_validation:
                current_validations.append({
                    "evidence_url": file_url,
                    "validation": semantic_validation,
                })

                incident_type_row = (
                    db.query(IncidentType)
                    .filter(IncidentType.incident_type_id == report_after.incident_type_id)
                    .first()
                )
                semantic_alignment = _semantic_alignment_check(
                    report_description=report_after.description or "",
                    incident_type_name=getattr(incident_type_row, "type_name", "") or "",
                    incident_type_description=getattr(incident_type_row, "description", "") or "",
                    evidence_semantic_text=_build_evidence_semantic_text(current_validations),
                )

                fv_update = report_after.feature_vector if isinstance(report_after.feature_vector, dict) else {}
                fv_update["evidence_validations"] = current_validations
                if semantic_alignment:
                    fv_update["semantic_alignment"] = semantic_alignment
                    if semantic_alignment.get("mismatch"):
                        report_after.is_flagged = True
                        report_after.rule_status = "flagged"
                        report_after.verification_status = "under_review"
                        if not report_after.flag_reason:
                            report_after.flag_reason = "description_evidence_mismatch"
                report_after.feature_vector = _json_safe(fv_update)
        except Exception as e:
            logger.warning(f"Post-upload semantic validation failed for report {report_after.report_id}: {e}")

        evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_after.report_id).count()
        print(f"Re-applying AI-enhanced rules after evidence upload - evidence_count: {evidence_count}")  # Debug log
        
        # Re-run unified validation so TrustBond/NL/VOLO only contribute signals.
        unified_validation_data = None
        try:
            from app.core.unified_validator import validate_report_unified

            validation_result = validate_report_unified(
                db=db,
                report=report_after,
                device=device,
                evidence_files=list(getattr(report_after, "evidence_files", []) or []),
            )
            unified_validation_data = _store_unified_validation_result(db, report_after, validation_result)
        except Exception as e:
            logger.error(f"Unified validation failed after evidence upload for {report_after.report_id}: {e}")

        ml_prediction = resolve_ml_prediction_for_report(report_after)
        if ml_prediction is not None:
            print(f"Using ML prediction for re-evaluation: {ml_prediction.prediction_label}, trust_score: {ml_prediction.trust_score}")  # Debug log

        # Apply AI-enhanced rules
        from app.core.report_priority import apply_anti_fraud_rules, calculate_report_priority
        rule_status, is_flagged, flag_reason = apply_anti_fraud_rules(
            report_after, evidence_count, db
        )
        print(f"AI-enhanced rule result after evidence upload - rule_status: {rule_status}, is_flagged: {is_flagged}, flag_reason: {flag_reason}")  # Debug log
        
        # Recalculate priority with unified validation
        unified_validation_data = (
            unified_validation_data
            if isinstance(unified_validation_data, dict)
            else report_after.feature_vector.get('unified_validation', {}) if isinstance(report_after.feature_vector, dict) else {}
        )
        priority = calculate_report_priority(report_after, evidence_count, db, unified_validation_data)
        print(f"Recalculated priority after evidence upload: {priority}")  # Debug log
        
        report_after.rule_status = rule_status
        report_after.is_flagged = is_flagged
        report_after.priority = priority  # Save recalculated priority
        if is_flagged and flag_reason:
            report_after.flag_reason = flag_reason
        votes_after = {"real": 0, "false": 0, "unknown": 0}
        fv_votes = report_after.feature_vector if isinstance(report_after.feature_vector, dict) else {}
        vv_after = fv_votes.get("community_votes", {}) if isinstance(fv_votes.get("community_votes", {}), dict) else {}
        for v in vv_after.values():
            k = str(v)
            if k in votes_after:
                votes_after[k] += 1
        scorecard_after = _compute_threshold_scorecard(
            report_after,
            ml_prediction=ml_prediction,
            community_votes=votes_after,
            unified_validation=unified_validation_data,
        )
        fv_votes["threshold_scorecard"] = scorecard_after
        report_after.feature_vector = _json_safe(fv_votes)
        _apply_threshold_outcome(report_after, scorecard_after)

        # Persist human-readable AI summary and decision reasoning on report row.
        fv_after = report_after.feature_vector if isinstance(report_after.feature_vector, dict) else {}
        validations_after = fv_after.get("evidence_validations") if isinstance(fv_after.get("evidence_validations"), list) else []
        semantic_after = fv_after.get("semantic_alignment") if isinstance(fv_after.get("semantic_alignment"), dict) else None
        report_after.ai_evidence_description = _compose_ai_evidence_description(
            validations_after,
            incident_type_name=getattr(getattr(report_after, "incident_type", None), "type_name", None),
            reporter_description=report_after.description,
            context_tags=list(getattr(report_after, "context_tags", None) or []),
            evidence_file_count=len(validations_after),
            unified_validation=unified_validation_data,
            scorecard=scorecard_after,
        )
        ai_trust_score = (
            float(ml_prediction.trust_score)
            if ml_prediction and getattr(ml_prediction, "trust_score", None) is not None
            else None
        )
        ai_label = getattr(ml_prediction, "prediction_label", None) if ml_prediction else None
        ai_trust_score, ai_label = _rule_adjusted_trust_label(report_after, ai_trust_score, ai_label)
        _persist_adjusted_ml_prediction(db, ml_prediction, ai_trust_score, ai_label)
        try:
            update_device_ml_aggregates(db, device, window=30)
        except Exception:
            pass
        report_after.ai_verification_reason = _compose_ai_verification_reason(
            verification_status=report_after.verification_status,
            rule_status=report_after.rule_status,
            is_flagged=report_after.is_flagged,
            flag_reason=report_after.flag_reason,
            ml_prediction_label=ai_label,
            trust_score=ai_trust_score,
            semantic_alignment=semantic_after,
            incident_type_name=getattr(getattr(report_after, "incident_type", None), "type_name", None),
            reporter_description=report_after.description,
            context_tags=list(getattr(report_after, "context_tags", None) or []),
            unified_validation=unified_validation_data,
            scorecard=scorecard_after,
        )
        snapshot_after = _build_ai_analysis_snapshot(
            verification_status=report_after.verification_status,
            rule_status=report_after.rule_status,
            is_flagged=report_after.is_flagged,
            flag_reason=report_after.flag_reason,
            ml_prediction_label=ai_label,
            trust_score=ai_trust_score,
            semantic_alignment=semantic_after if isinstance(semantic_after, dict) else None,
            incident_type_name=getattr(getattr(report_after, "incident_type", None), "type_name", None),
            reporter_description=report_after.description,
            context_tags=list(getattr(report_after, "context_tags", None) or []),
            unified_validation=unified_validation_data,
            scorecard=scorecard_after,
            evidence_validations=validations_after,
            evidence_file_count=len(validations_after),
        )
        _persist_ai_analysis_snapshot(report_after, snapshot_after)
        db.commit()
    
    await manager.broadcast({"type": "refresh_data", "entity": "report", "action": "evidence_added"})
    
    return {"evidence_id": str(evidence.evidence_id), "file_url": file_url}
@router.post("/{report_id}/confirm")
def add_community_confirmation(
    report_id: UUID,
    body: CommunityVoteRequest,
    db: Session = Depends(get_db),
):
    """
    Allow community users to vote on a report to bridge directly into the credibility scoring system.
    """
    if body.vote.lower() not in ["real", "false", "unknown"]:
        raise HTTPException(status_code=400, detail="vote must be 'real', 'false', or 'unknown'")

    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
        
    device_id_str = str(body.device_id).strip()
    if not device_id_str:
        raise HTTPException(status_code=400, detail="device_id required")
        
    if str(report.device_id) == device_id_str:
        raise HTTPException(status_code=400, detail="You cannot vote on your own report")

    # Access feature_vector safely
    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        fv = {}
        
    votes = fv.get("community_votes", {})
    if not isinstance(votes, dict):
        votes = {}
        
    # Apply vote
    votes[device_id_str] = body.vote.lower()
    fv["community_votes"] = votes
    
    # Must explicitly set it for SQLAlchemy JSONB mutation
    report.feature_vector = fv 
    
    db.commit()
    db.refresh(report)
    
    device = report.device
    # Recalculate credibility score since community votes changed
    evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).count()
    score_report_credibility(db, report, device, evidence_count)
    _ensure_fallback_ml_prediction_if_missing(db, report)
    update_device_ml_aggregates(db, device)

    # Persist updated ML prediction + device aggregates so the response includes fresh trust.
    db.commit()
    db.refresh(report)

    # Update report lifecycle state based on the new ML trust score
    try:
        from app.models.ml_prediction import MLPrediction
        latest_ml = (
            db.query(MLPrediction)
            .filter(MLPrediction.report_id == report_id)
            .order_by(MLPrediction.evaluated_at.desc())
            .first()
        )

        if latest_ml:
            trust_score = float(latest_ml.trust_score) if latest_ml.trust_score is not None else 0.0
            prediction_label = (latest_ml.prediction_label or "").lower()

            # Get ML thresholds from system config
            from app.database import SessionLocal
            from app.models.system_config import SystemConfig
            
            db = SessionLocal()
            try:
                auto_verify_config = db.query(SystemConfig).filter(
                    SystemConfig.config_key == 'ml.auto_verification_threshold'
                ).first()
                under_review_config = db.query(SystemConfig).filter(
                    SystemConfig.config_key == 'ml.under_review_threshold'
                ).first()
                
                auto_verify_threshold = float(auto_verify_config.config_value.get('value', 70.0)) if auto_verify_config else 70.0
                under_review_threshold = float(under_review_config.config_value.get('value', 45.0)) if under_review_config else 45.0
            finally:
                db.close()

            # AI-PRIMARY: Community voting disabled - AI makes all decisions
            # Community votes only affect ML model training, not verification status
            print(" AI-PRIMARY: Community vote processed, but verification status unchanged")
    except Exception:
        # Best-effort only: community vote must not fail if state update is blocked
        pass
    
    return _build_report_response(report, db, request_device_id=device_id_str)


@router.get("/nearby-confirmations", response_model=List[ReportResponse])
def list_nearby_confirmations(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_meters: int = Query(600, ge=50, le=5000),
    limit: int = Query(10, ge=1, le=30),
    device_id: Optional[str] = Query(None),
    device_hash: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    AI-PRIMARY: Community confirmation disabled - return empty list
    In AI-primary mode, there are no pending reports for community confirmation.
    """
    # AI-PRIMARY: No community confirmation needed
    return []

    import math

    def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000.0
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        a = math.sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * math.sin(d_lon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    candidates = q.all()
    enriched: list[tuple[float, Report]] = []
    for r in candidates:
        if r.latitude is None or r.longitude is None:
            continue
        dist = haversine_m(lat, lon, float(r.latitude), float(r.longitude))
        if dist <= radius_meters:
            enriched.append((dist, r))

    enriched.sort(key=lambda x: (x[0], (x[1].reported_at or datetime.min.replace(tzinfo=timezone.utc))))
    selected = [rr for _, rr in enriched[:limit]]

    return [_build_report_response(r, db, request_device_id=str(device.device_id)) for r in selected]


@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    device_id: Optional[str] = Query(None, description="Device ID of the original reporter"),
    background_tasks: BackgroundTasks = None,
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
):
    """
    Allow a user or admin to delete a report. Primary use case: rollback if evidence upload fails.
    """
    report = db.query(Report).filter(Report.report_id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    is_authorized = False
    
    # Check if admin/supervisor
    if current_user and current_user.role in ["admin", "supervisor"]:
        is_authorized = True
        
    # Check if original creator
    if device_id and str(report.device_id) == str(device_id):
        # Only allow if it's still pending OR was very recently created (rollback window)
        now = datetime.now(timezone.utc)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
            
        age_seconds = (now - reported_at).total_seconds()
        
        if report.rule_status == "pending" or age_seconds < 300:
            is_authorized = True

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized to delete this report")

    db.delete(report)
    db.commit()
    if background_tasks is not None:
        # Recompute hotspots after deletions so map stays live and accurate.
        background_tasks.add_task(run_hotspot_auto)
    return {}


def _check_and_create_auto_case(report_id: str):
    """Background task to add verified report to existing case or create new case using proper location-based clustering"""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report or report.verification_status != "verified":
            logger.info(
                "[AUTO_CASE] Skip report %s: report_exists=%s verification_status=%s",
                report_id,
                bool(report),
                getattr(report, "verification_status", None),
            )
            return
        
        # Check if report is already in a case
        from app.models.case_reports import case_reports_table
        existing_case = db.query(case_reports_table).filter(
            case_reports_table.c.report_id == report_id
        ).first()
        
        if existing_case:
            logger.info("[AUTO_CASE] Skip report %s: already linked to case", report_id)
            return
        
        # Get clustering parameters from system config
        from app.models.system_config import SystemConfig
        dbscan_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.epsilon'
        ).first()
        min_samples_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.min_samples'
        ).first()
        
        # Use configured values or defaults
        cluster_radius_meters = 500  # Default 500m for better incident grouping
        min_reports_threshold = 3   # Default from system config
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 500)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 3)

        logger.info(
            "[AUTO_CASE] Start report %s: incident_type=%s village=%s radius_m=%s min_reports=%s",
            report_id,
            report.incident_type_id,
            report.village_location_id,
            cluster_radius_meters,
            min_reports_threshold,
        )
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # STRATEGY 1: Try to add to existing case first
        existing_case_added = _try_add_to_existing_case(db, report, cluster_radius_km)
        if existing_case_added:
            logger.info("[AUTO_CASE] Report %s attached to existing case", report_id)
            return
        
        # STRATEGY 2: Create new case if no existing case found
        _create_new_case_for_report(db, report, cluster_radius_km, min_reports_threshold)
    
    except Exception as e:
        print(f"Error in auto-case processing for report {report_id}: {e}")
    finally:
        db.close()


def _try_add_to_existing_case(db: Session, report: Report, cluster_radius_km: float) -> bool:
    """Try to add report to existing compatible case"""
    try:
        from app.models.case import Case
        from app.models.case_reports import case_reports_table
        
        # Find existing cases with same incident type that are still open
        compatible_cases = db.query(Case).filter(
            Case.incident_type_id == report.incident_type_id,
            Case.status.in_(['open', 'assigned', 'in_progress']),
            Case.latitude.isnot(None),
            Case.longitude.isnot(None)
        ).all()

        logger.info(
            "[AUTO_CASE] Existing-case scan report=%s compatible_cases=%s",
            report.report_id,
            len(compatible_cases),
        )
        
        if not compatible_cases:
            return False
        
        from math import radians, cos, sin, asin, sqrt
        
        def calculate_distance(lat1, lon1, lat2, lon2):
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c  # Returns distance in kilometers
        
        # Priority 1: Same village (most precise)
        if report.village_location_id:
            for case in compatible_cases:
                if case.location_id == report.village_location_id:
                    # Add report to this case
                    db.execute(
                        case_reports_table.insert().values(
                            case_id=case.case_id,
                            report_id=report.report_id,
                            added_at=datetime.now(timezone.utc)
                        )
                    )
                    # Update case report count and timestamp
                    case.report_count = (case.report_count or 0) + 1
                    case.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    print(f"Added report {report.report_id} to existing case {case.case_number} (same village)")
                    return True
        
        # Priority 2: Geographic proximity (fallback)
        for case in compatible_cases:
            distance = calculate_distance(
                report.latitude, report.longitude,
                float(case.latitude), float(case.longitude)
            )
            logger.info(
                "[AUTO_CASE] Distance check report=%s case=%s distance_km=%.3f threshold_km=%.3f",
                report.report_id,
                case.case_number,
                distance,
                cluster_radius_km,
            )
            if distance <= cluster_radius_km:
                # Add report to this case
                db.execute(
                    case_reports_table.insert().values(
                        case_id=case.case_id,
                        report_id=report.report_id,
                        added_at=datetime.now(timezone.utc)
                    )
                )
                # Update case report count and timestamp
                case.report_count = (case.report_count or 0) + 1
                case.updated_at = datetime.now(timezone.utc)
                db.commit()
                print(f"Added report {report.report_id} to existing case {case.case_number} (within {cluster_radius_km * 1000:.0f}m)")
                return True
        
        return False
        
    except Exception as e:
        print(f"Error trying to add report to existing case: {e}")
        return False


def _create_new_case_for_report(db: Session, report: Report, cluster_radius_km: float, min_reports_threshold: int):
    """Create new case for report if enough similar reports exist"""
    try:
        from app.models.case_reports import case_reports_table
        
        # Strategy 1: Cluster by same village/location (preferred)
        if report.village_location_id:
            village_reports = db.query(Report).filter(
                Report.incident_type_id == report.incident_type_id,
                Report.verification_status == "verified",
                Report.village_location_id == report.village_location_id,
                Report.report_id != report.report_id,
                ~Report.report_id.in_(
                    db.query(case_reports_table.c.report_id).distinct()
                )
            ).all()
            
            # Add the current report
            village_reports.insert(0, report)
            logger.info(
                "[AUTO_CASE] Village candidate report=%s count=%s threshold=%s village=%s",
                report.report_id,
                len(village_reports),
                min_reports_threshold,
                report.village_location_id,
            )
            
            # Create case if enough reports in same village
            if len(village_reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, village_reports)
                if case_stats['cases_created'] > 0:
                    print(f"Created new village-based case {case_stats['case_number']} with {len(village_reports)} reports in village {report.village_location_id}")
                    return
            else:
                logger.info(
                    "[AUTO_CASE] Village threshold not met report=%s %s/%s",
                    report.report_id,
                    len(village_reports),
                    min_reports_threshold,
                )
        
        # Strategy 2: Geographic clustering using GPS coordinates (fallback)
        from math import radians, cos, sin, asin, sqrt
        
        def calculate_distance(lat1, lon1, lat2, lon2):
            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c  # Returns distance in kilometers
        
        # Find nearby reports using GPS coordinates
        nearby_reports = db.query(Report).filter(
            Report.incident_type_id == report.incident_type_id,
            Report.verification_status == "verified",
            Report.report_id != report.report_id,
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            )
        ).all()
        
        # Filter by geographic proximity
        clustered_reports = [report]
        for other_report in nearby_reports:
            distance = calculate_distance(
                report.latitude, report.longitude,
                other_report.latitude, other_report.longitude
            )
            if distance <= cluster_radius_km:  # Use configured radius
                clustered_reports.append(other_report)

        logger.info(
            "[AUTO_CASE] Geo candidate report=%s count=%s threshold=%s radius_km=%.3f",
            report.report_id,
            len(clustered_reports),
            min_reports_threshold,
            cluster_radius_km,
        )
        
        # Create case if enough reports geographically clustered
        if len(clustered_reports) >= min_reports_threshold:
            case_stats = _create_case_from_reports(db, clustered_reports)
            if case_stats['cases_created'] > 0:
                print(f"Created new geo-clustered case {case_stats['case_number']} with {len(clustered_reports)} reports within {cluster_radius_km * 1000:.0f}m")
        else:
            logger.info(
                "[AUTO_CASE] Geo threshold not met report=%s %s/%s",
                report.report_id,
                len(clustered_reports),
                min_reports_threshold,
            )
    
    except Exception as e:
        print(f"Error creating new case for report: {e}")


def _auto_remove_rejected_report(report_id: str):
    """Background task to safely remove rejected reports"""
    from app.database import SessionLocal
    
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        if not report:
            return
        
        # Double-check it's still rejected before removal
        if report.verification_status == "rejected" and report.status == "rejected":
            # Remove evidence files first
            from app.models.evidence import EvidenceFile
            evidence_files = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).all()
            for evidence in evidence_files:
                db.delete(evidence)
            
            # Remove ML predictions
            from app.models.ml_prediction import MLPrediction
            ml_predictions = db.query(MLPrediction).filter(MLPrediction.report_id == report_id).all()
            for ml_pred in ml_predictions:
                db.delete(ml_pred)
            
            # Remove case associations
            from app.models.case_reports import case_reports_table
            db.execute(case_reports_table.delete().where(case_reports_table.c.report_id == report_id))
            
            # Finally remove the report
            db.delete(report)
            db.commit()
            
            print(f" Successfully removed rejected report {report_id}")
            
            # Broadcast removal to keep clients in sync
            from app.api.v1.ws import manager
            try:
                background_tasks.add_task(
                    manager.broadcast,
                    {"type": "refresh_data", "entity": "report", "action": "deleted", "report_id": report_id}
                )
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast report removal: {broadcast_error}")
        
    except Exception as e:
        print(f"Error removing rejected report {report_id}: {e}")
        db.rollback()
    finally:
        db.close()


def _balance_report_workload_and_reassign(db: Session):
    """Smart workload balancing for assigned reports across multiple officers"""
    try:
        from app.models.report import Report
        from app.models.police_user import PoliceUser
        from sqlalchemy import func
        
        # Get all active officers
        officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer'
        ).all()
        
        if len(officers) < 2:
            return  # Need at least 2 officers for balancing
        
        # Calculate current report workload per officer
        workload = {str(officer.police_user_id): 0 for officer in officers}
        for officer_id, count in db.query(Report.verified_by, func.count(Report.report_id)).filter(
            Report.verified_by.in_([o.police_user_id for o in officers]),
            Report.status.in_(['pending', 'under_review'])
        ).group_by(Report.verified_by).all():
            workload[str(officer_id)] = count
        
        # Find overloaded and underloaded officers
        avg_reports = sum(workload.values()) / len(workload)
        overloaded = [oid for oid, count in workload.items() if count > avg_reports + 3]  # Threshold of 3 reports above average
        underloaded = [oid for oid, count in workload.items() if count < avg_reports - 1]  # Threshold of 1 report below average
        
        if not overloaded or not underloaded:
            return  # Workload is already balanced
        
        # Reassign reports from overloaded to underloaded officers
        reassigned = 0
        for overloaded_officer in overloaded:
            # Get newest assigned reports from overloaded officer (only flagged/boundary reports)
            reports_to_reassign = db.query(Report).filter(
                Report.verified_by == int(overloaded_officer),
                Report.status.in_(['pending', 'under_review']),
                Report.is_flagged == True,  # Only reassign flagged reports
                Report.reported_at >= datetime.now(timezone.utc) - timedelta(hours=6)  # Only recent reports (6 hours)
            ).order_by(Report.reported_at.desc()).limit(2).all()
            
            for report in reports_to_reassign:
                if underloaded:
                    # Find least loaded underloaded officer
                    target_officer = min(underloaded, key=lambda oid: workload[oid])
                    
                    # Reassign report
                    old_officer_id = report.verified_by
                    report.verified_by = int(target_officer)
                    report.handling_station_id = db.query(PoliceUser.station_id).filter(PoliceUser.police_user_id == int(target_officer)).scalar()
                    
                    # Update workload tracking
                    workload[overloaded_officer] -= 1
                    workload[target_officer] += 1
                    
                    # Remove from underloaded if they're now balanced
                    if workload[target_officer] >= avg_reports - 1:
                        underloaded.remove(target_officer)
                    
                    reassigned += 1
                    
                    print(f"🔄 Reassigned report {report.report_id} from officer {old_officer_id} to officer {target_officer}")
        
        if reassigned > 0:
            db.commit()
            print(f" Report workload balanced: {reassigned} reports reassigned across {len(officers)} officers")
            
            # Broadcast changes to keep clients synchronized
            try:
                from app.api.v1.ws import manager
                from app.core.websocket import manager as ws_manager
                ws_manager.broadcast({"type": "refresh_data", "entity": "report", "action": "reassigned"})
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast report reassignments: {broadcast_error}")
    
    except Exception as e:
        print(f"Error in report workload balancing: {e}")
        db.rollback()


def _balance_workload_and_reassign(db: Session):
    """Smart workload balancing across multiple officers"""
    try:
        from app.models.case import Case
        from app.models.police_user import PoliceUser
        from sqlalchemy import func
        
        # Get all active officers
        officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer'
        ).all()
        
        if len(officers) <= 1:
            return  # No balancing needed with 0 or 1 officer
        
        # Get current case counts per officer
        case_counts = db.query(
            Case.assigned_to_id,
            func.count(Case.case_id).label('active_cases')
        ).filter(
            Case.status.in_(['open', 'assigned', 'in_progress']),
            Case.assigned_to_id.isnot(None)
        ).group_by(Case.assigned_to_id).all()
        
        # Create workload dictionary
        workload = {str(officer.police_user_id): 0 for officer in officers}
        for officer_id, count in case_counts:
            workload[str(officer_id)] = count
        
        # Find overloaded and underloaded officers (aggressive balancing for equal distribution)
        avg_cases = sum(workload.values()) / len(workload)
        max_cases = max(workload.values()) if workload else 0
        min_cases = min(workload.values()) if workload else 0
        
        # Trigger balancing if there's any imbalance (difference of 1 or more)
        if max_cases - min_cases <= 0:
            return  # Already perfectly balanced
        
        overloaded = [oid for oid, count in workload.items() if count > min_cases]
        underloaded = [oid for oid, count in workload.items() if count < max_cases]
        
        if not overloaded or not underloaded:
            return  # No imbalance to fix
        
        # Reassign cases from overloaded to underloaded officers
        reassigned = 0
        for overloaded_officer in overloaded:
            # Get cases from overloaded officer (aggressive rebalancing)
            cases_to_reassign = db.query(Case).filter(
                Case.assigned_to_id == overloaded_officer,
                Case.status.in_(['assigned', 'open', 'in_progress']),  # Include more statuses
                Case.created_at >= datetime.now(timezone.utc) - timedelta(days=7)  # Include last 7 days
            ).order_by(Case.created_at.desc()).limit(5).all()  # Reassign up to 5 cases
            
            for case in cases_to_reassign:
                if underloaded:
                    # Find least loaded underloaded officer
                    target_officer = min(underloaded, key=lambda oid: workload[oid])
                    
                    # Reassign case
                    case.assigned_to_id = target_officer
                    case.status = 'open'
                    case.updated_at = datetime.now(timezone.utc)
                    
                    # Update workload tracking
                    workload[overloaded_officer] -= 1
                    workload[target_officer] += 1
                    
                    # Remove from underloaded if they're now balanced
                    if workload[target_officer] >= avg_cases - 1:
                        underloaded.remove(target_officer)
                    
                    reassigned += 1
                    
                    print(f"🔄 Reassigned case {case.case_number} from officer {overloaded_officer} to officer {target_officer}")
        
        if reassigned > 0:
            db.commit()
            print(f" Workload balanced: {reassigned} cases reassigned across {len(officers)} officers")
            
            # Broadcast changes to keep clients synchronized
            try:
                from app.api.v1.ws import manager
                background_tasks.add_task(
                    manager.broadcast,
                    {"type": "refresh_data", "entity": "case", "action": "reassigned"}
                )
            except Exception as broadcast_error:
                print(f"Warning: Could not broadcast case reassignments: {broadcast_error}")
    
    except Exception as e:
        print(f"Error in workload balancing: {e}")
        db.rollback()


def _handle_officer_case_finalization(db: Session, officer_id: str):
    """Reassign cases when an officer finalizes their current cases"""
    try:
        from app.models.case import Case
        from app.models.police_user import PoliceUser
        
        # Check if officer has any active cases
        active_cases = db.query(Case).filter(
            Case.assigned_to_id == officer_id,
            Case.status.in_(['open', 'assigned', 'in_progress'])
        ).count()
        
        if active_cases > 0:
            return  # Officer still has active cases
        
        # Find other active officers to reassign new cases to
        other_officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == 'officer',
            PoliceUser.police_user_id != officer_id
        ).all()
        
        if not other_officers:
            return  # No other officers available
        
        # Assign new unassigned cases to other officers
        unassigned_cases = db.query(Case).filter(
            Case.assigned_to_id.is_(None),
            Case.status == 'open'
        ).order_by(Case.created_at.asc()).limit(5).all()
        
        for case in unassigned_cases:
            # Assign to least loaded officer
            least_loaded = min(other_officers, key=lambda officer: 
                db.query(Case).filter(
                    Case.assigned_to_id == officer.police_user_id,
                    Case.status.in_(['open', 'assigned', 'in_progress'])
                ).count()
            )
            
            case.assigned_to_id = least_loaded.police_user_id
            case.status = 'open'
            case.updated_at = datetime.now(timezone.utc)
            
            print(f" Assigned unassigned case {case.case_number} to officer {least_loaded.police_user_id}")
        
        if unassigned_cases:
            db.commit()
            print(f" Redistributed {len(unassigned_cases)} unassigned cases after officer {officer_id} finalized all cases")
    
    except Exception as e:
        print(f"Error handling officer case finalization: {e}")
        db.rollback()

def _assign_officer_to_report_based_on_location(db: Session, report_lat: float, report_lon: float) -> Optional[int]:
    """Assign an officer to a flagged report based on station proximity and workload."""
    try:
        from app.models.station import Station
        from app.models.police_user import PoliceUser
        from app.models.report import Report
        from math import radians, cos, sin, asin, sqrt
        from sqlalchemy import func

        def calculate_distance(lat1, lon1, lat2, lon2):
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                return float('inf')
            lat1, lon1, lat2, lon2 = map(radians, map(float, [lat1, lon1, lat2, lon2]))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c

        stations = db.query(Station).filter(Station.is_active == True).all()
        if not stations:
            return None

        ranked_stations = sorted(stations, key=lambda s: calculate_distance(report_lat, report_lon, s.latitude, s.longitude))

        for station in ranked_stations:
            officers = db.query(PoliceUser).filter(
                PoliceUser.is_active == True,
                PoliceUser.role == 'officer',
                PoliceUser.station_id == station.station_id
            ).all()

            if officers:
                officer_ids = [o.police_user_id for o in officers]
                # Count assigned reports (not cases) for workload
                report_counts = db.query(Report.verified_by, func.count(Report.report_id)).filter(
                    Report.verified_by.in_(officer_ids),
                    Report.status.in_(['pending', 'under_review'])
                ).group_by(Report.verified_by).all()
                
                count_dict = dict(report_counts)
                selected_officer = min(officers, key=lambda o: count_dict.get(o.police_user_id, 0))
                return selected_officer.police_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error assigning officer to report: {e}")
        return None


def _assign_officer_to_case_based_on_location(db: Session, case_lat: float, case_lon: float) -> Optional[int]:
    try:
        from app.models.station import Station
        from app.models.police_user import PoliceUser
        from app.models.case import Case
        from math import radians, cos, sin, asin, sqrt
        from sqlalchemy import func
        import random

        def calculate_distance(lat1, lon1, lat2, lon2):
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                return float('inf')
            lat1, lon1, lat2, lon2 = map(radians, map(float, [lat1, lon1, lat2, lon2]))
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return 6371 * c

        stations = db.query(Station).filter(Station.is_active == True).all()
        if not stations:
            return None

        ranked_stations = sorted(stations, key=lambda s: calculate_distance(case_lat, case_lon, s.latitude, s.longitude))

        for station in ranked_stations:
            officers = db.query(PoliceUser).filter(
                PoliceUser.is_active == True,
                PoliceUser.role == 'officer',
                PoliceUser.station_id == station.station_id
            ).all()

            if officers:
                officer_ids = [o.police_user_id for o in officers]
                case_counts = db.query(Case.assigned_to_id, func.count(Case.case_id)).filter(
                    Case.assigned_to_id.in_(officer_ids),
                    Case.status != 'closed'
                ).group_by(Case.assigned_to_id).all()
                
                count_dict = dict(case_counts)
                
                # Get current case counts for all officers
                officer_workloads = []
                for officer in officers:
                    count = count_dict.get(officer.police_user_id, 0)
                    officer_workloads.append((officer, count))
                
                # Sort by workload (ascending) - officers with fewer cases first
                officer_workloads.sort(key=lambda x: x[1])
                
                # Get minimum workload
                min_workload = officer_workloads[0][1] if officer_workloads else 0
                
                # Filter officers with minimum workload (for fair distribution)
                least_loaded_officers = [off for off, count in officer_workloads if count == min_workload]
                
                # Randomly select from least loaded officers to ensure rotation
                selected_officer = random.choice(least_loaded_officers)
                
                print(f"🎯 Assigned case to officer {selected_officer.police_user_id} (workload: {min_workload}) from {len(least_loaded_officers)} eligible officers")
                
                return selected_officer.police_user_id
        
        return None
    except Exception as e:
        logger.error(f"Error assigning officer to case: {e}")
        return None

def _create_case_from_reports(db: Session, reports: List[Report]) -> Dict[str, int]:
    """Create a case from a cluster of reports"""
    stats = {'cases_created': 0, 'case_number': None}
    
    try:
        from app.models.case import Case, CaseReport
        case_reports_table = CaseReport.__table__
        
        report = reports[0]  # Use first report as reference
        case_count = db.query(Case).count()
        case_number = f"CASE-{datetime.now().year}-{case_count + 1:04d}"
        
        high_priority_count = sum(1 for r in reports if r.priority == 'high')
        priority = 'high' if high_priority_count >= 1 else 'medium'  # Single high priority report makes case high priority
        
        case_lat = sum(r.latitude for r in reports) / len(reports)
        case_lon = sum(r.longitude for r in reports) / len(reports)
        officer_id = _assign_officer_to_case_based_on_location(db, float(case_lat), float(case_lon))
        
        # Adjust title and description based on number of reports
        if len(reports) == 1:
            title = f"Incident Type {report.incident_type_id} case - Single Report"
            description = f"Auto-generated case from 1 verified report"
        else:
            title = f"Incident Type {report.incident_type_id} case - Multiple Reports"
            description = f"Auto-generated case from {len(reports)} verified reports"
        
        case = Case(
            case_id=uuid4(),
            case_number=case_number,
            title=title,
            description=description,
            incident_type_id=report.incident_type_id,
            priority=priority,
            status='open',
            assigned_to_id=officer_id,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            report_count=len(reports),
            location_id=report.location_id,
            latitude=case_lat,
            longitude=case_lon
        )
        
        db.add(case)
        db.flush()
        
        # Link reports to case
        for report in reports:
            db.execute(
                case_reports_table.insert().values(
                    case_id=case.case_id,
                    report_id=report.report_id,
                )
            )
        
        # Update report status to indicate they're in a case
        for report in reports:
            report.status = "verified"
        
        db.commit()
        stats['cases_created'] += 1
        stats['case_number'] = case_number
        
        # Trigger workload balancing after case creation to ensure fair distribution
        try:
            _continuous_workload_balancing(db)
        except Exception as e:
            print(f"Warning: Could not trigger continuous workload balancing: {e}")
        print(f"Created auto-case {case.case_number} with {len(reports)} reports")
        
        # Broadcast case creation to all connected clients for real-time updates
        try:
            import asyncio
            payload = {"type": "refresh_data", "entity": "case", "action": "created"}
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager.broadcast(payload))
            except RuntimeError:
                asyncio.run(manager.broadcast(payload))
        except Exception as e:
            print(f"Warning: Could not broadcast case creation: {e}")
        
        # Send email notifications for auto case creation
        try:
            from app.api.v1.notifications import create_role_notifications
            from app.models.police_user import PoliceUser
            
            # Notify supervisors and admins about auto case creation
            create_role_notifications(
                db=db,
                title=f"Auto-Generated Case: {case.case_number}",
                message=f"A new case has been automatically created from {len(reports)} verified reports. Case: {case.title}",
                notif_type="system",
                related_entity_type="case",
                related_entity_id=str(case.case_id),
                target_roles=["supervisor", "admin"],
                send_email=True
            )
            
            # Notify assigned officer if case was assigned
            if case.assigned_to_id:
                from app.api.v1.notifications import create_notification
                create_notification(
                    db=db,
                    police_user_id=case.assigned_to_id,
                    title=f"Case Assigned: {case.case_number}",
                    message=f"You have been assigned to auto-generated case: {case.title}",
                    notif_type="assignment",
                    related_entity_type="case",
                    related_entity_id=str(case.case_id),
                    send_email=True
                )
                
        except Exception as e:
            print(f"Failed to send email notifications for case {case.case_number}: {e}")
        
    except Exception as e:
        print(f"Error creating case from reports: {e}")
    
    return stats


def _create_auto_cases(db: Session) -> Dict[str, int]:
    """Automatically create/attach cases from verified reports without a time window.

    Policy:
    - If a compatible OPEN case exists, attach report to it.
    - Create a NEW case only when no compatible open/in-progress case exists
      (e.g., prior matching cases are closed).
    """
    
    stats = {'cases_created': 0}
    
    try:
        from app.models.case import Case, CaseReport
        from datetime import datetime, timezone
        case_reports_table = CaseReport.__table__
        
        # Get clustering parameters from system config
        from app.models.system_config import SystemConfig
        dbscan_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.epsilon'
        ).first()
        min_samples_config = db.query(SystemConfig).filter(
            SystemConfig.config_key == 'dbscan.min_samples'
        ).first()
        
        # Use configured values or defaults
        cluster_radius_meters = 500  # Default 500m for better incident grouping
        min_reports_threshold = 1   # Allow single reports to create cases
        
        if dbscan_config:
            cluster_radius_meters = dbscan_config.config_value.get('value', 500)
        if min_samples_config:
            min_reports_threshold = min_samples_config.config_value.get('value', 2)
        
        # Convert radius to kilometers for distance calculation
        cluster_radius_km = cluster_radius_meters / 1000.0
        
        # Strategy 1: attach to existing open cases first, then cluster/create new.
        village_clusters = {}
        verified_reports = db.query(Report).filter(
            Report.verification_status == 'verified',
            Report.status == 'verified',
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            )
        ).all()
        
        logger.info(f"Found {len(verified_reports)} verified reports available for case creation")

        # First pass: attach to existing open/in-progress compatible cases.
        reports_for_new_case_eval = []
        for report in verified_reports:
            attached = _try_add_to_existing_case(db, report, cluster_radius_km)
            if not attached:
                reports_for_new_case_eval.append(report)
        logger.info(
            "Auto-case attachment pass complete: attached=%s remaining_for_new=%s",
            len(verified_reports) - len(reports_for_new_case_eval),
            len(reports_for_new_case_eval),
        )
        
        # Group remaining reports by village and incident type.
        for report in reports_for_new_case_eval:
            if report.village_location_id:
                village_key = f"{report.village_location_id}_{report.incident_type_id}"
                if village_key not in village_clusters:
                    village_clusters[village_key] = []
                village_clusters[village_key].append(report)
        
        # Create cases for village-based clusters.
        for village_key, reports in village_clusters.items():
            if len(reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, reports)
                stats['cases_created'] += case_stats['cases_created']
                village_id, incident_type_id = village_key.split('_')
                logger.info(
                    f"Created ONE village-based case for {len(reports)} reports in village {village_id}, incident type {incident_type_id}"
                )
        
        # Strategy 2: Geographic clustering for reports without village assignment
        unassigned_reports = [r for r in reports_for_new_case_eval if not r.village_location_id]
        if len(unassigned_reports) >= min_reports_threshold:
            # Group by incident type for geographic clustering
            by_incident_type = {}
            for report in unassigned_reports:
                incident_type_id = report.incident_type_id
                if incident_type_id not in by_incident_type:
                    by_incident_type[incident_type_id] = []
                by_incident_type[incident_type_id].append(report)
            
            # Apply geographic clustering
            from math import radians, cos, sin, asin, sqrt
            
            def calculate_distance(lat1, lon1, lat2, lon2):
                lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                return 6371 * c
            
            for incident_type_id, type_reports in by_incident_type.items():
                if len(type_reports) < min_reports_threshold:
                    continue
                
                # Find geographic clusters
                processed = set()
                for report in type_reports:
                    if report.report_id in processed:
                        continue
                        
                    cluster = [report]
                    processed.add(report.report_id)
                    
                    for other_report in type_reports:
                        if other_report.report_id in processed:
                            continue
                            
                        distance = calculate_distance(
                            report.latitude, report.longitude,
                            other_report.latitude, other_report.longitude
                        )
                        
                        if distance <= cluster_radius_km:  # Use configured radius
                            cluster.append(other_report)
                            processed.add(other_report.report_id)
                    
                    # Create case if cluster has enough reports
                    if len(cluster) >= min_reports_threshold:
                        case_stats = _create_case_from_reports(db, cluster)
                        stats['cases_created'] += case_stats['cases_created']
                        logger.info(
                            f"Created ONE geo-clustered case for {len(cluster)} reports of incident type {incident_type_id} within {cluster_radius_meters}m"
                        )
        
        if stats['cases_created'] > 0:
            db.commit()
        return stats
        
    except Exception as e:
        logger.error(f"Auto-case creation error: {e}")
        return stats
        db.commit()


def _automatic_incident_consolidation(db: Session, report: Report):
    """
    Automatic incident consolidation for verified reports.
    Uses existing case creation system for same-incident grouping.
    """
    print(f"Starting automatic incident consolidation for verified report {report.report_id}")
    
    # Use the existing auto-case creation system that was already working
    # This will handle same-incident grouping and case creation
    try:
        # Call the existing auto-case creation function
        from app.core.report_priority import auto_create_cases_from_verified_reports
        
        # Create a list with just this report to trigger the existing logic
        result = auto_create_cases_from_verified_reports(db, [report])
        
        if result and result.get('cases_created', 0) > 0:
            print(f"Auto-created {result['cases_created']} cases for report {report.report_id}")
        else:
            print(f"No case created for report {report.report_id} - will be grouped later")
            
    except Exception as e:
        print(f"Auto-case creation failed for report {report.report_id}: {e}")
        # Don't fail the report creation if case creation fails


def _build_report_detail_response(report: Report, db: Session) -> ReportDetailResponse:
    """Build a ReportDetailResponse from a Report object."""
    # Get ML prediction
    ml_prediction = resolve_ml_prediction_for_report(report)
    trust_score = (
        float(ml_prediction.trust_score)
        if ml_prediction is not None and ml_prediction.trust_score is not None
        else None
    )
    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()
    trust_score, ml_prediction_label = _rule_adjusted_trust_label(
        report, trust_score, ml_prediction_label
    )
    community_votes = {"real": 0, "false": 0, "unknown": 0}
    user_vote = None
    if getattr(report, "feature_vector", None) and isinstance(report.feature_vector, dict):
        votes_dict = report.feature_vector.get("community_votes", {})
        for dict_device_id, v in votes_dict.items():
            if str(v) in community_votes:
                community_votes[str(v)] += 1
    trust_factors = _resolve_trust_factors(
        report,
        ml_prediction,
        evidence_count=len(getattr(report, "evidence_files", []) or []),
        community_votes=community_votes,
    )
    context_tags_list = getattr(report, "context_tags", None) or []

    # Get device metadata and trust score
    device_metadata = getattr(report.device, "metadata_json", {}) if report.device else {}
    device_trust_score = getattr(report.device, "device_trust_score", None) if report.device else None
    total_reports = getattr(report.device, "total_reports", None) if report.device else None
    trusted_reports = getattr(report.device, "trusted_reports", None) if report.device else None

    # Get incident location info
    incident_location_info = {}
    incident_source = "reporter_only"
    if report.evidence_files and len(report.evidence_files) > 0:
        # Check if any evidence has location data
        evidence_with_location = [ef for ef in report.evidence_files if ef.media_latitude and ef.media_longitude]
        if evidence_with_location:
            incident_source = "combined"
            # Use evidence location for incident location
            ef = evidence_with_location[0]
            try:
                from app.core.village_lookup import get_village_location_info
                incident_location_info = get_village_location_info(float(ef.media_latitude), float(ef.media_longitude))
            except Exception:
                pass
        else:
            incident_source = "reporter_only"
    else:
        incident_source = "reporter_only"
    
    # If no evidence location, use report location
    if not incident_location_info and report.latitude and report.longitude:
        try:
            from app.core.village_lookup import get_village_location_info
            incident_location_info = get_village_location_info(float(report.latitude), float(report.longitude))
        except Exception:
            pass

    # Build assignments list
    assignment_list = []
    if hasattr(report, 'assignments') and report.assignments:
        for assignment in report.assignments:
            assignment_list.append(AssignmentResponse(
                assignment_id=assignment.assignment_id,
                report_id=assignment.report_id,
                police_user_id=assignment.police_user_id,
                assigned_at=assignment.assigned_at,
                assigned_by=assignment.assigned_by,
                status=assignment.status,
                notes=assignment.notes,
                officer_name=getattr(assignment.police_user, 'full_name', None) if assignment.police_user else None,
                officer_badge=getattr(assignment.police_user, 'badge_number', None) if assignment.police_user else None,
                station_name=getattr(getattr(assignment.police_user, 'station', None), 'station_name', None) if assignment.police_user else None,
            ))

    # Build reviews list
    review_list = []
    if hasattr(report, 'police_reviews') and report.police_reviews:
        for review in report.police_reviews:
            reviewer_name = None
            if review.police_user:
                first_name = (getattr(review.police_user, "first_name", None) or "").strip()
                last_name = (getattr(review.police_user, "last_name", None) or "").strip()
                full_name = f"{first_name} {last_name}".strip()
                reviewer_name = full_name or getattr(review.police_user, "badge_number", None)
            review_list.append(ReviewResponse(
                review_id=review.review_id,
                report_id=review.report_id,
                police_user_id=review.police_user_id,
                decision=review.decision,
                review_note=review.review_note,
                reviewed_at=review.reviewed_at,
                reviewer_name=reviewer_name,
            ))

    return ReportDetailResponse(
        report_id=report.report_id,
        report_number=getattr(report, "report_number", None),
        device_id=report.device_id,
        incident_type_id=report.incident_type_id,
        description=report.description,
        latitude=report.latitude,
        longitude=report.longitude,
        gps_accuracy=getattr(report, "gps_accuracy", None),
        motion_level=getattr(report, "motion_level", None),
        movement_speed=getattr(report, "movement_speed", None),
        was_stationary=getattr(report, "was_stationary", None),
        reported_at=report.reported_at,
        rule_status=report.rule_status,
        priority=getattr(report, "priority", "medium"),
        status=report.status,
        verification_status=report.verification_status,
        village_location_id=report.village_location_id,
        village_name=getattr(report.village_location, "village_name", None) if report.village_location else None,
        cell_name=getattr(getattr(report.village_location, "parent", None), "village_name", None) if report.village_location and report.village_location.parent else None,
        sector_name=getattr(getattr(getattr(report.village_location, "parent", None), "parent", None), "village_name", None) if report.village_location and report.village_location.parent and report.village_location.parent.parent else None,
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        trust_score=float(trust_score) if trust_score is not None else None,
        trust_factors=trust_factors,
        ml_prediction_label=ml_prediction_label,
        context_tags=context_tags_list,
        is_flagged=getattr(report, "is_flagged", None),
        flag_reason=getattr(report, "flag_reason", None),
        ai_evidence_description=getattr(report, "ai_evidence_description", None),
        ai_verification_reason=getattr(report, "ai_verification_reason", None),
        decision_patterns=_extract_decision_patterns(getattr(report, "ai_verification_reason", None)),
        decision_pattern_explanations=_extract_decision_pattern_explanations(
            getattr(report, "ai_verification_reason", None)
        ),
        incident_latitude=float(report.latitude) if report.latitude is not None else None,
        incident_longitude=float(report.longitude) if report.longitude is not None else None,
        incident_location_source=incident_source,
        incident_village_name=incident_location_info.get("village_name") if incident_location_info else None,
        incident_cell_name=incident_location_info.get("cell_name") if incident_location_info else None,
        incident_sector_name=incident_location_info.get("sector_name") if incident_location_info else None,
        evidence_files=[
            EvidenceFileResponse(
                evidence_id=ef.evidence_id,
                report_id=ef.report_id,
                file_url=_absolute_evidence_url(getattr(ef, "file_url", None)) or "",
                file_type=ef.file_type,
                uploaded_at=ef.uploaded_at,
                media_latitude=float(ef.media_latitude) if ef.media_latitude is not None else None,
                media_longitude=float(ef.media_longitude) if ef.media_longitude is not None else None,
                blur_score=float(ef.blur_score) if getattr(ef, "blur_score", None) is not None else None,
                tamper_score=float(ef.tamper_score) if getattr(ef, "tamper_score", None) is not None else None,
                quality_label=ef.quality_label.value if ef.quality_label else None,
            )
            for ef in report.evidence_files
        ],
        assignments=assignment_list,
        reviews=review_list,
        community_votes=community_votes,
        user_vote=user_vote,
        metadata_json=device_metadata,
        device_trust_score=float(device_trust_score) if device_trust_score is not None else None,
        total_reports=total_reports,
        trusted_reports=trusted_reports,
        evidence_count=len(getattr(report, "evidence_files", []) or []),
        hotspot_id=getattr(report, "hotspot_id", None),
        hotspot_risk_level=getattr(report, "hotspot_risk_level", None),
        hotspot_incident_count=getattr(report, "hotspot_incident_count", None),
        hotspot_label=getattr(report, "hotspot_label", None),
        ml_predictions=[],
    )


def _build_report_response(report: Report, db: Session, request_device_id: Optional[str] = None) -> ReportResponse:
    """Build a ReportResponse from a Report object."""
    # Get ML prediction
    ml_prediction = resolve_ml_prediction_for_report(report)
    trust_score = (
        float(ml_prediction.trust_score)
        if ml_prediction is not None and ml_prediction.trust_score is not None
        else None
    )
    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()
    trust_score, ml_prediction_label = _rule_adjusted_trust_label(
        report, trust_score, ml_prediction_label
    )
    community_votes = {"real": 0, "false": 0, "unknown": 0}
    user_vote = None
    if getattr(report, "feature_vector", None) and isinstance(report.feature_vector, dict):
        votes_dict = report.feature_vector.get("community_votes", {})
        if isinstance(votes_dict, dict):
            for device_key, v in votes_dict.items():
                k = str(v)
                if k in community_votes:
                    community_votes[k] += 1
                if request_device_id and str(device_key) == str(request_device_id):
                    user_vote = k
    trust_factors = _resolve_trust_factors(
        report,
        ml_prediction,
        evidence_count=len(getattr(report, "evidence_files", []) or []),
        community_votes=community_votes,
    )
    
    # Get device metadata and stored device trust stats
    device_metadata = None
    device_trust_score = None
    total_reports = None
    trusted_reports = None
    
    if report.device:
        device_metadata = report.device.metadata_json or {}
        device_trust_score = (
            float(report.device.device_trust_score)
            if getattr(report.device, "device_trust_score", None) is not None
            else None
        )
        total_reports = getattr(report.device, "total_reports", None)
        trusted_reports = getattr(report.device, "trusted_reports", None)
    
    # Build evidence files response
    evidence_files_response = [
        EvidenceFileResponse(
            report_id=str(report.report_id),
            evidence_id=str(ef.evidence_id),
            file_url=ef.file_url,
            file_type=ef.file_type,
            file_size=ef.file_size,
            uploaded_at=ef.uploaded_at,
            media_latitude=float(ef.media_latitude) if ef.media_latitude is not None else None,
            media_longitude=float(ef.media_longitude) if ef.media_longitude is not None else None,
            blur_score=float(ef.blur_score) if getattr(ef, "blur_score", None) is not None else None,
            tamper_score=float(ef.tamper_score) if getattr(ef, "tamper_score", None) is not None else None,
            quality_label=ef.quality_label.value if ef.quality_label else None,
        )
        for ef in (report.evidence_files or [])
    ]
    
    return ReportResponse(
        report_id=str(report.report_id),
        report_number=report.report_number,
        title=None,  # Report model doesn't have title field
        description=report.description,
        incident_type_id=str(report.incident_type_id) if report.incident_type_id else None,
        incident_type=report.incident_type,
        status=report.status,
        verification_status=report.verification_status,
        rule_status=report.rule_status,
        reported_at=report.reported_at,
        village_location_id=str(report.village_location_id) if report.village_location_id else None,
        village_location=report.village_location,
        reporter_name=None,  # Report model doesn't have reporter_name field
        reporter_contact=None,  # Report model doesn't have reporter_contact field
        is_anonymous=True,  # Default to True since reports are from devices
        evidence_files=evidence_files_response,
        assignments=[],
        reviews=[],
        community_votes=community_votes,
        user_vote=user_vote,
        metadata_json=device_metadata,
        device_trust_score=float(device_trust_score) if device_trust_score is not None else None,
        total_reports=total_reports,
        trusted_reports=trusted_reports,
        trust_score=trust_score,
        trust_factors=trust_factors,
        ml_prediction_label=ml_prediction_label,
        ai_evidence_description=getattr(report, "ai_evidence_description", None),
        ai_verification_reason=getattr(report, "ai_verification_reason", None),
        decision_patterns=_extract_decision_patterns(getattr(report, "ai_verification_reason", None)),
        decision_pattern_explanations=_extract_decision_pattern_explanations(
            getattr(report, "ai_verification_reason", None)
        ),
        # Add missing required fields
        device_id=str(report.device_id),
        latitude=float(report.latitude) if report.latitude else None,
        longitude=float(report.longitude) if report.longitude else None,
        # Add fields needed by frontend reports table
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        village_name=report.village_location.location_name if report.village_location else None,
        # Add ML predictions array for frontend
        ml_predictions=[{
            'trust_score': float(trust_score) if trust_score is not None else None,
            'prediction_label': ml_prediction_label if ml_prediction_label else (ml_prediction.prediction_label if ml_prediction else None),
            'evaluated_at': ml_prediction.evaluated_at.isoformat() if ml_prediction and ml_prediction.evaluated_at else None
        }] if ml_prediction else [],
    )


