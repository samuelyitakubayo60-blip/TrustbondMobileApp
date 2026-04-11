"""
Report priority calculation and AI integration utilities.
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Tuple
from app.models.report import Report
from app.models.ml_prediction import MLPrediction
from app.models.evidence_file import EvidenceFile
from app.models.incident_type import IncidentType
from app.models.system_config import SystemConfig
from app.config import settings
from sqlalchemy.orm import Session

_SEMANTIC_MODEL = None
_SEMANTIC_MODEL_UNAVAILABLE = False


def calculate_report_priority(
    report: Report,
    ml_prediction: Optional[MLPrediction] = None,
    evidence_count: int = 0,
    db: Session = None
) -> str:
    """
    Calculate automatic report priority based on multiple factors.
    Returns: 'low', 'medium', 'high', or 'urgent'
    """
    priority_score = 0
    
    # 1. Incident type severity (0-3 points)
    if db and report.incident_type_id:
        from app.models.incident_type import IncidentType
        incident_type = db.query(IncidentType).filter(
            IncidentType.incident_type_id == report.incident_type_id
        ).first()
        if incident_type and incident_type.severity_weight:
            severity = float(incident_type.severity_weight)
            if severity >= 2.0:
                priority_score += 3  # High severity
            elif severity >= 1.5:
                priority_score += 2  # Medium severity
            else:
                priority_score += 1  # Low severity
    
    # 2. AI prediction influence (0-2 points)
    if ml_prediction:
        if ml_prediction.prediction_label == "fake":
            priority_score += 2  # Fake reports need urgent review
        elif ml_prediction.prediction_label in ["suspicious", "uncertain"]:
            priority_score += 1  # Suspicious/uncertain needs review
        # likely_real doesn't increase priority
    
    # 3. Evidence count (0-1 point)
    if evidence_count >= 3:
        priority_score += 1  # Multiple evidence pieces increase priority
    
    # 4. Trust score (inverse - lower trust = higher priority)
    if ml_prediction and ml_prediction.trust_score is not None:
        trust_score = float(ml_prediction.trust_score)
        if trust_score < 0.3:
            priority_score += 2  # Very low trust
        elif trust_score < 0.6:
            priority_score += 1  # Low trust
    
    # Convert score to priority level
    if priority_score >= 6:
        return "urgent"
    elif priority_score >= 4:
        return "high"
    elif priority_score >= 2:
        return "medium"
    else:
        return "low"


def apply_ai_enhanced_rules(
    report: Report,
    evidence_count: int,
    ml_prediction: Optional[MLPrediction] = None,
    db: Session = None
) -> Tuple[str, bool, Optional[str]]:
    """
    Enhanced rule-based logic that incorporates AI predictions.
    Returns (rule_status, is_flagged, flag_reason or None).
    """
    # Get basic rule-based result first
    from app.core.report_rules import apply_rule_based_status
    base_status, base_flagged, base_reason = apply_rule_based_status(
        report, evidence_count, db
    )

    # Additional anti-false-positive checks (non-ML) before ML overrides.
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
    keyword_mismatch = _incident_description_mismatch(report, db)
    if semantic_mismatch or keyword_mismatch:
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
    
    # AI enhancement: Override or enhance based on ML prediction
    if ml_prediction:
        prediction_label = ml_prediction.prediction_label
        trust_score = float(ml_prediction.trust_score) if ml_prediction.trust_score else 0.5
        
        # FIXED: Clearer AI rules based on new prediction labels
        # Rule: AI says "fake" (0-30%) -> always flagged for review
        if prediction_label == "fake":
            return "flagged", True, "ai_detected_fake"
        
        # Rule: AI says "uncertain" (30-60%) -> keep as passed but set verification_status to under_review
        if prediction_label == "uncertain":
            if base_status == "passed":
                # Keep rule_status as passed but don't auto-verify (will be handled in verification_status)
                return "passed", False, "ai_uncertain_review"
            # Keep other statuses (rejected, flagged) as-is
        
        # Rule: AI says "suspicious" (60-85%) -> keep as passed but set verification_status to under_review
        if prediction_label == "suspicious":
            if base_status == "passed":
                # Keep rule_status as passed but don't auto-verify (will be handled in verification_status)
                return "passed", False, "ai_suspicious_review"
            # Keep other statuses (rejected, flagged) as-is
        
        # Rule: AI says "likely_real" (85-100%) -> no changes, proceed with normal verification
        if prediction_label == "likely_real":
            # Keep base status, no AI interference
            pass
    
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
    """Heuristic mismatch check between selected incident type and free-text description."""
    if db is None:
        return False
    description = (getattr(report, "description", None) or "").strip().lower()
    if len(description) < 8:
        return False

    incident_type_id = getattr(report, "incident_type_id", None)
    if not incident_type_id:
        return False
    it = (
        db.query(IncidentType)
        .filter(IncidentType.incident_type_id == incident_type_id)
        .first()
    )
    if not it or not getattr(it, "type_name", None):
        return False

    type_name = str(it.type_name).strip().lower()
    keywords = {
        "theft": {"steal", "stolen", "rob", "robbed", "snatch", "burglary", "thief"},
        "vandalism": {"damage", "destroy", "broken", "graffiti", "deface"},
        "suspicious activity": {"suspicious", "strange", "unknown", "lurking", "watching"},
        "domestic violence": {"husband", "wife", "family", "home", "domestic", "partner", "beating"},
        "drug activity": {"drug", "weed", "cocaine", "heroin", "dealer", "selling", "pills"},
        "fraud/scam": {"scam", "fraud", "fake", "con", "money transfer", "phishing"},
        "harassment": {"harass", "threat", "stalk", "intimidat", "abuse"},
        "traffic incident": {"accident", "crash", "collision", "vehicle", "road", "car"},
        "assault": {"assault", "attack", "fight", "hit", "beaten", "injur", "violence"},
    }
    own = keywords.get(type_name)
    if not own:
        return False

    own_hits = any(k in description for k in own)
    # If user chose a known type but the description contains no related signal,
    # require review (prevents "assault" + random text from passing).
    if not own_hits:
        return True
    other_hits = 0
    for t, ks in keywords.items():
        if t == type_name:
            continue
        if any(k in description for k in ks):
            other_hits += 1

    # If description strongly matches other types too, keep mismatch as well.
    return other_hits >= 1


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


def _get_semantic_model():
    global _SEMANTIC_MODEL, _SEMANTIC_MODEL_UNAVAILABLE
    if not getattr(settings, "enable_semantic_match", False):
        return None
    if _SEMANTIC_MODEL is not None:
        return _SEMANTIC_MODEL
    if _SEMANTIC_MODEL_UNAVAILABLE:
        return None
    try:
        from sentence_transformers import SentenceTransformer

        # Lightweight model with good sentence-level semantic matching.
        _SEMANTIC_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        return _SEMANTIC_MODEL
    except Exception:
        # Fail open: system continues using keyword rules.
        _SEMANTIC_MODEL_UNAVAILABLE = True
        return None


def _incident_description_mismatch_semantic(report: Report, db: Optional[Session]) -> bool:
    """
    Semantic mismatch check using sentence embeddings.
    Returns True only when selected incident type is clearly less similar
    than the best alternative and confidence is meaningfully high.
    """
    if db is None:
        return False

    description = (getattr(report, "description", None) or "").strip()
    if len(description) < 12:
        return False

    selected_id = getattr(report, "incident_type_id", None)
    if not selected_id:
        return False

    model = _get_semantic_model()
    if model is None:
        return False

    selected = (
        db.query(IncidentType)
        .filter(IncidentType.incident_type_id == selected_id)
        .first()
    )
    if not selected:
        return False

    active_types = (
        db.query(IncidentType)
        .filter(getattr(IncidentType, "is_active", True) == True)  # noqa: E712
        .all()
    )
    if not active_types:
        active_types = db.query(IncidentType).all()
    if len(active_types) < 2:
        return False

    labels = []
    ids = []
    for t in active_types:
        txt = f"{(t.type_name or '').strip()}: {(t.description or '').strip()}"
        labels.append(txt)
        ids.append(t.incident_type_id)

    try:
        emb_desc = model.encode(description, convert_to_tensor=True, normalize_embeddings=True)
        emb_types = model.encode(labels, convert_to_tensor=True, normalize_embeddings=True)

        # cosine scores in [-1, 1], normalized embeddings keep it efficient.
        # Lazy import to avoid hard dependency issues at module load.
        from sentence_transformers import util
        scores = util.cos_sim(emb_desc, emb_types)[0]

        best_idx = int(scores.argmax().item())
        best_score = float(scores[best_idx].item())
        best_id = ids[best_idx]

        selected_idx = None
        for i, iid in enumerate(ids):
            if iid == selected_id:
                selected_idx = i
                break
        if selected_idx is None:
            return False
        selected_score = float(scores[selected_idx].item())
    except Exception:
        return False

    # Conservative mismatch rule:
    # - selected type is not top match
    # - top semantic confidence is decent
    # - and top-vs-selected margin is meaningful
    return (
        best_id != selected_id
        and best_score >= 0.42
        and (best_score - selected_score) >= 0.10
    )


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
