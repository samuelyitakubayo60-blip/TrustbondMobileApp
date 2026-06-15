import logging
import json
import threading
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
from app.models.station_coverage import StationCoverageCell
from app.schemas.report import (
    ReportCreate,
    ReportResponse,
    ReportDetailResponse,
    ReportListResponse,
    EvidenceFileResponse,
    EvidencePreview,
    AssignmentResponse,
    AssignCreate,
)
from app.models.police_user import PoliceUser
from app.models.local_leader import LocalLeader
from app.api.v1.leader_auth import get_optional_local_leader
from app.models.report_assignment import ReportAssignment
from app.models.ml_prediction import MLPrediction
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
from app.core.report_review import resolve_ml_prediction_for_report
from app.core.credibility_model import score_report_credibility, update_device_ml_aggregates, _json_safe
from app.core.report_credibility_summary import report_credibility_api_fields
from app.core.natural_language_scorer import analyze_description_quality
from app.core.audit import log_action
from app.core.hotspot_auto import (
    create_hotspots_from_reports,
    get_hotspot_params_from_db,
    get_hotspot_trust_min_from_db,
)
from app.core.village_lookup import get_village_location_id, get_village_location_info
from app.schemas.report import CommunityVoteRequest
from sqlalchemy import text, and_, or_, func, cast, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError

router = APIRouter(prefix="/reports", tags=["reports"])

