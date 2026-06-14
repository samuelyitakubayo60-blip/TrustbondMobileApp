"""
Refactored Report priority calculation and anti-fraud integration utilities.
Integrates with unified validation system and removes duplicate ML logic.
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Tuple
from app.models.report import Report
from app.models.evidence_file import EvidenceFile
from app.models.incident_type import IncidentType
from app.models.system_config import SystemConfig
from app.config import settings
from sqlalchemy.orm import Session

def calculate_report_priority(
    report: Report,
    evidence_count: int = 0,
    db: Session = None,
    unified_validation_result: Optional[dict] = None
) -> str:
    """
    Calculate automatic report priority based on multiple factors.
    Returns: 'low', 'medium', 'high', or 'urgent'
    
    Now integrates with unified validation results.
    """
    priority_score = 0
    
    # 1. Incident type severity (0-3 points)
    if db and report.incident_type_id:
        from app.core.incident_type_loader import fetch_incident_type_by_id

        incident_type = fetch_incident_type_by_id(db, report.incident_type_id)
        if incident_type and incident_type.severity_weight:
            severity = float(incident_type.severity_weight)
            if severity >= 2.0:
                priority_score += 3  # High severity
            elif severity >= 1.5:
                priority_score += 2  # Medium severity
            else:
                priority_score += 1  # Low severity
    
    # 2. Unified validation influence (0-2 points) - REPLACES old ML logic
    if unified_validation_result:
        trust_band = unified_validation_result.get("trust_band", "")
        aggregated_score = unified_validation_result.get("aggregated_score", 0)
        
        if trust_band == "reject":
            priority_score += 2  # Rejected reports need urgent review
        elif trust_band == "low_confidence":
            priority_score += 1  # Low confidence needs review
        # medium_confidence and high_confidence don't increase priority
        
        # Additional priority for very low scores
        if aggregated_score < 20:
            priority_score += 1
    
    # 3. Evidence count (0-1 point)
    if evidence_count >= 3:
        priority_score += 1  # Multiple evidence pieces increase priority
    
    # Convert score to priority level
    if priority_score >= 6:
        return "urgent"
    elif priority_score >= 4:
        return "high"
    elif priority_score >= 2:
        return "medium"
    else:
        return "low"


def apply_anti_fraud_rules(
    report: Report,
    evidence_count: int,
    db: Session = None
) -> Tuple[str, bool, Optional[str]]:
    """
    Anti-fraud and spam detection rules.
    Returns (rule_status, is_flagged, flag_reason or None).
    
    REMOVED duplicate ML logic - now focuses on anti-fraud only.
    """
    # Get basic rule-based result first
    from app.core.report_rules import apply_rule_based_status
    base_status, base_flagged, base_reason = apply_rule_based_status(
        report, evidence_count, db
    )

    # Anti-fraud checks (non-ML)
    # 1) Evidence timestamp mismatch (captured_at much older than reported_at).
    stale_reason = _stale_evidence_reason(report, db)
    if stale_reason:
        return "flagged", True, stale_reason

    # 2) Incident type vs description mismatch (semantic first, keyword fallback).
    gibberish = _gibberish_description(report)
    if gibberish:
        # Keep hard rejections from base rules, otherwise require review.
        if base_status == "rejected":
            return base_status, base_flagged, base_reason
        return "flagged", True, "gibberish_description"

    semantic_mismatch = _incident_description_mismatch_semantic(report, db)
    if semantic_mismatch:
        # Keep hard rejections from base rules, otherwise require review.
        if base_status == "rejected":
            return base_status, base_flagged, base_reason
        return "flagged", True, "incident_description_mismatch"

    # 3) Device burst/spam behavior check (many reports in a short period).
    if _device_burst_reporting(report, db):
        if base_status == "rejected":
            return base_status, base_flagged, base_reason
        return "flagged", True, "device_burst_reporting"

    # 4) Duplicate description check (same device repeats same text quickly).
    if _duplicate_description_recent(report, db):
        if base_status == "rejected":
            return base_status, base_flagged, base_reason
        return "flagged", True, "duplicate_description_recent"
    
    # NO MORE ML LOGIC HERE - unified validation handles trust scoring
    return base_status, base_flagged, base_reason


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _stale_evidence_reason(report: Report, db: Optional[Session]) -> Optional[str]:
    """Return reason code when evidence timestamp significantly mismatches report time."""
    if db is None or not report or not report.report_id:
        return None

    reported_at = _to_utc(getattr(report, "reported_at", None))
    if reported_at is None:
        return None

    # Strict threshold for claimed live captures, broader threshold otherwise.
    max_live_gap_minutes = 15
    max_regular_gap_hours = 2

    evidence_rows = (
        db.query(EvidenceFile.captured_at, EvidenceFile.is_live_capture)
        .filter(EvidenceFile.report_id == report.report_id)
        .all()
    )
    for captured_at, is_live_capture in evidence_rows:
        cap = _to_utc(captured_at)
        if cap is None:
            continue
        delta_minutes = (reported_at - cap).total_seconds() / 60.0
        if delta_minutes < 0:
            # Future capture timestamp can happen due to bad device clocks; let manual review handle only if far off.
            if abs(delta_minutes) > 10:
                return "evidence_time_mismatch"
            continue
        if is_live_capture and delta_minutes > max_live_gap_minutes:
            return "stale_live_capture_timestamp"
        if delta_minutes > (max_regular_gap_hours * 60):
            return "evidence_time_mismatch"
    return None


def _incident_description_mismatch(report: Report, db: Optional[Session]) -> bool:
    """
    Heuristic mismatch check between selected incident type and free-text description.

    DISABLED: This keyword-based approach produces too many false positives because
    incident types naturally share vocabulary (assault/fight/domestic violence share
    "hit", "beat", "violence" etc.).  The TF-IDF semantic similarity in the NL scorer
    handles mismatch detection more accurately as part of the trust aggregation score.
    Keeping the function for future reference but always returning False.
    """
    return False


def _gibberish_description(report: Report) -> bool:
    """
    Detect obviously meaningless / spammy descriptions that can slip through
    type-vs-description mismatch checks (e.g., random keysmash strings).
    Conservative: only flags when we have strong evidence the text is not human language.
    """
    import re

    description = (getattr(report, "description", None) or "").strip()
    if len(description) < 12:
        return False

    # If there are very few word boundaries, it's likely not a sentence.
    words = re.findall(r"[A-Za-z]{2,}", description)
    if len(words) < 3:
        # Allow short but meaningful descriptions like "armed robbery at market"
        # by requiring at least some spaces/punctuation structure.
        if description.count(" ") < 2:
            return True
        # still treat very low alphabetic content as gibberish

    letters = re.findall(r"[A-Za-z]", description)
    alnum = re.findall(r"[A-Za-z0-9]", description)
    if not alnum:
        return True

    alpha_ratio = len(letters) / max(1, len(description))
    if alpha_ratio < 0.45:
        return True

    # Very long "word" chunks (no spaces) are typical keysmash.
    longest_token = max((len(t) for t in re.findall(r"\S+", description)), default=0)
    if longest_token >= 18:
        return True

    # Vowel ratio sanity check (English/Kinyarwanda both have vowels frequently).
    letters_lower = "".join(ch.lower() for ch in letters)
    vowels = sum(1 for ch in letters_lower if ch in "aeiou")
    vowel_ratio = vowels / max(1, len(letters_lower))
    if vowel_ratio < 0.18:
        return True

    # Excessive repeated characters (e.g., "aaaaaa", "jjjjjj", "!!!!!!")
    if re.search(r"(.)\1{6,}", description):
        return True

    # Too many unique characters with too few spaces often indicates random strings
    # (high entropy keysmash). Use a simple proxy.
    uniq = len(set(description.lower()))
    if uniq >= 22 and description.count(" ") <= 1 and len(description) >= 20:
        return True

    return False


def _incident_description_mismatch_semantic(report: Report, db: Optional[Session]) -> bool:
    """
    Semantic mismatch via Groq/Gemini API (same stack as hotspot LLM).
    Falls back to keyword rules when API is not configured.
    """
    if db is None or not getattr(settings, "enable_semantic_match", False):
        return False

    description = (getattr(report, "description", None) or "").strip()
    if len(description) < 12:
        return False

    selected_id = getattr(report, "incident_type_id", None)
    if not selected_id:
        return False

    from app.core.natural_language_scorer import (
        incident_description_mismatch_via_llm,
        report_semantic_llm_configured,
    )

    if not report_semantic_llm_configured():
        return False

    from app.core.incident_type_loader import fetch_active_incident_types

    active_types = fetch_active_incident_types(db)
    if len(active_types) < 2:
        return False

    type_pairs = [
        (
            t.incident_type_id,
            f"{(t.type_name or '').strip()}: {(t.description or '').strip()}",
        )
        for t in active_types
    ]
    return incident_description_mismatch_via_llm(description, selected_id, type_pairs)


def _device_burst_reporting(report: Report, db: Optional[Session]) -> bool:
    """Flag suspicious bursts from same device in short windows."""
    if db is None:
        return False
    device_id = getattr(report, "device_id", None)
    reported_at = _to_utc(getattr(report, "reported_at", None))
    if not device_id or reported_at is None:
        return False
    from datetime import timedelta
    burst_threshold, _ = _spam_thresholds(db)
    window_start = reported_at - timedelta(minutes=5)
    count_5m = (
        db.query(Report.report_id)
        .filter(
            Report.device_id == device_id,
            Report.reported_at >= window_start,
            Report.reported_at <= reported_at,
        )
        .count()
    )
    # Includes this report; configurable via system_config spam.threshold.flags.
    return count_5m >= burst_threshold


def _normalize_text(text: str) -> str:
    import re
    t = (text or "").lower().strip()
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _duplicate_description_recent(report: Report, db: Optional[Session]) -> bool:
    """Flag near-identical descriptions from same device in a recent window."""
    if db is None:
        return False
    device_id = getattr(report, "device_id", None)
    description = _normalize_text(getattr(report, "description", None) or "")
    reported_at = _to_utc(getattr(report, "reported_at", None))
    if not device_id or reported_at is None or len(description) < 12:
        return False
    from datetime import timedelta
    _, duplicate_threshold = _spam_thresholds(db)
    window_start = reported_at - timedelta(hours=6)
    recent = (
        db.query(Report.description)
        .filter(
            Report.device_id == device_id,
            Report.reported_at >= window_start,
            Report.reported_at <= reported_at,
            Report.report_id != report.report_id,
        )
        .all()
    )
    if not recent:
        return False
    same = 0
    for (d,) in recent:
        if _normalize_text(d or "") == description:
            same += 1
    # Duplicate text repeated in recent reports -> suspicious.
    return same >= duplicate_threshold


def _spam_thresholds(db: Optional[Session]) -> tuple[int, int]:
    """
    Returns (burst_threshold, duplicate_threshold) with DB-driven config fallback.
    Reads system_config key: spam.threshold (JSON), e.g. {"flags": 5, "trust_score": 10}
    """
    burst_threshold = 4
    duplicate_threshold = 2
    if db is None:
        return burst_threshold, duplicate_threshold
    try:
        row = db.query(SystemConfig).filter(SystemConfig.config_key == "spam.threshold").first()
        cfg = row.config_value if row and isinstance(row.config_value, dict) else {}
        if "flags" in cfg:
            burst_threshold = max(2, int(cfg.get("flags")))
            # Keep duplicate threshold tighter than burst, but configurable by same key.
            duplicate_threshold = max(2, min(3, burst_threshold // 2))
    except Exception:
        pass
    return burst_threshold, duplicate_threshold


def should_re_enable_screenshot_detection() -> bool:
    """
    Determine if screenshot detection should be re-enabled.
    Returns True if we think it's safe to re-enable.
    """
    # For now, return False to keep uploads working
    # TODO: Implement improved screenshot detection heuristics
    return False