logger = logging.getLogger(__name__)
_auto_case_realtime_lock = threading.Lock()
_LLM_CLIENT = None
_LLM_UNAVAILABLE = False
_LOCAL_NARRATOR = None
_LOCAL_NARRATOR_UNAVAILABLE = False


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
        max_nt = max(128, min(2048, int(getattr(settings, "llm_local_max_new_tokens", 768) or 768)))
        out = generator(prompt, max_new_tokens=max_nt, do_sample=True, temperature=0.5)
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
        # Without LLM/local model, preserve structured facts instead of a useless placeholder.
        return fallback
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
    return fallback


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
    deterministic_fallback: str = "",
) -> str:
    """Generate human narrative from structured model snapshot."""
    client = _get_llm_client()
    if not isinstance(snapshot, dict):
        return (deterministic_fallback or fallback_text or "").strip() or f"{text_kind.title()} narrative unavailable."

    try:
        snapshot_json = json.dumps(snapshot, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        snapshot_json = json.dumps(_json_safe(snapshot), ensure_ascii=True)
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
            return (deterministic_fallback or fallback_text or "").strip() or f"{text_kind.title()} narrative unavailable."
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
            return (deterministic_fallback or fallback_text or "").strip() or f"{text_kind.title()} narrative unavailable."
        return candidate
    except Exception as exc:
        logger.warning("Grounded narrative generation failed (%s): %s", text_kind, exc)
        return (deterministic_fallback or fallback_text or "").strip() or f"{text_kind.title()} narrative unavailable."


def warmup_narrative_models_on_startup() -> None:
    """
    Warm-up narrative components on startup.
    - Checks Groq/Gemini semantic API if enabled (no local embedding download).
    - Initializes LLM client and performs a minimal readiness call.
    """
    try:
        if settings.enable_semantic_match:
            from app.core.natural_language_scorer import warmup_report_semantic_llm

            warmup_report_semantic_llm()
    except Exception as exc:
        logger.warning("Semantic API warm-up failed: %s", exc)

    try:
        logger.info(
            "Narrative warm-up config: remote_model=%s, local_fallback=%s, local_model=%s",
            settings.llm_model,
            settings.llm_use_local_fallback,
            settings.llm_local_model,
        )
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
            logger.info(
                "Remote LLM unavailable; warming local narrative model: %s",
                settings.llm_local_model,
            )
            local_gen = _get_local_narrator()
            if local_gen is not None:
                _generate_with_local_narrator("Summarize: startup check", max_chars=64)
                logger.info(
                    "Local LLM narrative warm-up complete for model: %s",
                    settings.llm_local_model,
                )
            else:
                logger.info("LLM narrative warm-up skipped (no remote/local model available)")
    except Exception as exc:
        logger.warning("LLM narrative warm-up failed: %s", exc)


def _apply_post_pipeline_evidence_checks(
    report: Report,
    db: Session,
    *,
    description: str,
    out_of_boundary: bool = False,
) -> None:
    """Re-run evidence semantic checks when pipeline was invoked outside orchestrator."""
    if out_of_boundary:
        return

    from app.core.verification_orchestrator import apply_evidence_semantic_checks, apply_threshold_outcome

    apply_evidence_semantic_checks(
        db,
        report,
        description=description or "",
        skip_if_rejected=False,
    )
    # Always re-apply score-based status to ensure consistency
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    scorecard = fv.get("threshold_scorecard") if isinstance(fv.get("threshold_scorecard"), dict) else None
    if scorecard:
        apply_threshold_outcome(report, scorecard)


def _compact_snapshot_location(
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    gps_accuracy: Optional[Any] = None,
    location_label: Optional[str] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if location_label and str(location_label).strip():
        out["label"] = str(location_label).strip()[:280]
    if latitude is not None and longitude is not None:
        try:
            out["coordinates"] = f"{float(latitude):.5f}, {float(longitude):.5f}"
        except (TypeError, ValueError):
            pass
    if gps_accuracy is not None:
        try:
            out["gps_accuracy_m"] = float(gps_accuracy)
        except (TypeError, ValueError):
            pass
    return out


def _truncate_for_narrative(text: Optional[str], max_chars: int = 520) -> str:
    s = " ".join((text or "").strip().split())
    if len(s) <= max_chars:
        return s
    cut = s[: max_chars - 3].rsplit(" ", 1)[0].strip()
    return (cut + "…") if cut else s[: max_chars]


def _deterministic_ai_executive_summary(
    snapshot: Dict[str, Any],
    verification_status: str,
    *,
    pattern_codes: List[str],
    pattern_explanations: Optional[List[str]] = None,
) -> str:
    """
    Plain-language verdict when cloud LLMs are off or JSON narrative fails.
    Mirrors snapshot facts — no hallucinated evidence.
    """
    if not isinstance(snapshot, dict):
        return ""

    incident = (snapshot.get("incident_type") or "the incident type they selected").strip()
    fd = snapshot.get("final_decision") or {}
    status = verification_status.strip().lower() if verification_status else "pending"
    rule_rs = str(fd.get("rule_status") or "").lower().strip()

    tags = snapshot.get("context_tags") or []
    tags_s = ", ".join(str(t).strip() for t in tags[:10] if str(t).strip())

    desc = _truncate_for_narrative(snapshot.get("reporter_description"), 560)

    loc = snapshot.get("location") or {}
    loc_bits: List[str] = []
    if loc.get("label"):
        loc_bits.append(f"administrative area: {loc['label']}")
    if loc.get("coordinates"):
        loc_bits.append(f"GPS {loc['coordinates']}")
    if loc.get("gps_accuracy_m") is not None:
        try:
            loc_bits.append(f"GPS accuracy about {float(loc['gps_accuracy_m']):.0f} m")
        except (TypeError, ValueError):
            pass
    loc_sentence = ("Location: " + "; ".join(loc_bits) + ".") if loc_bits else ""

    evid = (snapshot.get("model_signals") or {}).get("evidence_ai") or {}
    ec = int(evid.get("evidence_count") or 0)
    if ec <= 0:
        media_line = (
            "No photo, video, or audio evidence was attached, so the decision leans on the written report, "
            "metadata, and automated checks."
        )
    else:
        media_line = (
            f"{ec} evidence file(s) were analyzed where possible; objects and quality signals still need to "
            f"agree with the narrative and incident type."
        )

    nl = (snapshot.get("model_signals") or {}).get("natural_language") or {}
    sem_bits: List[str] = []
    if nl.get("mismatch") is True:
        sem_bits.append(
            "semantic similarity between the description and the selected incident expectations is weak "
            "(possible context mismatch)."
        )
    elif isinstance(nl.get("description_incident_similarity"), (int, float)):
        try:
            dis = float(nl["description_incident_similarity"])
            if dis < 0.42:
                sem_bits.append(
                    "semantic similarity between the description and the selected incident expectations is weak "
                    "(possible context mismatch)."
                )
            else:
                sem_bits.append(
                    f"description vs incident-type similarity sits near {dis:.2f} on a 0–1 semantic scale."
                )
        except (TypeError, ValueError):
            pass

    dc = (snapshot.get("model_signals") or {}).get("description_credibility") or {}
    desc_length_line = ""
    if isinstance(dc, dict) and dc.get("word_count") is not None:
        wc = int(dc["word_count"])
        min_w = int(dc.get("min_recommended_words") or 15)
        if dc.get("short_description_rescue"):
            desc_length_line = (
                f"Description length: {wc} words (under {min_w} recommended) but wording matches "
                f"the incident type and attached evidence, so only a limited credibility penalty was applied."
            )
        elif wc < min_w:
            applied = dc.get("applied_penalty_points")
            pts = f" (−{applied} on credibility score)" if applied is not None else ""
            desc_length_line = (
                f"Description length: {wc} words (recommended {min_w}+); short text reduced credibility{pts}."
            )
        elif dc.get("length_adjustment") == "bonus":
            bonus = dc.get("length_points")
            bonus_txt = f" (+{bonus} credibility points)" if bonus is not None else ""
            desc_length_line = (
                f"Description length: {wc} words — sufficient detail improved credibility{bonus_txt}."
            )

    ts = fd.get("trust_score")
    label = fd.get("label")
    scoring: List[str] = []
    if ts is not None:
        try:
            scoring.append(f"automated credibility score ≈ {float(ts):.1f}/100")
        except (TypeError, ValueError):
            pass
    if label:
        scoring.append(f"model label {label}")
    scdig = snapshot.get("scorecard_digest") or {}
    if scdig.get("total_points") is not None:
        try:
            scoring.append(f"threshold scorecard total ≈ {float(scdig['total_points']):.1f}/100")
        except (TypeError, ValueError):
            pass
    if scdig.get("band"):
        band_s = str(scdig["band"]).replace("_", " ")
        scoring.append(f"scorecard band {band_s}")
    elif fd.get("threshold_band"):
        band_s = str(fd["threshold_band"]).replace("_", " ")
        scoring.append(f"scorecard band {band_s}")

    uni = snapshot.get("unified_validation_digest") or {}
    if uni.get("aggregated_score") is not None:
        try:
            scoring.append(f"unified model blend ≈ {float(uni['aggregated_score']):.1f}/100")
        except (TypeError, ValueError):
            pass

    trig = snapshot.get("rules") or {}
    flagged_rules = trig.get("triggered") if isinstance(trig.get("triggered"), list) else []
    prim = ""
    if flagged_rules:
        prim = str((flagged_rules[0] or {}).get("explanation") or "").strip()

    p1_parts = [
        f"The reporter submitted a {incident.lower()} report.",
    ]
    if desc:
        p1_parts.append(f"In their words: {desc}")
    elif not desc:
        p1_parts.append("They did not provide a usable description.")

    closing: List[str] = [loc_sentence, media_line]
    if desc_length_line:
        closing.append(desc_length_line)
    if sem_bits:
        closing.append(" ".join(sem_bits))
    if scoring:
        closing.append("Signals collected: " + "; ".join(scoring) + ".")
    if prim:
        closing.append(f"Primary automated flag motive: {prim}.")

    if status == "verified":
        conclusion = (
            "Summary verdict: Automated checks support treating this submission as credible for now, "
            "but policing policy and staffing still apply."
        )
    elif status == "rejected":
        reason = prim or _snapshot_rule_fallback_explanation(snapshot)
        conclusion = (
            "Summary verdict: Automated validation concludes this submission should not proceed as a trusted report "
            f"because {reason}"
        ).strip()
        if not reason.endswith("."):
            conclusion += "."
    else:
        whys = []
        for code in pattern_codes or []:
            if code == "LOW_TRUST_SCORE":
                whys.append("credibility stays below automatic confirmation thresholds")
            elif code == "CONTEXT_MISMATCH":
                whys.append("the wording does not line up cleanly with incident-type expectations")
            elif code in {"SHORT_DESCRIPTION", "SHORT_DESCRIPTION_PARTIAL"}:
                whys.append("the written description is shorter than recommended for full credibility credit")
            elif code == "SHORT_DESCRIPTION_RESCUED":
                whys.append(
                    "the description is short but still aligns with the incident type and evidence on file"
                )
            elif code == "RULE_FLAGGED":
                whys.append("rule checks requested manual scrutiny")
            elif code == "FINAL_PENDING_REVIEW":
                continue
            elif code.startswith("RULE_"):
                whys.append("rule engine emitted a cautious state")
        if not whys and pattern_explanations:
            whys.extend(
                exp.split(": ", 1)[-1].strip().rstrip(".")
                for exp in pattern_explanations[:3]
                if exp and ":" in exp
            )
        if not whys:
            whys.append("automated certainty is insufficient without human judgment")
        conclusion = (
            "Summary verdict: The system keeps this report open for officers because "
            + ", ".join(dict.fromkeys(whys))
            + "."
        )

    block_a = " ".join(p for p in p1_parts if p).strip()
    block_b = " ".join(s for s in closing if s)
    parts_out = [_truncate_for_narrative(block_a, 1200)]
    if block_b:
        parts_out.append(block_b[:1600])
    parts_out.append(conclusion[:900])
    return "\n\n".join(p.strip() for p in parts_out if p and p.strip())


def _snapshot_rule_fallback_explanation(snapshot: Dict[str, Any]) -> str:
    trig = snapshot.get("rules") or {}
    flagged = trig.get("triggered") if isinstance(trig.get("triggered"), list) else []
    if flagged:
        return str((flagged[0] or {}).get("explanation") or "policy thresholds failed").strip()
    return "policy or rule thresholds were not satisfied"


def _deterministic_ai_evidence_summary(snapshot: Dict[str, Any]) -> str:
    """Standalone evidence/context paragraph when narrative models are unavailable."""
    if not isinstance(snapshot, dict):
        return ""
    incident_raw = (snapshot.get("incident_type") or "").strip()
    incident = " ".join(incident_raw.split()).title() if incident_raw else "Incident"
    desc = _truncate_for_narrative(snapshot.get("reporter_description"), 520)
    tags = snapshot.get("context_tags") or []
    tags_s = ", ".join(str(t).strip() for t in tags[:10] if str(t).strip())

    evid = (snapshot.get("model_signals") or {}).get("evidence_ai") or {}
    ec = int(evid.get("evidence_count") or 0)

    paras: List[str] = [f"Evidence summary ({incident}):"]

    if ec <= 0:
        paras.append(
            "There is no uploaded media—only the textual report and contextual tags guided automated checks."
        )
    else:
        paras.append(f"{ec} file(s) underwent content checks (blur, authenticity cues, detected objects where applicable).")

    if desc:
        paras.append(f"Reporter narrative: {desc}")

    fd = snapshot.get("final_decision") or {}
    if fd.get("trust_score") is not None:
        try:
            paras.append(f"Integrated credibility sits near {float(fd['trust_score']):.1f}/100.")
        except (TypeError, ValueError):
            pass

    if tags_s:
        paras.append(f"Tags emphasized in screening: {tags_s}.")

    return "\n\n".join(paras)[:2000]


def _extract_evidence_per_file_summary(
    evidence_validations: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build a compact per-file record for narrative use: media_type, valid, score, objects."""
    out: List[Dict[str, Any]] = []
    for item in evidence_validations or []:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        raw_media = (
            summary.get("media_type")
            or (item or {}).get("file_type")
            or (item or {}).get("media_type")
            or "media"
        )
        # Normalise to a human label
        mt = str(raw_media).strip().lower()
        if mt.startswith("image") or mt == "photo":
            media_label = "photo"
        elif mt.startswith("video") or mt == "video":
            media_label = "video"
        elif mt.startswith("audio") or mt == "audio":
            media_label = "audio"
        else:
            media_label = "file"

        detected = [str(o).strip() for o in (summary.get("detected_objects") or []) if str(o).strip()]
        volo_score = validation.get("volo_overall_score")
        is_valid = validation.get("valid")
        out.append({
            "media_type": media_label,
            "valid": is_valid,
            "volo_score": round(float(volo_score), 1) if volo_score is not None else None,
            "detected_objects": detected[:8],
            "issues": (validation.get("issues") or [])[:4],
        })
    return out


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
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    gps_accuracy: Optional[Any] = None,
    location_label: Optional[str] = None,
    description_credibility: Optional[Dict[str, Any]] = None,
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

    scdig: Dict[str, Any] = {}
    if isinstance(scorecard, dict):
        tsp = scorecard.get("total_score")
        if tsp is not None:
            try:
                scdig["total_points"] = float(tsp)
            except (TypeError, ValueError):
                pass
        if scorecard.get("threshold_band"):
            scdig["band"] = scorecard.get("threshold_band")
        hgsc = scorecard.get("hard_gates")
        if isinstance(hgsc, list) and hgsc:
            scdig["hard_gates"] = list(hgsc)[:14]

    unidig: Dict[str, Any] = {}
    if isinstance(unified_validation, dict):
        agg = unified_validation.get("aggregated_score")
        if agg is not None:
            try:
                unidig["aggregated_score"] = float(agg)
            except (TypeError, ValueError):
                pass
        if unified_validation.get("trust_band"):
            unidig["trust_band"] = unified_validation.get("trust_band")

    loc_blob = _compact_snapshot_location(latitude, longitude, gps_accuracy, location_label)

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
                # Per-file details so narratives can mention media type and detection result
                "per_file": _extract_evidence_per_file_summary(evidence_validations),
            },
            "base": model_breakdown.get("base", {}),
            "description_credibility": (
                description_credibility if isinstance(description_credibility, dict) else {}
            ),
        },
        "evidence_count": int(evidence_count or 0),
        "evidence_file_count": evidence_file_count,
        "evidence_files": evidence_validations,
        "rules": {
            "triggered": rules_triggered,
            "hard_gates": hard_gates,
        },
        "scorecard": scorecard if isinstance(scorecard, dict) else {},
        "location": loc_blob,
        "scorecard_digest": scdig,
        "unified_validation_digest": unidig,
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
    verification_status: Optional[str] = None,
    rule_status: Optional[str] = None,
    is_flagged: Optional[bool] = None,
    flag_reason: Optional[str] = None,
    ml_prediction_label: Optional[str] = None,
    trust_score: Optional[float] = None,
    semantic_alignment: Optional[Dict[str, Any]] = None,
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    gps_accuracy: Optional[Any] = None,
    location_label: Optional[str] = None,
) -> str:
    """Evidence + narrative context; prefers plain-language deterministic summary when models are unavailable."""

    incident_label = (incident_type_name or "incident").strip() or "incident"
    desc_excerpt = (reporter_description or "").strip()
    desc_excerpt = " ".join(desc_excerpt.split())
    if len(desc_excerpt) > 180:
        desc_excerpt = f"{desc_excerpt[:177]}..."
    tags = [str(t).strip() for t in (context_tags or []) if str(t).strip()]
    tags_text = ", ".join(tags[:6]) if tags else None

    def _snap(ec: Optional[int]) -> Dict[str, Any]:
        ec_final = ec if ec is not None else len(evidence_validations or [])
        return _build_ai_analysis_snapshot(
            verification_status=verification_status or "pending",
            rule_status=rule_status or "unknown",
            is_flagged=bool(is_flagged) if is_flagged is not None else False,
            flag_reason=flag_reason,
            ml_prediction_label=ml_prediction_label,
            trust_score=trust_score,
            semantic_alignment=semantic_alignment,
            incident_type_name=incident_type_name,
            reporter_description=reporter_description,
            context_tags=context_tags,
            unified_validation=unified_validation,
            scorecard=scorecard,
            evidence_validations=evidence_validations,
            evidence_file_count=ec_final,
            latitude=latitude,
            longitude=longitude,
            gps_accuracy=gps_accuracy,
            location_label=location_label,
        )

    def _finalize(snapshot: Dict[str, Any], fallback_chunks: List[str], must_include: List[str]) -> str:
        # Evidence narrative is included in ai_verification_reason unified summary.
        return ""

    if not evidence_validations:
        media_types = [str(m).strip() for m in (evidence_media_types or []) if str(m).strip()]
        media_text = ", ".join(sorted(set(media_types))) if media_types else "photo/video/audio"
        if (evidence_file_count or 0) > 0:
            fb = [
                f"{evidence_file_count} evidence file(s) uploaded ({media_text}), detail trace missing for this revision.",
                "Screening rested on textual context, sensors, metadata, and aggregated trust signals.",
            ]
            snapshot = _snap(evidence_file_count)
            return _finalize(snapshot, fb, [incident_label, desc_excerpt, tags_text or "", media_text])
        fb = [
            "There are no uploads—only descriptive text anchors the authenticity review.",
            "That increases reliance on linguistic consistency checks and corroborating device metadata.",
        ]
        snapshot = _snap(0)
        return _finalize(snapshot, fb, [incident_label, desc_excerpt, tags_text or ""])

    media_types_lv: List[str] = []
    object_counter: Dict[str, int] = {}
    quality_scores: List[float] = []

    for item in evidence_validations:
        validation = (item or {}).get("validation") or {}
        summary = validation.get("analysis_summary") or {}
        advanced = validation.get("advanced_analysis") or {}

        media_type = summary.get("media_type") or advanced.get("media_type")
        if isinstance(media_type, str) and media_type.strip():
            media_types_lv.append(media_type.strip())

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
    object_text = ", ".join(obj for obj, _ in top_objects) if top_objects else "no strong object cues yet"
    avg_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else None
    media_text = ", ".join(sorted(set(media_types_lv))) if media_types_lv else "photo/video/audio"

    quality_note = ""
    if avg_quality is not None:
        quality_note = f"Average AI quality meter for uploads: {avg_quality:.2f}."

    fb = [
        f"{len(evidence_validations)} file(s) screened ({media_text}).",
        f"Salient automated detections leaned toward {object_text}. {quality_note}".strip(),
        "Investigators should reconcile these cues with the witness wording and map context.",
    ]
    snapshot = _snap(len(evidence_validations))
    return _finalize(snapshot, fb, [incident_label, object_text, media_text, desc_excerpt])


def _description_credibility_from_report(report: Any) -> Optional[Dict[str, Any]]:
    """Structured description length/semantic adjustment saved during credibility scoring."""
    fv = getattr(report, "feature_vector", None)
    if isinstance(fv, dict):
        meta = fv.get("description_credibility")
        if isinstance(meta, dict) and meta:
            return meta
    return None


def _text_only_reason_codes_from_report(report: Any) -> List[str]:
    fv = getattr(report, "feature_vector", None)
    if not isinstance(fv, dict):
        return []
    tov = fv.get("text_only_validation")
    if not isinstance(tov, dict):
        return []
    return [str(c) for c in (tov.get("reason_codes") or []) if str(c).strip()]


def _apply_description_credibility_patterns(
    description_credibility: Optional[Dict[str, Any]],
    add_pattern: Any,
) -> None:
    """Encode description_credibility into decision patterns shown during AI confirmation."""
    if not isinstance(description_credibility, dict) or not description_credibility:
        return
    wc = description_credibility.get("word_count")
    min_w = int(description_credibility.get("min_recommended_words") or 15)
    if wc is None:
        return
    try:
        wc_i = int(wc)
    except (TypeError, ValueError):
        return
    if description_credibility.get("short_description_rescue"):
        sem = description_credibility.get("semantic_similarity")
        sem_txt = f", semantic match {float(sem):.0f}%" if sem is not None else ""
        add_pattern(
            "SHORT_DESCRIPTION_RESCUED",
            f"only {wc_i} words (under {min_w} recommended) but description matches incident type "
            f"and evidence{sem_txt}; credibility penalty capped at 30%",
        )
        return
    if wc_i < min_w:
        applied = description_credibility.get("applied_penalty_points")
        pts = f" (−{applied} points on credibility score)" if applied is not None else ""
        add_pattern(
            "SHORT_DESCRIPTION",
            f"description has {wc_i} words (recommended {min_w}+); short text lowered credibility{pts}",
        )
        if description_credibility.get("partial_rescue") == "semantic_only":
            add_pattern(
                "SHORT_DESCRIPTION_PARTIAL",
                "text aligns with incident type but lacks evidence for full short-description credit",
            )
        return
    if description_credibility.get("length_adjustment") == "bonus":
        bonus = description_credibility.get("length_points")
        bonus_txt = f" (+{bonus} credibility points)" if bonus is not None else ""
        add_pattern(
            "DETAILED_DESCRIPTION",
            f"{wc_i} words provided additional description detail{bonus_txt}",
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
    description_credibility: Optional[Dict[str, Any]] = None,
    latitude: Optional[Any] = None,
    longitude: Optional[Any] = None,
    gps_accuracy: Optional[Any] = None,
    location_label: Optional[str] = None,
    text_only_reason_codes: Optional[List[str]] = None,
    evidence_validations: Optional[List[Dict[str, Any]]] = None,
    evidence_file_count: Optional[int] = None,
) -> str:
    """Plain-language unified screening summary for officers (no technical codes in text)."""
    status = (verification_status or "pending").lower()
    rule_status_norm = (rule_status or "").strip().lower()
    # Keep narrative final-state patterns aligned with enforcement.
    effective_status = "rejected" if rule_status_norm == "rejected" else status
    incident_label = (incident_type_name or "incident").strip() or "incident"
    pattern_codes: List[str] = []
    pattern_explanations: List[str] = []

    def _add_pattern(code: str, explanation: str) -> None:
        if code not in pattern_codes:
            pattern_codes.append(code)
            pattern_explanations.append(f"{code}: {explanation}")

    if flag_reason:
        raw_reason = str(flag_reason).strip().lower().replace("-", "_").replace(" ", "_")
        raw_reason = raw_reason.strip("_").rstrip("._")
        reason_map = {
            "description_appears_inconsistent_with_the_selected_incident_type": (
                "CONTEXT_MISMATCH",
                "report description does not align with incident-type expectations",
            ),
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
                "reviewer explicitly rejected the report",
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
        elif (
            "inconsistent" in str(flag_reason).lower()
            and "incident" in str(flag_reason).lower()
            and "description" in str(flag_reason).lower()
        ):
            _add_pattern(
                "CONTEXT_MISMATCH",
                "report description does not align with incident-type expectations",
            )
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
        if ml_prediction_label in {"fake", "suspicious"}:
            _add_pattern(
                "LOW_TRUST_SCORE",
                "automated credibility below auto-confirm threshold",
            )
        elif ml_prediction_label == "likely_real":
            _add_pattern(
                "HIGH_TRUST_SCORE",
                "ML credibility score supports authenticity",
            )

    if semantic_alignment:
        mismatch = semantic_alignment.get("mismatch")
        if mismatch is True:
            _add_pattern(
                "CONTEXT_MISMATCH",
                "semantic comparison shows mismatch between description, incident type, and evidence",
            )

    _apply_description_credibility_patterns(description_credibility, _add_pattern)

    if rule_status_norm == "rejected":
        _add_pattern(
            "RULE_REJECTION",
            "rule engine produced a hard rejection state",
        )
    elif rule_status_norm == "flagged":
        _add_pattern(
            "RULE_FLAGGED",
            "rule engine requested review",
        )
    elif rule_status_norm == "passed":
        _add_pattern(
            "RULES_PASSED",
            "rule checks passed without blocking violations",
        )

    if effective_status == "rejected":
        _add_pattern("FINAL_REJECTED", "final decision is rejected")
    elif effective_status in {"under_review", "pending"}:
        _add_pattern("FINAL_PENDING_REVIEW", "final decision is pending human review")
    elif effective_status == "verified":
        _add_pattern("FINAL_CONFIRMED", "final decision is confirmed")

    note = (reviewer_note or "").strip()
    if note:
        if effective_status == "verified":
            _add_pattern("HUMAN_CONFIRMED", "reviewer confirmed the report")
        elif effective_status == "rejected":
            _add_pattern("HUMAN_REJECTION", "reviewer rejected the report")

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
        evidence_validations=evidence_validations,
        evidence_file_count=evidence_file_count,
        latitude=latitude,
        longitude=longitude,
        gps_accuracy=gps_accuracy,
        location_label=location_label,
        description_credibility=description_credibility,
    )
    from app.core.report_verification_narrative import (
        build_officer_verification_brief,
        polish_officer_brief_with_llm,
    )

    officer_brief = build_officer_verification_brief(
        snapshot=snapshot,
        verification_status=effective_status,
        rule_status=rule_status_norm,
        is_flagged=is_flagged,
        pattern_codes=list(pattern_codes),
        pattern_explanations=list(pattern_explanations),
        flag_reason=flag_reason,
        text_only_reason_codes=text_only_reason_codes,
    )
    if note and "Officer note on file:" not in officer_brief:
        officer_brief += f"\n\nOfficer note on file: {note}"
    chosen = polish_officer_brief_with_llm(officer_brief)
    return chosen[:4000]


def _patch_stale_no_evidence_text(text: Optional[str], evidence_count: int) -> Optional[str]:
    """Replace stale 'no evidence' phrases when evidence files actually exist.

    This handles the race condition where the initial verification pipeline runs
    before evidence is uploaded (report JSON first, then multipart evidence),
    and the background re-verification either hasn't completed or failed.
    """
    if not text or evidence_count <= 0:
        return text
    import re as _re
    stale_phrases = [
        "No photo, video, or audio evidence was attached",
        "no evidence was attached",
        "no photo or video evidence",
        "no evidence uploaded",
    ]
    replacement = f"{evidence_count} evidence file(s) were uploaded and analyzed"
    patched = text
    for phrase in stale_phrases:
        patched = _re.sub(
            _re.escape(phrase),
            replacement,
            patched,
            count=1,
            flags=_re.IGNORECASE,
        )
    return patched


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


def _factors_with_reconciling_adjustment(
    factors: Any,
    total_score: Any,
) -> Dict[str, Any]:
    """
    When unified trust applies a post-sum penalty (e.g. insufficient contributing models),
    total_score can differ from the sum of factor rows. Inject a single adjustment row so
    the dashboard numbers reconcile without implying a bug.
    """
    if not isinstance(factors, dict):
        return {}
    try:
        total_f = float(total_score)
    except (TypeError, ValueError):
        return dict(factors)
    skip = {"aggregation_adjustment", "_aggregation_adjustment"}
    partial = 0.0
    for k, v in factors.items():
        if k in skip or not isinstance(v, dict):
            continue
        try:
            partial += float(v.get("points_awarded") or 0.0)
        except (TypeError, ValueError):
            pass
    adj = round(total_f - partial, 2)
    fac = dict(factors)
    if abs(adj) < 0.02:
        return fac
    fac["aggregation_adjustment"] = {
        "weight": 0.0,
        "max_points": 0.0,
        "signal": 0.0,
        "points_awarded": adj,
        "model": "policy",
        "is_valid": True,
        "detail": "Combines model-count penalties and other unified-aggregation deltas so the rows sum to Total score.",
    }
    return fac


def _headline_trust_score_from_factors(
    trust_factors: Optional[Dict[str, Any]],
    ml_fallback: Optional[float],
) -> Optional[float]:
    """Single number officers see: same as credibility breakdown total when scorecard exists."""
    if isinstance(trust_factors, dict):
        raw = trust_factors.get("total_score")
        if raw is not None:
            try:
                v = float(raw)
                if v == v:  # not NaN
                    return max(0.0, min(100.0, v))
            except (TypeError, ValueError):
                pass
    if ml_fallback is not None:
        try:
            v = float(ml_fallback)
            if v == v:
                return max(0.0, min(100.0, v))
        except (TypeError, ValueError):
            pass
    return None


def _trust_score_display_note(report: Report, *, headline_matches_scorecard: bool) -> Optional[str]:
    if headline_matches_scorecard:
        rs = (getattr(report, "rule_status", None) or "").strip().lower()
        flagged = bool(getattr(report, "is_flagged", False)) or rs == "flagged"
        if flagged:
            return (
                "This total matches the credibility breakdown below. "
                "The report is still flagged for human review—the ML label may read “suspicious” even when the scorecard is mid-range."
            )
        if rs == "rejected":
            return "This total matches the credibility breakdown; the report is rejected on rules or gates—see status and flag reason."
        return "This total matches the sum shown in the credibility breakdown (threshold scorecard)."
    return None


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
        reconciled_factors = _factors_with_reconciling_adjustment(
            scorecard.get("factors", {}),
            scorecard.get("total_score"),
        )
        out: Dict[str, Any] = {
            "scorecard_type": scorecard.get("scorecard_type"),
            "max_score": scorecard.get("max_score", 100.0),
            "total_score": scorecard.get("total_score"),
            "threshold_band": scorecard.get("threshold_band"),
            "hard_gates": scorecard.get("hard_gates", []),
            "factors": reconciled_factors,
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
        "factors": _factors_with_reconciling_adjustment(
            computed.get("factors", {}),
            computed.get("total_score"),
        ),
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


def _extract_verification_pipeline(report: Report) -> Optional[Dict[str, Any]]:
    """Extract 5-stage verification pipeline details from feature_vector for UI display."""
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}
    if not fv:
        return None

    pipeline_version = ""
    uv = fv.get("unified_validation")
    if isinstance(uv, dict):
        pipeline_version = uv.get("pipeline_version", "")

    stage2 = fv.get("stage_2_incident_match") if isinstance(fv.get("stage_2_incident_match"), dict) else None
    stage3 = fv.get("stage_3_description_quality") if isinstance(fv.get("stage_3_description_quality"), dict) else None
    stage4 = fv.get("stage_4_evidence_match") if isinstance(fv.get("stage_4_evidence_match"), dict) else None
    stage5 = fv.get("stage_5_trust_score") if isinstance(fv.get("stage_5_trust_score"), dict) else None

    if not any([stage2, stage3, stage4, stage5]):
        return None

    result: Dict[str, Any] = {
        "pipeline_version": pipeline_version or "v2_5stage",
        "pipeline_decision": fv.get("pipeline_decision"),
        "pipeline_rejection_stage": fv.get("pipeline_rejection_stage"),
        "pipeline_rejection_reason": fv.get("pipeline_rejection_reason"),
    }

    if stage2:
        result["incident_match"] = {
            "embedding_similarity": stage2.get("embedding_similarity"),
            "llm_match_score": stage2.get("llm_match_score"),
            "final_score": stage2.get("final_score"),
            "decision": stage2.get("decision"),
            "confidence": stage2.get("confidence"),
            "method": stage2.get("method"),
            "incident_type_name": stage2.get("incident_type_name"),
        }

    if stage3:
        result["description_quality"] = {
            "description_score": stage3.get("description_score"),
            "completeness": stage3.get("completeness"),
            "specificity": stage3.get("specificity"),
            "coherence": stage3.get("coherence"),
            "word_count": stage3.get("word_count"),
            "decision": stage3.get("decision"),
        }

    if stage4:
        result["evidence_match"] = {
            "semantic_similarity": stage4.get("semantic_similarity"),
            "support_level": stage4.get("support_level"),
            "final_score": stage4.get("final_score"),
            "decision": stage4.get("decision"),
        }

    if stage5:
        components = stage5.get("components", [])
        result["trust_score"] = {
            "trust_score": stage5.get("trust_score"),
            "trust_band": stage5.get("trust_band"),
            "decision": stage5.get("decision"),
            "components": [
                {
                    "name": c.get("name"),
                    "raw_score": c.get("raw_score"),
                    "weight": c.get("normalized_weight"),
                    "contribution": c.get("contribution"),
                    "available": c.get("available"),
                }
                for c in components
                if isinstance(c, dict)
            ],
        }

    # Evidence admissibility from stage 1
    ev = fv.get("evidence_validations")
    if isinstance(ev, list) and ev:
        result["evidence_admissibility"] = [
            {
                "admissibility_score": v.get("admissibility_score"),
                "is_admissible": v.get("is_admissible"),
                "file_type": v.get("file_type"),
                "rejection_reasons": v.get("rejection_reasons", []),
            }
            for v in ev
            if isinstance(v, dict)
        ]

    return result


def _rule_adjusted_trust_label(
    report: Report,
    trust_score: Optional[float],
    ml_prediction_label: Optional[str],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Align the categorical ML label with rule outcomes only.
    Numeric trust is not capped here—the API headline trust uses the credibility scorecard
    total so it matches the breakdown; the stored ML row keeps the model aggregate for audit.
    """
    score = trust_score
    label = (ml_prediction_label or "").strip().lower() or None
    rule_status = (getattr(report, "rule_status", None) or "").strip().lower()
    is_flagged = bool(getattr(report, "is_flagged", False))

    if rule_status == "rejected":
        label = "fake"
        return score, label

    if rule_status == "flagged" or is_flagged:
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


def _admin_hierarchy_from_village_location(village_loc: Optional[Any]) -> tuple:
    """
    sector_name, cell_name, village_name from a Location row (village) using ORM parents.
    Location model uses location_name (not village_name).
    """
    if not village_loc:
        return None, None, None
    village_name = getattr(village_loc, "location_name", None)
    cell_name = None
    sector_name = None
    parent = getattr(village_loc, "parent", None)
    if parent:
        if getattr(parent, "location_type", None) == "cell":
            cell_name = getattr(parent, "location_name", None)
            gp = getattr(parent, "parent", None)
            if gp and getattr(gp, "location_type", None) == "sector":
                sector_name = getattr(gp, "location_name", None)
        elif getattr(parent, "location_type", None) == "sector":
            sector_name = getattr(parent, "location_name", None)
    return sector_name, cell_name, village_name


def _human_location_chain_from_report(report: Report) -> Optional[str]:
    sec, cell, vill = _admin_hierarchy_from_village_location(getattr(report, "village_location", None))
    chain = [x for x in (sec, cell, vill) if x]
    return " > ".join(chain) if chain else None


def _station_covered_village_ids(db: Session, station: Optional[Station]) -> set[int]:
    if station is None:
        return set()
    covered_cell_ids = {
        int(row[0])
        for row in db.query(StationCoverageCell.cell_location_id)
        .filter(StationCoverageCell.station_id == station.station_id)
        .all()
    }
    # Map station's covered cells → villages under those cells.
    return {
        int(row[0])
        for row in db.query(Location.location_id)
        .filter(
            Location.location_type == "village",
            Location.parent_location_id.in_(covered_cell_ids),
        )
        .all()
    } if covered_cell_ids else set()


def _compute_threshold_scorecard(
    report: Report,
    *,
    ml_prediction: Optional[Any] = None,
    community_votes: Optional[Dict[str, int]] = None,
    unified_validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute a weighted 100-point threshold scorecard (text-only vs with evidence).

    When the 5-stage pipeline (v2) has run, uses Stage 5 trust score directly.
    Falls back to legacy pillar-based computation for older pipeline results.
    """
    fv = report.feature_vector if isinstance(getattr(report, "feature_vector", None), dict) else {}

    # ── NEW: Fast path for 5-stage pipeline results ──────────────────────────
    # When the new pipeline has already computed the trust score in Stage 5,
    # use it directly instead of re-computing from model breakdown.
    stage5 = fv.get("stage_5_trust_score") if isinstance(fv.get("stage_5_trust_score"), dict) else {}
    pipeline_version = (unified_validation or {}).get("pipeline_version", "") if isinstance(unified_validation, dict) else ""

    if stage5 and pipeline_version == "v2_5stage":
        trust_score = float(stage5.get("trust_score", 0.0))
        trust_band = str(stage5.get("trust_band", ""))
        components = stage5.get("components", [])

        hard_gates: List[str] = []
        flag_reason = (getattr(report, "flag_reason", None) or "").lower()
        # Only boundary violations are hard gates — score determines all else
        if "out_of_musanze_boundary" in flag_reason:
            hard_gates.append("LOCATION_OUT_OF_BOUNDARY")

        # Map trust band to threshold band
        if hard_gates:
            band = "hard_reject"
        elif trust_band == "high_confidence":
            band = "confirmed_candidate"
        elif trust_band == "medium_confidence":
            band = "under_review"
        elif trust_band == "low_confidence":
            band = "low_confidence"
        else:
            band = "low_confidence"

        # Build factors from Stage 5 components
        factors = {}
        for comp in components:
            if isinstance(comp, dict) and comp.get("available"):
                factors[comp.get("name", "unknown")] = {
                    "weight": comp.get("normalized_weight", 0),
                    "max_points": comp.get("normalized_weight", 0),
                    "signal": round(comp.get("raw_score", 0) / 100.0, 4),
                    "points_awarded": comp.get("contribution", 0),
                }

        # Pipeline-level rejection reasons
        pipeline_decision = fv.get("pipeline_decision", "")
        pipeline_rejection_stage = fv.get("pipeline_rejection_stage")
        evidence_validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []
        has_evidence = len(evidence_validations) > 0

        return {
            "scorecard_type": "pipeline_v2_5stage",
            "max_score": 100.0,
            "total_score": round(trust_score, 2),
            "threshold_band": band,
            "hard_gates": hard_gates,
            "factors": factors,
            "decision_source": "unified_validation",
            "pipeline_version": "v2_5stage",
            "pipeline_decision": pipeline_decision,
            "pipeline_rejection_stage": pipeline_rejection_stage,
            "evidence_all_failed": False,
            "evidence_mismatch_flag": False,
        }

    # ── Fallback to ML Prediction if no validation ───────────────────────────
    if ml_prediction is not None and not isinstance(unified_validation, dict):
        if hasattr(ml_prediction, "trust_score") and ml_prediction.trust_score is not None:
            ts = float(ml_prediction.trust_score)
            return {
                "scorecard_type": "legacy_ml_prediction",
                "max_score": 100.0,
                "total_score": round(ts, 2),
                "threshold_band": "confirmed_candidate" if ts >= 70.0 else ("under_review" if ts >= 40.0 else "low_confidence"),
                "hard_gates": [],
                "factors": {},
            }

    # ── Legacy path: pillar-based computation ────────────────────────────────
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

    # Hard gates — only boundary violations; score determines all else
    flag_reason = (getattr(report, "flag_reason", None) or "").lower()
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
        scorecard_type = "evidence_scorecard" if has_evidence else "text_only_scorecard"

        # ── Extract per-model sub-signals ─────────────────────────────────────────────
        nl_model   = model_breakdown.get("natural_language") or {}
        nl_meta    = nl_model.get("metadata") or {}
        nl_sem     = clamp01(float(nl_meta.get("semantic_similarity")  or 0.0) / 100.0)
        nl_desc    = clamp01(float(nl_meta.get("description_quality")  or 0.0) / 100.0)
        nl_valid   = bool(nl_model.get("is_valid", False))

        volo_model = model_breakdown.get("volo") or {}
        volo_meta  = volo_model.get("metadata") or {}
        volo_raw   = clamp01(float(volo_model.get("raw_score") or 0.0) / 100.0)
        volo_valid = bool(volo_model.get("is_valid", False))
        ctx_rel    = bool(volo_meta.get("context_relevant", False))

        tb_model   = model_breakdown.get("trustbond") or {}
        tb_raw     = clamp01(float(tb_model.get("raw_score") or 0.0) / 100.0)
        tb_valid   = bool(tb_model.get("is_valid", False))

        # Triple-alignment scores from the LLM semantic check (stored in feature_vector)
        sa = semantic if isinstance(semantic, dict) else {}
        desc_inc_sim  = sa.get("description_incident_similarity")
        inc_evid_sim  = sa.get("incident_evidence_similarity")
        triple_avail  = desc_inc_sim is not None
        desc_inc_sig  = clamp01(float(desc_inc_sim or 0.0) / 100.0) if triple_avail else None
        inc_evid_sig  = clamp01(float(inc_evid_sim  or 0.0) / 100.0) if inc_evid_sim is not None else None

        # ── 3-Pillar explicit formula ─────────────────────────────────────────────────
        # Points allocation differs by whether evidence was submitted:
        #
        #  WITH EVIDENCE   — sum-of-pillars can reach 110, capped at 100
        #    Pillar 1: Description Quality      20 pts
        #    Pillar 2: Incident Type Alignment  20 pts
        #    Pillar 3: Evidence Authenticity    28 pts  (Volo)
        #    Pillar 3b: Evid-Incident Alignment 12 pts  (triple LLM / Volo context)
        #    Pillar 4: Device / TrustBond       12 pts
        #    Community (bonus)                   8 pts
        #                               max = 100
        #
        #  TEXT-ONLY — no evidence, evidence pillars = 0, weights re-distributed
        #    Pillar 1: Description Quality      25 pts
        #    Pillar 2: Incident Type Alignment  35 pts
        #    Pillar 4: Device / TrustBond       25 pts
        #    Community (bonus)                  15 pts
        #                               max = 100

        if has_evidence:
            # Pillar 1 — Description quality
            p1_pts = round(nl_desc * 20.0, 2)
            # Pillar 2 — Incident type alignment
            # Blend NL semantic with triple-LLM alignment if available
            if triple_avail:
                p2_signal = 0.55 * nl_sem + 0.45 * desc_inc_sig
            else:
                p2_signal = nl_sem
            p2_pts = round(p2_signal * 20.0, 2)
            # Pillar 3a — Evidence authenticity (Volo score, already cross-val-adjusted)
            p3a_pts = round(volo_raw * 28.0, 2)
            # Pillar 3b — Evidence-incident alignment
            if inc_evid_sig is not None:
                p3b_signal = 0.6 * inc_evid_sig + 0.4 * (1.0 if ctx_rel else 0.0)
            elif ctx_rel:
                p3b_signal = 0.75
            elif volo_valid:
                p3b_signal = volo_raw * 0.6
            else:
                p3b_signal = 0.0
            p3b_pts = round(p3b_signal * 12.0, 2)
            # Pillar 4 — Device / TrustBond (user history, GPS quality, device trust)
            p4_pts = round(tb_raw * 12.0, 2)
            # Community bonus
            comm_pts = round(community_signal * 8.0, 2)
        else:
            # Text-only
            p1_pts  = round(nl_desc * 25.0, 2)
            p2_signal = (0.55 * nl_sem + 0.45 * desc_inc_sig) if triple_avail else nl_sem
            p2_pts  = round(p2_signal * 35.0, 2)
            p3a_pts = 0.0
            p3b_pts = 0.0
            p4_pts  = round(tb_raw * 25.0, 2)
            comm_pts = round(community_signal * 15.0, 2)

        total = round(min(100.0, max(0.0, p1_pts + p2_pts + p3a_pts + p3b_pts + p4_pts + comm_pts)), 2)

        # Build named factors for transparency
        factors: Dict[str, Any] = {}
        factors["description_quality"] = {
            "pillar": 1,
            "max_points": 20.0 if has_evidence else 25.0,
            "signal": round(nl_desc, 4),
            "points_awarded": p1_pts,
            "model": "natural_language",
            "is_valid": nl_valid,
        }
        factors["incident_type_alignment"] = {
            "pillar": 2,
            "max_points": 20.0 if has_evidence else 35.0,
            "signal": round(p2_signal, 4),
            "points_awarded": p2_pts,
            "model": "natural_language+triple_alignment",
            "is_valid": nl_valid,
            "triple_alignment_used": triple_avail,
        }
        if has_evidence:
            factors["evidence_authenticity"] = {
                "pillar": "3a",
                "max_points": 28.0,
                "signal": round(volo_raw, 4),
                "points_awarded": p3a_pts,
                "model": "volo",
                "is_valid": volo_valid,
                "context_relevant": ctx_rel,
            }
            factors["evidence_incident_alignment"] = {
                "pillar": "3b",
                "max_points": 12.0,
                "signal": round(p3b_signal, 4),
                "points_awarded": p3b_pts,
                "model": "volo+triple_alignment",
                "is_valid": volo_valid,
                "triple_alignment_used": inc_evid_sig is not None,
            }
        factors["device_trustbond"] = {
            "pillar": 4,
            "max_points": 12.0 if has_evidence else 25.0,
            "signal": round(tb_raw, 4),
            "points_awarded": p4_pts,
            "model": "trustbond",
            "is_valid": tb_valid,
        }
        factors["community_signal"] = {
            "pillar": "bonus",
            "max_points": 8.0 if has_evidence else 15.0,
            "signal": round(community_signal, 4),
            "points_awarded": comm_pts,
            "model": "community",
            "is_valid": True,
        }

        comm_points = comm_pts  # keep name consistent for penalty block below

        # ── Text-only penalties ───────────────────────────────────────────────────────
        if not has_evidence:
            text_valid = bool(text_only.get("valid", True))
            quality_band = str(text_only.get("quality_band") or "").strip().lower()
            reason_codes = {
                str(code).strip().upper()
                for code in (text_only.get("reason_codes") or [])
                if str(code).strip()
            }
            semantic_mismatch = bool(semantic.get("mismatch")) if isinstance(semantic, dict) else False
            flag_reason_upper = (flag_reason or "").upper()
            has_text_mismatch_flag = (
                semantic_mismatch
                or "INCIDENT_TEXT_MISMATCH" in reason_codes
                or "GIBBERISH" in reason_codes
            )
            if not text_valid or quality_band == "reject_quality":
                total = min(total, 45.0)
            elif quality_band == "review_quality":
                total = min(total, 65.0)
            if has_text_mismatch_flag:
                total = min(total, 49.0)

        # ── Evidence mismatch penalties ───────────────────────────────────────────────
        # When evidence was uploaded but none of it matches the incident type,
        # this is a stronger signal than text mismatch — cap and force rejection.
        evidence_all_failed = False
        evidence_mismatch_flag = False
        if has_evidence and evidence_validations:
            failed_count = sum(
                1 for ev in evidence_validations
                if isinstance((ev or {}).get("validation"), dict)
                and (ev or {}).get("validation", {}).get("valid") is False
            )
            evidence_all_failed = (failed_count == len(evidence_validations))

        flag_reason_upper = (flag_reason or "").upper()
        evidence_mismatch_flag = any(
            p in flag_reason_upper
            for p in ("EVIDENCE_INCIDENT", "DESCRIPTION_EVIDENCE", "INCIDENT_MISMATCH",
                      "EVIDENCE_NOT_RELEVANT")
        )

        # Evidence failure is already factored into the score through component weights.
        # No hard cap — score determines final status.

        if hard_gates:
            band = "hard_reject"
        elif not has_evidence:
            if total >= 70.0:
                band = "confirmed_candidate"
            elif total >= 40.0:
                band = "under_review"
            else:
                band = "low_confidence"
        else:
            if total >= 70.0:
                band = "confirmed_candidate"
            elif total >= 40.0:
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
            "evidence_all_failed": evidence_all_failed,
            "evidence_mismatch_flag": evidence_mismatch_flag,
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
            "max_points": weight,
            "signal": round(signal, 4),
            "points_awarded": points,
        }
    total = round(min(100.0, max(0.0, total)), 2)

    if hard_gates:
        band = "hard_reject"
    elif not has_evidence:
        if total >= 70.0:
            band = "confirmed_candidate"
        elif total >= 40.0:
            band = "under_review"
        else:
            band = "low_confidence"
    else:
        if total >= 70.0:
            band = "confirmed_candidate"
        elif total >= 40.0:
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
    """Apply scorecard thresholds (delegates to verification_orchestrator)."""
    from app.core.verification_orchestrator import apply_threshold_outcome

    apply_threshold_outcome(report, scorecard)


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


def _friendly_rule_rejection_message(flag_reason: Optional[str]) -> str:
    reason = (flag_reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    if any(
        key in reason
        for key in (
            "incident_text_mismatch",
            "gibberish",
            "unclear_description",
            "text_only_validation_failed",
        )
    ):
        return (
            "Report rejected: the description appears unclear or non-meaningful for the selected incident type. "
            "Please rewrite using clear words: what happened, where, when, who was involved, and any visible facts."
        )
    if "duplicate" in reason:
        return "Report rejected: this appears to duplicate an existing incident submission."
    if "out_of_musanze_boundary" in reason or "boundary" in reason:
        return "Report rejected: the reported location is outside the supported operational area."
    if "tamper" in reason:
        return "Report rejected: evidence integrity checks indicate possible tampering."
    return "Report rejected by rule-based validation."


def _process_report_background(
    report_id: str,
    device_id: str,
    evidence_count: int,
    evidence_metadata_list: List[dict],
):
    """Background re-run of citizen verification (same orchestrator as submit)."""
    from app.core.verification_orchestrator import run_citizen_verification_pipeline

    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.report_id == report_id).first()
        device = db.query(Device).filter(Device.device_id == device_id).first()
        if not report or not device:
            logger.error("Background verification: report %s or device %s not found", report_id, device_id)
            return

        if getattr(device, "is_banned", False):
            report.rule_status = "rejected"
            report.verification_status = "rejected"
            report.status = "rejected"
            report.is_flagged = True
            report.flag_reason = "device_banned"
            db.commit()
            return

        evidence_files = (
            db.query(EvidenceFile).filter(EvidenceFile.report_id == report.report_id).all()
        )
        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        validations = fv.get("evidence_validations") if isinstance(fv.get("evidence_validations"), list) else []

        run_citizen_verification_pipeline(
            db,
            report,
            device,
            evidence_files=evidence_files,
            evidence_validations=validations,
            evidence_metadata_list=evidence_metadata_list,
            compute_scorecard_fn=_compute_threshold_scorecard,
        )

        try:
            if report.status not in ("rejected",):
                create_hotspots_from_reports(db, [report])
        except Exception as exc:
            logger.error("Hotspot creation failed for report %s: %s", report_id, exc)

        db.commit()
        try:
            manager.broadcast({"type": "refresh_data", "entity": "report", "action": "processed"})
        except Exception as exc:
            logger.warning("Broadcast failed for report %s: %s", report_id, exc)
    except Exception as exc:
        logger.error("Background verification error for report %s: %s", report_id, exc)
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


def _absolute_evidence_url(raw: str | None) -> str | None:
    """
    Backward-compatible evidence URL resolver used by response builders.
    Keep remote URLs as-is, normalize local paths, and avoid NameError crashes.
    """
    return _normalize_evidence_file_url(raw)

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


def _scalar_float(value: Any) -> Optional[float]:
    """Convert numpy / Decimal scalars to plain float for PostgreSQL bind params (avoids np.float64 → invalid SQL)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    analysis["blur_score"] = _scalar_float(analysis.get("blur_score"))
    analysis["tamper_score"] = _scalar_float(analysis.get("tamper_score"))
    if analysis.get("volo_confidence") is not None:
        analysis["volo_confidence"] = _scalar_float(analysis.get("volo_confidence"))
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
            time_window_hours=max(int(tw), 8760),
            min_incidents=mi,
            radius_meters=rm,
            trust_min=trust_min,
            analyze_all_reports=True,
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
                notif_type="hotspot",
                related_entity_type="hotspot",
                related_entity_id=str(latest_hotspot.hotspot_id) if created == 1 and latest_hotspot else None,
                target_roles=["admin", "supervisor"],
                send_email=True  # Enable email notifications for hotspots
            )

            # Notify officers at stations covering hotspot areas
            try:
                from app.core.station_assignment import resolve_station_id
                recent_hotspots = db.query(Hotspot).order_by(Hotspot.detected_at.desc()).limit(created).all()
                notified_stations = set()
                for hs in recent_hotspots:
                    lat = float(hs.center_lat) if hs.center_lat else None
                    lon = float(hs.center_long) if hs.center_long else None
                    if lat is None or lon is None:
                        continue
                    sid = resolve_station_id(db, latitude=lat, longitude=lon)
                    if sid and sid not in notified_stations:
                        notified_stations.add(sid)
                        create_role_notifications(
                            db,
                            title="New Cluster Detected in Your Area",
                            message=f"A new incident cluster with {hs.incident_count} reports has been detected near your station area. Please review the Safety Map.",
                            notif_type="hotspot",
                            related_entity_type="hotspot",
                            related_entity_id=str(hs.hotspot_id),
                            target_roles=["officer"],
                            target_station_id=sid,
                            send_email=True,
                        )
            except Exception as e:
                print(f"Failed to notify station officers about hotspots: {e}")
        db.commit()
    except Exception as e:
        print(f"Error in background hotspot creation: {e}")
        db.rollback()
    finally:
        db.close()


def run_auto_case_realtime():
    """Background task to run case auto-linking/creation after live report changes."""
    if not _auto_case_realtime_lock.acquire(blocking=False):
        logger.info("Skipping overlapping realtime auto-case run")
        return

    db = SessionLocal()
    try:
        case_stats = _create_auto_cases(db)
        if case_stats.get("cases_created", 0) > 0:
            logger.info(
                "Realtime auto-case run: created %s case(s)",
                case_stats["cases_created"],
            )
    except Exception as e:
        logger.error("Error in realtime auto-case run: %s", e)
        db.rollback()
    finally:
        db.close()
        _auto_case_realtime_lock.release()


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
    """Generate next report number RPT-YYYY-NNNN using advisory lock (concurrent-safe)."""
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"RPT-{year}-"
    try:
        # Use advisory lock to serialize report number generation
        db.execute(text("SELECT pg_advisory_xact_lock(42)"))
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
    except Exception:
        # Fallback: use uuid suffix to avoid collisions
        import uuid
        fast_suffix = uuid.uuid4().hex[:6].upper()
        return f"{prefix}{fast_suffix}"

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
    submitting_leader: Annotated[Optional[LocalLeader], Depends(get_optional_local_leader)] = None,
):
    """Create a new report."""
    """Submit a new incident report. Device can be identified by device_id or device_hash (find-or-create)."""
    device = None
    if report_data.device_id:
        device = db.query(Device).filter(Device.device_id == report_data.device_id).first()
        if not device:
            if not report_data.device_hash:
                report_data.device_hash = str(report_data.device_id)

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
                device_id=report_data.device_id if report_data.device_id else uuid4(),
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

        if not village_id or not village_info:
            out_of_boundary = True
            out_of_boundary_reason = (
                f"out_of_musanze_boundary: ({lat_f:.4f}, {lon_f:.4f})"
            )

        district_name = ""
        if village_info:
            district_name = (village_info.get("district_name") or "").strip().lower()
        if district_name and district_name != "musanze":
            out_of_boundary = True
            out_of_boundary_reason = f"out_of_musanze_boundary: district={district_name}"
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

    if submitting_leader is not None:
        if out_of_boundary or village_id is None:
            raise HTTPException(
                status_code=400,
                detail="Leader submissions must use a GPS location inside a recognized village in your coverage area.",
            )
        from app.core.leader_workflow import leader_covered_village_ids

        if int(village_id) not in leader_covered_village_ids(db, submitting_leader.local_leader_id):
            raise HTTPException(
                status_code=403,
                detail="This location is outside your assigned village or cell.",
            )

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
        is_media = file_type_lower in (
            "photo",
            "video",
            "audio",
            "image/jpeg",
            "image/png",
            "image/jpg",
            "image/webp",
            "video/mp4",
            "video/mov",
            "video/quicktime",
            "video/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp3",
            "audio/aac",
            "audio/ogg",
        ) or file_type_lower.startswith(("image/", "video/", "audio/"))

        if is_media:
            from app.core.verification_orchestrator import pending_evidence_validation

            blur_score = 0.0
            tamper_score = 0.0
            quality_label = "pending"
            evidence_validations.append(
                {
                    "evidence_url": normalized_url,
                    "validation": pending_evidence_validation(),
                }
            )
        
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

    if out_of_boundary:
        report.rule_status = "rejected"
        report.status = "rejected"
        report.verification_status = "rejected"
        report.is_flagged = True
        report.flag_reason = out_of_boundary_reason or "out_of_musanze_boundary"

        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        fv["boundary_status"] = "out_of_musanze"
        fv["excluded_from_clustering"] = True
        fv["boundary_reason"] = report.flag_reason
        report.feature_vector = _json_safe(fv)

    # Note: submission-guidance (mobile guidance) has been removed from the product.
    # For text-only reports we keep the existing pipeline and record a lightweight NL analysis.
    # Police no longer review reports directly — AI + local leader are the verification gates.
    # Local leader submissions skip server-side NL/semantic/ML — mobile gates already ran on device.
    if submitting_leader is None and not evidence_metadata_list:
        try:
            incident_type_row = (
                db.query(IncidentType)
                .filter(IncidentType.incident_type_id == report.incident_type_id)
                .first()
            )
            type_name = getattr(incident_type_row, "type_name", "") or "unknown"
            type_desc = getattr(incident_type_row, "description", "") or ""
            nl = analyze_description_quality(
                report_data.description or report.description or "",
                type_name,
                type_desc,
            )
            from app.core.verification_orchestrator import build_text_only_validation_from_nl

            fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
            fv["text_only_nl"] = {
                "overall_score": float(getattr(nl, "overall_score", 0.0) or 0.0),
                "confidence": float(getattr(nl, "confidence", 0.0) or 0.0),
                "semantic_similarity": float(getattr(nl, "semantic_similarity_score", 0.0) or 0.0),
                "description_quality": float(getattr(nl, "description_quality_score", 0.0) or 0.0),
            }
            fv["text_only_validation"] = build_text_only_validation_from_nl(nl)
            report.feature_vector = _json_safe(fv)
        except Exception as e:
            logger.warning(f"Text-only NL analysis failed for report {report.report_id}: {e}")

    # Persist evidence validation summary on the report for auditability
    try:
        fv = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        if evidence_validations:
            fv["evidence_validations"] = evidence_validations
        report.feature_vector = _json_safe(fv)
    except Exception:
        pass

    # === Verification: leader = mobile basics only; citizens = full AI/rules pipeline ===
    evidence_count = len(evidence_metadata_list)
    try:
        if submitting_leader is not None:
            from app.core.leader_workflow import apply_leader_submission_verification

            apply_leader_submission_verification(
                report, db, evidence_count=evidence_count
            )
        if submitting_leader is None:
            from app.core.report_priority import apply_anti_fraud_rules
            from app.core.verification_orchestrator import run_citizen_verification_pipeline

            # Hard reject before full pipeline (invalid coords / type / speed)
            pre_rule_status, pre_flagged, pre_reason = apply_anti_fraud_rules(
                report, evidence_count, db
            )
            if pre_rule_status == "rejected":
                db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "RULE_BASED_REJECTION",
                        "message": _friendly_rule_rejection_message(pre_reason),
                        "flag_reason": pre_reason or "anti_fraud_rules_violation",
                        "rule_status": pre_rule_status,
                    },
                )

            def _compose_narratives_create(**kwargs):
                r = kwargs["report"]
                uv = kwargs["unified_validation"]
                sc = kwargs["scorecard"]
                mp = kwargs["ml_prediction"]
                ai_ts = kwargs["ai_trust_score"]
                ai_lbl = kwargs["ai_label"]
                ev = kwargs["evidence_validations"]
                # Use the real uploaded evidence file count when available (not just validation rows),
                # so AI narratives and dashboard evidence summaries never say "no evidence" when files exist.
                evidence_files_all = list(getattr(r, "evidence_files", []) or [])
                ec_final = len(evidence_files_all) if evidence_files_all else len(ev or [])
                sem = (
                    r.feature_vector.get("semantic_alignment")
                    if isinstance(r.feature_vector, dict)
                    else None
                )
                r.ai_verification_reason = _compose_ai_verification_reason(
                    verification_status=r.verification_status,
                    rule_status=r.rule_status,
                    is_flagged=r.is_flagged,
                    flag_reason=r.flag_reason,
                    ml_prediction_label=ai_lbl,
                    trust_score=ai_ts,
                    semantic_alignment=sem if isinstance(sem, dict) else None,
                    incident_type_name=getattr(getattr(r, "incident_type", None), "type_name", None),
                    reporter_description=r.description,
                    context_tags=list(getattr(r, "context_tags", None) or []),
                    unified_validation=uv,
                    scorecard=sc,
                    evidence_validations=ev,
                    evidence_file_count=ec_final,
                    latitude=getattr(r, "latitude", None),
                    longitude=getattr(r, "longitude", None),
                    gps_accuracy=getattr(r, "gps_accuracy", None),
                    location_label=_human_location_chain_from_report(r),
                    description_credibility=_description_credibility_from_report(r),
                    text_only_reason_codes=_text_only_reason_codes_from_report(r),
                )
                r.ai_evidence_description = None
                snapshot = _build_ai_analysis_snapshot(
                    verification_status=r.verification_status,
                    rule_status=r.rule_status,
                    is_flagged=r.is_flagged,
                    flag_reason=r.flag_reason,
                    ml_prediction_label=ai_lbl,
                    trust_score=ai_ts,
                    semantic_alignment=sem if isinstance(sem, dict) else None,
                    incident_type_name=getattr(getattr(r, "incident_type", None), "type_name", None),
                    reporter_description=r.description,
                    context_tags=list(getattr(r, "context_tags", None) or []),
                    unified_validation=uv,
                    scorecard=sc,
                    evidence_validations=ev,
                    evidence_file_count=ec_final,
                    latitude=getattr(r, "latitude", None),
                    longitude=getattr(r, "longitude", None),
                    gps_accuracy=getattr(r, "gps_accuracy", None),
                    location_label=_human_location_chain_from_report(r),
                    description_credibility=_description_credibility_from_report(r),
                )
                _persist_ai_analysis_snapshot(r, snapshot)

            # Flush so evidence rows are visible to queries and relationships
            db.flush()
            evidence_files_for_pipeline = (
                db.query(EvidenceFile)
                .filter(EvidenceFile.report_id == report.report_id)
                .all()
            )
            pipeline_result = run_citizen_verification_pipeline(
                db,
                report,
                device,
                evidence_files=evidence_files_for_pipeline,
                evidence_validations=evidence_validations,
                evidence_metadata_list=evidence_metadata_list,
                compute_scorecard_fn=_compute_threshold_scorecard,
                compose_narratives_fn=_compose_narratives_create,
                skip_if_out_of_boundary=out_of_boundary,
            )
            unified_validation_data = pipeline_result.unified_validation
            scorecard = pipeline_result.scorecard
            ml_prediction_tmp = pipeline_result.ml_prediction
            ai_trust_score = pipeline_result.ai_trust_score
            ai_label = pipeline_result.ai_label
            _apply_post_pipeline_evidence_checks(
                report,
                db,
                description=report_data.description or report.description or "",
                out_of_boundary=out_of_boundary,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "AI-enhanced rules pipeline failed for report %s (unified validation required; no TrustBond-only fallback)",
            report.report_id,
        )
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Report verification could not be completed. Please try again shortly.",
        ) from e

    # Persist everything before responding
    try:
        if submitting_leader is not None:
            now_ll = datetime.now(timezone.utc)
            report.submitted_by_local_leader_id = submitting_leader.local_leader_id
            report.leader_verification_status = "confirmed"
            report.leader_verified_by = submitting_leader.local_leader_id
            report.leader_verified_at = now_ll
        db.commit()
        db.refresh(report)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Report already exists")
    except OperationalError as e:
        db.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if "statement timeout" in msg or "querycanceled" in msg:
            # Idempotency safety: mobile may retry with the same report_id after a timeout.
            # If insert actually made it through and only response path timed out, return it.
            existing_after_timeout = (
                db.query(Report).filter(Report.report_id == incoming_report_id).first()
            )
            if existing_after_timeout is not None:
                return _build_report_detail_response(existing_after_timeout, db, for_police_viewer=False)
            raise HTTPException(
                status_code=503,
                detail="Database is busy processing this report. Please retry.",
            )
        raise HTTPException(status_code=500, detail=f"Failed to save report: {e}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save report: {e}")

    if submitting_leader is None and report.village_location_id is not None:
        from app.core.leader_notifications import notify_local_leaders_needs_verification_task

        ai_verified = report.verification_status == "verified" and report.status == "verified"
        has_evidence = bool(
            getattr(report, "evidence_files", None)
            or (
                isinstance(report.feature_vector, dict)
                and report.feature_vector.get("evidence_validations")
            )
        )

        if ai_verified:
            # AI (with or without evidence) is confident — treat as equivalent to leader verification.
            # No human gate needed; set leader_verification_status to confirmed automatically.
            report.leader_verification_status = "confirmed"
            try:
                db.commit()
            except Exception:
                db.rollback()
        else:
            # Only notify leader when AI flagged the report for human review (under_review).
            # AI-rejected reports must NOT reach the leader inbox at all.
            ai_rejected = (
                report.verification_status == "rejected"
                or report.rule_status == "rejected"
            )
            if ai_rejected:
                # Workflow rule: AI rejection auto-rejects leader verification too.
                # Report must never appear on maps, hotspots, cases, or analytics.
                report.leader_verification_status = "rejected"
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            else:
                background_tasks.add_task(notify_local_leaders_needs_verification_task, str(report.report_id))

    elif submitting_leader is not None:
        from app.core.leader_verification_notifications import (
            notify_police_leader_submitted_report_task,
        )

        background_tasks.add_task(
            notify_police_leader_submitted_report_task,
            str(report.report_id),
            int(submitting_leader.local_leader_id),
        )

    from app.core.leader_workflow import report_ready_for_cases_and_hotspots

    if report_ready_for_cases_and_hotspots(report):
        background_tasks.add_task(run_auto_case_for_report, str(report.report_id))
    background_tasks.add_task(run_hotspot_auto)

    return _build_report_detail_response(report, db, for_police_viewer=False)


@router.get("/", response_model=ReportListResponse)
def list_reports(
    device_id: Optional[UUID] = Query(None, description="Device ID (mobile owner). If omitted, auth required."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
    limit: int = Query(20, le=500),
    offset: int = Query(0, ge=0),
    report_status: Optional[str] = Query(None, description="Filter by report status"),
    rule_status: Optional[str] = Query(None, description="Filter by rule status"),
    boundary_status: Optional[str] = Query(None, description="Filter by boundary status"),
    incident_type_id: Optional[int] = Query(None, description="Filter by incident type"),
    village_location_id: Optional[UUID] = Query(None, description="Filter by village location"),
    sector_location_id: Optional[UUID] = Query(None, description="Filter by sector location"),
    from_date: Optional[datetime] = Query(None, description="Filter reports from this date"),
    to_date: Optional[datetime] = Query(None, description="Filter reports to this date"),
    verification_status_filter: Optional[str] = Query(
        None,
        description="Exact match against Report.verification_status (e.g. under_review)",
    ),
    verification_status_in: Optional[str] = Query(
        None,
        description="Comma-separated verification_status values (e.g. pending,under_review)",
    ),
    leader_confirmation: Optional[str] = Query(
        None,
        description="Community leader gate: pending (null,pending,''), confirmed, rejected",
    ),
    submitted_by_leader: Optional[bool] = Query(
        None,
        description="When true, only reports filed by a logged-in local leader",
    ),
    priority: Optional[str] = Query(None, description="Filter by priority: low, medium, high, urgent"),
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
    
    from app.core.station_scope import apply_report_list_scope

    query = apply_report_list_scope(query, db, current_user)
    
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

    if verification_status_filter:
        vsf = verification_status_filter.strip().lower()
        query = query.filter(Report.verification_status == vsf)

    if verification_status_in:
        parts = [
            p.strip().lower()
            for p in verification_status_in.split(",")
            if p.strip()
        ]
        if parts:
            query = query.filter(Report.verification_status.in_(parts))

    if leader_confirmation:
        lc = leader_confirmation.strip().lower()
        if lc == "pending":
            query = query.filter(
                or_(
                    Report.leader_verification_status.is_(None),
                    Report.leader_verification_status == "",
                    Report.leader_verification_status == "pending",
                )
            )
        elif lc == "confirmed":
            query = query.filter(Report.leader_verification_status == "confirmed")
        elif lc == "rejected":
            query = query.filter(Report.leader_verification_status == "rejected")

    if submitted_by_leader is True:
        query = query.filter(Report.submitted_by_local_leader_id.isnot(None))
    elif submitted_by_leader is False:
        query = query.filter(Report.submitted_by_local_leader_id.is_(None))

    if priority:
        p = priority.strip().lower()
        query = query.filter(Report.priority == p)

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




@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: UUID,
    device_id: Optional[UUID] = Query(None, description="Device ID (mobile owner)."),
    current_user: Annotated[Optional[PoliceUser], Depends(get_optional_user)] = None,
    db: Session = Depends(get_db),
):
    """Get a single report by ID."""
    from sqlalchemy.orm import joinedload
    
    report = (
        db.query(Report)
        .options(
            joinedload(Report.device),
            joinedload(Report.incident_type),
            joinedload(Report.village_location)
            .joinedload(Location.parent)
            .joinedload(Location.parent),
            joinedload(Report.evidence_files),
            joinedload(Report.assignments).joinedload(ReportAssignment.police_user).joinedload(PoliceUser.station),
            selectinload(Report.ml_predictions),
        )
        .filter(Report.report_id == report_id)
        .first()
    )

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Mobile owner access path (no auth token) - must match report owner device_id.
    if device_id is not None:
        if str(report.device_id) != str(device_id):
            raise HTTPException(status_code=401, detail="Unauthorized report access")
        return _build_report_detail_response(report, db, for_police_viewer=False)

    # Police/dashboard access path (auth required).
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return _build_report_detail_response(report, db, for_police_viewer=True)


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
    background_tasks: BackgroundTasks,
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
        if str(report.device_id) != str(device_id_uuid):
            raise HTTPException(status_code=403, detail="You can only add evidence to your own report")
        window_hours = getattr(settings, "evidence_add_window_hours", 72)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        reported_at = report.reported_at
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
        if reported_at < cutoff:
            raise HTTPException(
                status_code=400,
                detail=f"You can add evidence only within {window_hours} hours of submitting the report",
            )
    elif current_user is None:
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
        blur_score=_scalar_float(ai_analysis.get("blur_score")),
        tamper_score=_scalar_float(ai_analysis.get("tamper_score")),
        quality_label=_coerce_evidence_quality(ai_analysis.get('quality_label')),
        ai_checked_at=ai_analysis.get('ai_checked_at'),
        cloudinary_public_id=cloudinary_public_id,
        cloudinary_url=cloudinary_secure_url,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)

    # Persist pending validation metadata on the report immediately (fast).
    report_after = db.query(Report).filter(Report.report_id == report.report_id).first()
    if report_after:
        try:
            current_validations: List[Dict[str, Any]] = []
            fv_existing = report_after.feature_vector if isinstance(report_after.feature_vector, dict) else {}
            if isinstance(fv_existing.get("evidence_validations"), list):
                current_validations = list(fv_existing.get("evidence_validations") or [])

            from app.core.verification_orchestrator import pending_evidence_validation

            current_validations.append(
                {
                    "evidence_url": file_url,
                    "validation": pending_evidence_validation(),
                }
            )
            fv_update = (
                report_after.feature_vector
                if isinstance(report_after.feature_vector, dict)
                else {}
            )
            fv_update["evidence_validations"] = current_validations
            report_after.feature_vector = _json_safe(fv_update)
            db.commit()
        except Exception as e:
            logger.warning(f"Post-upload semantic validation failed for report {report_after.report_id}: {e}")

    # Run the heavy verification pipeline in a BACKGROUND task so the
    # mobile client gets an immediate response after Cloudinary upload.
    _report_id_str = str(report.report_id)
    _device_id_str = str(device.device_id) if device else None

    def _run_evidence_verification_background(report_id_str: str, device_id_str: Optional[str]):
        from app.database import SessionLocal
        from app.core.verification_orchestrator import run_citizen_verification_pipeline

        bg_db = SessionLocal()
        try:
            bg_report = bg_db.query(Report).filter(Report.report_id == report_id_str).first()
            if not bg_report:
                return
            bg_device = bg_report.device

            evidence_files_all = (
                bg_db.query(EvidenceFile).filter(EvidenceFile.report_id == bg_report.report_id).all()
            )
            fv_pre = bg_report.feature_vector if isinstance(bg_report.feature_vector, dict) else {}
            validations_pre = (
                fv_pre.get("evidence_validations")
                if isinstance(fv_pre.get("evidence_validations"), list)
                else []
            )

            def _compose_narratives_upload(**kwargs):
                r = kwargs["report"]
                uv = kwargs["unified_validation"]
                sc = kwargs["scorecard"]
                ai_lbl = kwargs["ai_label"]
                ai_ts = kwargs["ai_trust_score"]
                ev = kwargs["evidence_validations"]
                sem = fv_pre.get("semantic_alignment") if isinstance(fv_pre.get("semantic_alignment"), dict) else None
                loc_chain = _human_location_chain_from_report(r)
                r.ai_evidence_description = None
                r.ai_verification_reason = _compose_ai_verification_reason(
                    verification_status=r.verification_status,
                    rule_status=r.rule_status,
                    is_flagged=r.is_flagged,
                    flag_reason=r.flag_reason,
                    ml_prediction_label=ai_lbl,
                    trust_score=ai_ts,
                    semantic_alignment=sem,
                    incident_type_name=getattr(getattr(r, "incident_type", None), "type_name", None),
                    reporter_description=r.description,
                    context_tags=list(getattr(r, "context_tags", None) or []),
                    unified_validation=uv,
                    scorecard=sc,
                    evidence_validations=ev,
                    evidence_file_count=len(evidence_files_all or []),
                    latitude=getattr(r, "latitude", None),
                    longitude=getattr(r, "longitude", None),
                    gps_accuracy=getattr(r, "gps_accuracy", None),
                    location_label=loc_chain,
                    description_credibility=_description_credibility_from_report(r),
                    text_only_reason_codes=_text_only_reason_codes_from_report(r),
                )
                _persist_ai_analysis_snapshot(
                    r,
                    _build_ai_analysis_snapshot(
                        verification_status=r.verification_status,
                        rule_status=r.rule_status,
                        is_flagged=r.is_flagged,
                        flag_reason=r.flag_reason,
                        ml_prediction_label=ai_lbl,
                        trust_score=ai_ts,
                        semantic_alignment=sem,
                        incident_type_name=getattr(getattr(r, "incident_type", None), "type_name", None),
                        reporter_description=r.description,
                        context_tags=list(getattr(r, "context_tags", None) or []),
                        unified_validation=uv,
                        scorecard=sc,
                        evidence_validations=ev,
                        evidence_file_count=len(evidence_files_all or []),
                        latitude=getattr(r, "latitude", None),
                        longitude=getattr(r, "longitude", None),
                        gps_accuracy=getattr(r, "gps_accuracy", None),
                        location_label=loc_chain,
                    ),
                )

            run_citizen_verification_pipeline(
                bg_db,
                bg_report,
                bg_device,
                evidence_files=evidence_files_all,
                evidence_validations=validations_pre,
                compute_scorecard_fn=_compute_threshold_scorecard,
                compose_narratives_fn=_compose_narratives_upload,
            )
            _apply_post_pipeline_evidence_checks(
                bg_report,
                bg_db,
                description=bg_report.description or "",
            )
            bg_db.commit()
        except Exception as e:
            logger.exception(f"Background evidence verification failed for report {report_id_str}: {e}")
            bg_db.rollback()
            # Even if the full pipeline fails, patch the stale "no evidence" text
            # so the user doesn't see contradictory information.
            try:
                bg_report2 = bg_db.query(Report).filter(Report.report_id == report_id_str).first()
                if bg_report2:
                    ev_count = bg_db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id_str).count()
                    if ev_count > 0:
                        bg_report2.ai_verification_reason = _patch_stale_no_evidence_text(
                            bg_report2.ai_verification_reason, ev_count
                        )
                        bg_report2.ai_evidence_description = _patch_stale_no_evidence_text(
                            bg_report2.ai_evidence_description, ev_count
                        )
                        bg_db.commit()
            except Exception:
                bg_db.rollback()
        finally:
            bg_db.close()

    background_tasks.add_task(_run_evidence_verification_background, _report_id_str, _device_id_str)

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
    if device is None:
        device = db.query(Device).filter(Device.device_id == report.device_id).first()
    evidence_count = db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).count()
    if device is not None:
        score_report_credibility(db, report, device, evidence_count)
        from app.core.verification_orchestrator import (
            rerun_scorecard_and_outcome,
            run_citizen_verification_pipeline,
        )

        fv_vote = report.feature_vector if isinstance(report.feature_vector, dict) else {}
        has_unified = isinstance(fv_vote.get("unified_validation"), dict)

        try:
            if has_unified:
                rerun_scorecard_and_outcome(
                    db,
                    report,
                    device,
                    compute_scorecard_fn=_compute_threshold_scorecard,
                    respect_human_final=True,
                )
            else:
                evidence_files = (
                    db.query(EvidenceFile).filter(EvidenceFile.report_id == report_id).all()
                )
                validations = (
                    fv_vote.get("evidence_validations")
                    if isinstance(fv_vote.get("evidence_validations"), list)
                    else []
                )
                run_citizen_verification_pipeline(
                    db,
                    report,
                    device,
                    evidence_files=evidence_files,
                    evidence_validations=validations,
                    compute_scorecard_fn=_compute_threshold_scorecard,
                )
        except Exception as exc:
            logger.warning("Community vote verification refresh failed for %s: %s", report_id, exc)
            try:
                update_device_ml_aggregates(db, device, window=30)
            except Exception:
                pass

    db.commit()
    db.refresh(report)

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

    # Remove M2M hotspot links first (composite PK; DB does not cascade this table).
    db.execute(delete(hotspot_reports_table).where(hotspot_reports_table.c.report_id == report.report_id))
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

        from app.core.leader_workflow import report_eligible_for_auto_case

        if not report_eligible_for_auto_case(report):
            logger.info(
                "[AUTO_CASE] Skip report %s: awaiting local leader confirmation",
                report_id,
            )
            return
        
        # Check if report is already in a case
        from app.models.case import CaseReport
        case_reports_table = CaseReport.__table__
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
    """Try to add report to existing compatible case.

    Policy: one open case per (incident_type, station).  All verified reports
    of the same type handled by the same station are consolidated into that
    single case regardless of geographic spread.
    """
    try:
        from app.models.case import Case, CaseReport
        case_reports_table = CaseReport.__table__

        # Find the single open/in-progress case for this incident type + station.
        query = db.query(Case).filter(
            Case.incident_type_id == report.incident_type_id,
            Case.status.in_(["open", "assigned", "in_progress"]),
        )
        # Narrow to same station so reports don't leak into another station's case.
        if report.handling_station_id:
            query = query.filter(Case.station_id == report.handling_station_id)

        case = query.order_by(Case.created_at.asc()).first()

        if not case:
            return False

        logger.info(
            "[AUTO_CASE] Attaching report=%s to existing case=%s (incident_type=%s)",
            report.report_id,
            case.case_number,
            report.incident_type_id,
        )

        db.execute(
            case_reports_table.insert().values(
                case_id=case.case_id,
                report_id=report.report_id,
                added_at=datetime.now(timezone.utc),
            )
        )
        case.report_count = (case.report_count or 0) + 1
        case.updated_at = datetime.now(timezone.utc)
        # Escalate priority if this report is high/urgent
        if report.priority in ("high", "urgent") and case.priority == "medium":
            case.priority = "high"
        db.commit()
        print(f"[AUTO_CASE] Report {report.report_id} → case {case.case_number} ({case.title})")
        return True

    except Exception as e:
        print(f"Error trying to add report to existing case: {e}")
        return False


def _create_new_case_for_report(db: Session, report: Report, cluster_radius_km: float, min_reports_threshold: int):
    """Create new case for report if enough similar reports exist"""
    try:
        from app.models.case import CaseReport
        case_reports_table = CaseReport.__table__
        
        # Strategy 1: Cluster by same village/location (preferred)
        if report.village_location_id:
            vq = db.query(Report).filter(
                Report.incident_type_id == report.incident_type_id,
                Report.verification_status == "verified",
                Report.village_location_id == report.village_location_id,
                Report.report_id != report.report_id,
                ~Report.report_id.in_(
                    db.query(case_reports_table.c.report_id).distinct()
                ),
            )
            from app.core.leader_workflow import leader_gate_enabled

            if leader_gate_enabled():
                vq = vq.filter(Report.leader_verification_status == "confirmed")
            village_reports = vq.all()
            
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
                    return
            else:
                logger.info(
                    "[AUTO_CASE] Village threshold not met report=%s %s/%s",
                    report.report_id,
                    len(village_reports),
                    min_reports_threshold,
                )
        
        # Strategy 2: Station + incident type grouping (fallback)
        # Cases are formed by same incident type within the same station,
        # NOT by geographic proximity / clustering.
        station_id = report.handling_station_id
        if station_id:
            sq = db.query(Report).filter(
                Report.incident_type_id == report.incident_type_id,
                Report.verification_status == "verified",
                Report.handling_station_id == station_id,
                Report.report_id != report.report_id,
                ~Report.report_id.in_(
                    db.query(case_reports_table.c.report_id).distinct()
                ),
            )
            from app.core.leader_workflow import leader_gate_enabled

            if leader_gate_enabled():
                sq = sq.filter(Report.leader_verification_status == "confirmed")
            station_reports = sq.all()

            # Add the current report
            station_reports.insert(0, report)
            logger.info(
                "[AUTO_CASE] Station candidate report=%s count=%s threshold=%s station=%s",
                report.report_id,
                len(station_reports),
                min_reports_threshold,
                station_id,
            )

            # Create case if enough reports at the same station
            if len(station_reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, station_reports)
                if case_stats['cases_created'] > 0:
                    pass
            else:
                logger.info(
                    "[AUTO_CASE] Station threshold not met report=%s %s/%s",
                    report.report_id,
                    len(station_reports),
                    min_reports_threshold,
                )
        else:
            logger.info(
                "[AUTO_CASE] No station assigned for report=%s, skipping case creation",
                report.report_id,
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
            from app.models.case import CaseReport
            case_reports_table = CaseReport.__table__
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
    """Smart workload balancing across multiple officers."""
    from uuid import UUID

    from app.models.case import Case
    from app.models.police_user import PoliceUser
    from sqlalchemy import func
    from sqlalchemy.orm.exc import StaleDataError

    try:
        officers = db.query(PoliceUser).filter(
            PoliceUser.is_active == True,
            PoliceUser.role == "officer",
        ).all()

        if len(officers) <= 1:
            return

        officer_ids = [o.police_user_id for o in officers]
        case_counts = (
            db.query(Case.assigned_to_id, func.count(Case.case_id).label("active_cases"))
            .filter(
                Case.status.in_(["open", "assigned", "in_progress"]),
                Case.assigned_to_id.in_(officer_ids),
            )
            .group_by(Case.assigned_to_id)
            .all()
        )

        workload = {officer_id: 0 for officer_id in officer_ids}
        for officer_id, count in case_counts:
            if officer_id in workload:
                workload[officer_id] = int(count)

        max_cases = max(workload.values()) if workload else 0
        min_cases = min(workload.values()) if workload else 0
        if max_cases - min_cases <= 0:
            return

        overloaded_ids = [oid for oid, count in workload.items() if count > min_cases]
        underloaded_ids = [oid for oid, count in workload.items() if count < max_cases]
        if not overloaded_ids or not underloaded_ids:
            return

        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        candidate_cases = (
            db.query(Case)
            .filter(
                Case.assigned_to_id.in_(overloaded_ids),
                Case.status.in_(["assigned", "open", "in_progress"]),
                Case.created_at >= recent_cutoff,
            )
            .order_by(Case.created_at.desc())
            .all()
        )

        cases_by_officer: dict[int, list[Case]] = {oid: [] for oid in overloaded_ids}
        for case in candidate_cases:
            if case.assigned_to_id in cases_by_officer:
                cases_by_officer[case.assigned_to_id].append(case)

        reassigned = 0
        touched_case_ids: set[UUID] = set()

        for overloaded_id in overloaded_ids:
            for case in cases_by_officer.get(overloaded_id, [])[:5]:
                if case.case_id in touched_case_ids:
                    continue
                if not underloaded_ids:
                    break

                target_officer_id = min(underloaded_ids, key=lambda oid: workload[oid])
                still_exists = (
                    db.query(Case.case_id)
                    .filter(
                        Case.case_id == case.case_id,
                        Case.assigned_to_id == overloaded_id,
                    )
                    .first()
                )
                if not still_exists:
                    db.expire(case)
                    continue

                old_officer_id = case.assigned_to_id
                case.assigned_to_id = target_officer_id
                case.status = "open"
                case.updated_at = datetime.now(timezone.utc)
                db.flush()

                workload[overloaded_id] = max(0, workload.get(overloaded_id, 0) - 1)
                workload[target_officer_id] = workload.get(target_officer_id, 0) + 1
                touched_case_ids.add(case.case_id)
                reassigned += 1

                if workload[target_officer_id] >= min_cases:
                    underloaded_ids = [
                        oid for oid in underloaded_ids if workload[oid] < max_cases
                    ]

                logger.info(
                    "Reassigned case %s from officer %s to officer %s",
                    case.case_number,
                    old_officer_id,
                    target_officer_id,
                )

        if reassigned > 0:
            db.commit()
            logger.info(
                "Workload balanced: %s cases reassigned across %s officers",
                reassigned,
                len(officers),
            )

            try:
                import asyncio
                from app.api.v1.ws import manager

                payload = {"type": "refresh_data", "entity": "case", "action": "reassigned"}
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast(payload))
                except RuntimeError:
                    asyncio.run(manager.broadcast(payload))
            except Exception as broadcast_error:
                logger.warning(
                    "Could not broadcast case reassignments: %s", broadcast_error
                )

    except StaleDataError as e:
        db.rollback()
        logger.warning(
            "Workload balancing skipped stale case update (case may have been deleted): %s",
            e,
        )
    except Exception as e:
        db.rollback()
        logger.error("Error in workload balancing: %s", e)


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
        case_number = None
        
        high_priority_count = sum(1 for r in reports if r.priority == 'high')
        priority = 'high' if high_priority_count >= 1 else 'medium'  # Single high priority report makes case high priority
        
        case_lat = sum(r.latitude for r in reports) / len(reports)
        case_lon = sum(r.longitude for r in reports) / len(reports)
        from app.core.station_assignment import resolve_station_id

        resolved_station_id = resolve_station_id(
            db,
            latitude=float(case_lat),
            longitude=float(case_lon),
            village_location_id=getattr(report, "village_location_id", None),
            location_id=getattr(report, "location_id", None),
        )
        officer_id = _assign_officer_to_case_based_on_location(db, float(case_lat), float(case_lon))
        
        itype = (
            db.query(IncidentType)
            .filter(IncidentType.incident_type_id == report.incident_type_id)
            .first()
        )
        type_name = itype.type_name if itype else f"Incident Type {report.incident_type_id}"

        # Case title = incident type name; all same-type reports from same station
        # are consolidated here as new reports arrive.
        title = f"{type_name} case" if type_name else "Incident case"
        if type_name and type_name.lower().endswith(" cases"):
            title = f"{type_name[:-6].strip()} case"
        description = (
            f"Auto-generated consolidated case for {type_name} incidents. "
            f"Currently tracking {len(reports)} verified report(s). "
            f"New reports of the same type will be added automatically."
        )
        # Collision-safe case number allocation under concurrent auto-case runs.
        case = None
        case_created = False
        for _attempt in range(5):
            now_year = datetime.now().year
            prefix = f"CASE-{now_year}-"
            latest = (
                db.query(Case.case_number)
                .filter(Case.case_number.like(f"{prefix}%"))
                .order_by(Case.case_number.desc())
                .first()
            )
            next_seq = 1
            if latest and latest[0]:
                try:
                    next_seq = int(str(latest[0]).split("-")[-1]) + 1
                except Exception:
                    next_seq = 1
            case_number = f"{prefix}{next_seq:04d}"

            case = Case(
                case_id=uuid4(),
                case_number=case_number,
                title=title,
                description=description,
                incident_type_id=report.incident_type_id,
                priority=priority,
                status='open',
                assigned_to_id=officer_id,
                station_id=resolved_station_id,
                created_by=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                report_count=len(reports),
                location_id=report.location_id,
                latitude=case_lat,
                longitude=case_lon,
            )
            try:
                db.add(case)
                db.flush()
                case_created = True
                break
            except IntegrityError as e:
                db.rollback()
                if "cases_case_number_key" not in str(e):
                    raise
                continue

        if not case_created or case is None:
            raise RuntimeError("Failed to allocate unique case number")
        
        # Link reports to case
        for report in reports:
            db.execute(
                case_reports_table.insert().values(
                    case_id=case.case_id,
                    report_id=report.report_id,
                )
            )
        
        # Update report status and station ownership
        for report in reports:
            report.status = "verified"
            if resolved_station_id is not None:
                report.handling_station_id = resolved_station_id
        
        db.commit()
        stats['cases_created'] += 1
        stats['case_number'] = case_number
        
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
        vq = db.query(Report).filter(
            Report.verification_status == 'verified',
            Report.status == 'verified',
            ~Report.report_id.in_(
                db.query(case_reports_table.c.report_id).distinct()
            ),
        )
        from app.core.leader_workflow import leader_gate_enabled

        if leader_gate_enabled():
            vq = vq.filter(Report.leader_verification_status == "confirmed")
        verified_reports = vq.all()
        
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
        
        # Group remaining reports by station + incident type.
        # One case per (station, incident_type) — all same-type reports from the
        # same station are consolidated into a single case regardless of village.
        station_type_clusters: dict = {}
        for report in reports_for_new_case_eval:
            station_key = f"{report.handling_station_id or 'none'}_{report.incident_type_id}"
            if station_key not in station_type_clusters:
                station_type_clusters[station_key] = []
            station_type_clusters[station_key].append(report)

        for station_key, reports in station_type_clusters.items():
            if len(reports) >= min_reports_threshold:
                case_stats = _create_case_from_reports(db, reports)
                stats['cases_created'] += case_stats['cases_created']
                station_id, incident_type_id = station_key.rsplit('_', 1)
                logger.info(
                    f"Created ONE station-based case for {len(reports)} reports "
                    f"(station={station_id}, incident_type={incident_type_id})"
                )
        
        if stats["cases_created"] > 0:
            try:
                _balance_workload_and_reassign(db)
            except Exception as balance_error:
                logger.warning(
                    "Workload balancing after auto-case creation failed: %s",
                    balance_error,
                )

        return stats

    except Exception as e:
        logger.error("Auto-case creation error: %s", e)
        db.rollback()
        return stats


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


def _build_report_detail_response(
    report: Report,
    db: Session,
    *,
    for_police_viewer: bool = False,
) -> ReportDetailResponse:
    """Build a ReportDetailResponse from a Report object.

    When ``for_police_viewer`` is False (e.g. mobile submit response), strip fields that could
    identify officers (``verified_by``, reviewer names, assignment officer PII) so anonymous
    reporters cannot infer police identity from the payload.
    """
    # Get ML prediction
    ml_prediction = resolve_ml_prediction_for_report(report)
    ml_trust_numeric = (
        float(ml_prediction.trust_score)
        if ml_prediction is not None and ml_prediction.trust_score is not None
        else None
    )
    ml_prediction_label = None
    if ml_prediction is not None:
        raw_label = getattr(ml_prediction, "prediction_label", None)
        if raw_label is not None and str(raw_label).strip():
            ml_prediction_label = str(raw_label).strip().lower()
    _, ml_prediction_label = _rule_adjusted_trust_label(
        report, ml_trust_numeric, ml_prediction_label
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
    trust_score = _headline_trust_score_from_factors(trust_factors, ml_trust_numeric)
    headline_from_scorecard = isinstance(trust_factors, dict) and trust_factors.get(
        "total_score"
    ) is not None
    context_tags_list = getattr(report, "context_tags", None) or []

    # Get device metadata and trust score
    device_metadata = getattr(report.device, "metadata_json", {}) if report.device else {}
    device_trust_score = getattr(report.device, "device_trust_score", None) if report.device else None
    total_reports = getattr(report.device, "total_reports", None) if report.device else None
    trusted_reports = getattr(report.device, "trusted_reports", None) if report.device else None

    # Get incident location info (requires db session — signature is get_village_location_info(db, lat, lon))
    incident_location_info: Optional[Dict[str, Any]] = None
    incident_source = "reporter_only"
    if report.evidence_files and len(report.evidence_files) > 0:
        # Check if any evidence has location data
        evidence_with_location = [ef for ef in report.evidence_files if ef.media_latitude and ef.media_longitude]
        if evidence_with_location:
            incident_source = "combined"
            # Use evidence location for incident location
            ef = evidence_with_location[0]
            try:
                incident_location_info = get_village_location_info(
                    db, float(ef.media_latitude), float(ef.media_longitude)
                )
            except Exception:
                incident_location_info = None
        else:
            incident_source = "reporter_only"
    else:
        incident_source = "reporter_only"

    # If no evidence location, use report GPS
    if not incident_location_info and report.latitude and report.longitude:
        try:
            incident_location_info = get_village_location_info(
                db, float(report.latitude), float(report.longitude)
            )
        except Exception:
            incident_location_info = None

    ili = incident_location_info if isinstance(incident_location_info, dict) else {}
    sec_rel, cell_rel, vill_rel = _admin_hierarchy_from_village_location(
        getattr(report, "village_location", None)
    )

    # Build assignments list (strip officer-identifying fields for reporter-facing payloads)
    assignment_list = []
    if hasattr(report, "assignments") and report.assignments:
        for assignment in report.assignments:
            if for_police_viewer and assignment.police_user:
                pu = assignment.police_user
                fn = (getattr(pu, "first_name", None) or "").strip()
                ln = (getattr(pu, "last_name", None) or "").strip()
                full = f"{fn} {ln}".strip()
                off_name = full or getattr(pu, "badge_number", None)
                pid = assignment.police_user_id
            else:
                off_name = None
                pid = 0
            assignment_list.append(
                AssignmentResponse(
                    assignment_id=assignment.assignment_id,
                    report_id=assignment.report_id,
                    police_user_id=pid,
                    status=assignment.status,
                    priority=assignment.priority,
                    assignment_note=assignment.assignment_note,
                    assigned_at=assignment.assigned_at,
                    completed_at=assignment.completed_at,
                    officer_name=off_name,
                )
            )

    # Fix stale "no evidence" text when evidence was uploaded after initial verification
    actual_evidence_count = len(report.evidence_files) if report.evidence_files else 0
    raw_ai_evidence_desc = getattr(report, "ai_evidence_description", None)
    raw_ai_verification_reason = getattr(report, "ai_verification_reason", None)
    if actual_evidence_count > 0:
        raw_ai_evidence_desc = _patch_stale_no_evidence_text(raw_ai_evidence_desc, actual_evidence_count)
        raw_ai_verification_reason = _patch_stale_no_evidence_text(raw_ai_verification_reason, actual_evidence_count)

    return ReportDetailResponse(
        report_id=report.report_id,
        report_number=getattr(report, "report_number", None),
        trust_score_note=_trust_score_display_note(
            report, headline_matches_scorecard=headline_from_scorecard
        ),
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
        village_name=vill_rel or ili.get("village_name"),
        cell_name=cell_rel or ili.get("cell_name"),
        sector_name=sec_rel or ili.get("sector_name"),
        incident_type_name=report.incident_type.type_name if report.incident_type else None,
        trust_score=float(trust_score) if trust_score is not None else None,
        trust_factors=trust_factors,
        ml_prediction_label=ml_prediction_label,
        context_tags=context_tags_list,
        is_flagged=getattr(report, "is_flagged", None),
        flag_reason=getattr(report, "flag_reason", None),
        ai_evidence_description=raw_ai_evidence_desc,
        ai_verification_reason=raw_ai_verification_reason,
        decision_patterns=_extract_decision_patterns(getattr(report, "ai_verification_reason", None)),
        decision_pattern_explanations=_extract_decision_pattern_explanations(
            getattr(report, "ai_verification_reason", None)
        ),
        verified_at=getattr(report, "verified_at", None),
        verified_by=(
            getattr(report, "verified_by", None) if for_police_viewer else None
        ),
        leader_verification_status=getattr(report, "leader_verification_status", None),
        leader_verified_at=getattr(report, "leader_verified_at", None),
        submitted_by_local_leader_id=getattr(report, "submitted_by_local_leader_id", None),
        incident_latitude=float(report.latitude) if report.latitude is not None else None,
        incident_longitude=float(report.longitude) if report.longitude is not None else None,
        incident_location_source=incident_source,
        incident_village_name=ili.get("village_name") or vill_rel,
        incident_cell_name=ili.get("cell_name") or cell_rel,
        incident_sector_name=ili.get("sector_name") or sec_rel,
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
        **report_credibility_api_fields(
            report,
            trust_score=float(trust_score) if trust_score is not None else None,
            evidence_count=len(getattr(report, "evidence_files", []) or []),
        ),
    )


def _build_report_response(report: Report, db: Session, request_device_id: Optional[str] = None) -> ReportResponse:
    """Build a ReportResponse from a Report object.

    When ``request_device_id`` is set (mobile listing the device's own reports), omit
    ``verified_by`` so reporters cannot resolve officer identities from numeric ids.
    """
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
    _, ml_prediction_label = _rule_adjusted_trust_label(
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
    trust_score = _headline_trust_score_from_factors(trust_factors, trust_score)
    
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
    
    verified_by_value = getattr(report, "verified_by", None) if request_device_id is None else None
    verified_user = getattr(report, "verified_by_user", None) if verified_by_value is not None else None
    verified_by_name = None
    verified_by_role = None
    if verified_user is not None:
        first = (getattr(verified_user, "first_name", None) or "").strip()
        last = (getattr(verified_user, "last_name", None) or "").strip()
        full = f"{first} {last}".strip()
        verified_by_name = full or None
        verified_by_role = getattr(verified_user, "role", None)

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
        ai_evidence_description=_patch_stale_no_evidence_text(
            getattr(report, "ai_evidence_description", None),
            len(report.evidence_files or []),
        ),
        ai_verification_reason=_patch_stale_no_evidence_text(
            getattr(report, "ai_verification_reason", None),
            len(report.evidence_files or []),
        ),
        decision_patterns=_extract_decision_patterns(getattr(report, "ai_verification_reason", None)),
        decision_pattern_explanations=_extract_decision_pattern_explanations(
            getattr(report, "ai_verification_reason", None)
        ),
        verified_at=getattr(report, "verified_at", None),
        verified_by=verified_by_value,
        verified_by_name=verified_by_name,
        verified_by_role=verified_by_role,
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
        leader_verification_status=getattr(report, "leader_verification_status", None),
        leader_verified_at=getattr(report, "leader_verified_at", None),
        submitted_by_local_leader_id=getattr(report, "submitted_by_local_leader_id", None),
        verification_pipeline=_extract_verification_pipeline(report),
        **report_credibility_api_fields(
            report,
            trust_score=float(trust_score) if trust_score is not None else None,
            evidence_count=len(report.evidence_files or []),
        ),
    )


