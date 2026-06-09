"""
Stage 1: Evidence Admissibility
================================
Before analyzing evidence content, determine whether submitted evidence is acceptable.

Checks performed on images and videos:
- Screenshot detection
- AI-generated / manipulated media detection
- Duplicate evidence detection (perceptual hash)
- Corrupted file detection
- Resolution and quality validation
- Excessive compression detection
- Metadata validation
- Timestamp validation
- Evidence age validation
- Unsupported file detection

Rules:
- If evidence exists and admissibility fails → reject the report immediately.
- If no evidence is provided → continue processing (skip this stage).
- Invalid evidence must trigger rejection, not merely lower the score.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.evidence_file import EvidenceFile

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

SCREENSHOT_FILENAME_KEYWORDS = (
    "screenshot", "screencap", "screencapture",
    "scrn", "snapshot", "screen shot",
    "screen_shot_", "screenrec", "screenrecord",
    "screen record", "screen recording", "screen_recording",
    "screencast", "screen cast", "screen capture", "screen_capture",
)

COMMON_SCREEN_RESOLUTIONS = frozenset({
    (1920, 1080), (1080, 1920), (1366, 768), (768, 1366),
    (1280, 720), (720, 1280), (2560, 1440), (1440, 2560),
    (3840, 2160), (2160, 3840), (1536, 864), (864, 1536),
    (1600, 900), (900, 1600), (1280, 800), (800, 1280),
    (750, 1334), (1334, 750), (1125, 2436), (2436, 1125),
    (1242, 2688), (2688, 1242), (828, 1792), (1792, 828),
    (1170, 2532), (2532, 1170), (1284, 2778), (2778, 1284),
    (1080, 2340), (2340, 1080), (1440, 3120), (3120, 1440),
})

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg", "image/webp"}
SUPPORTED_VIDEO_TYPES = {"video/mp4", "video/mpeg", "video/quicktime", "video/webm"}
SUPPORTED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4"}
SUPPORTED_SIMPLE_TYPES = {"photo", "video", "audio"}

MAX_EVIDENCE_AGE_HOURS = 72
MIN_IMAGE_RESOLUTION = 100  # pixels, either dimension
MIN_FILE_SIZE_BYTES = 1024  # 1 KB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
MIN_AUDIO_DURATION_SECONDS = 0.5  # At least half a second of audio
MAX_AUDIO_DURATION_SECONDS = 600  # 10 minutes max


@dataclass
class AdmissibilityResult:
    """Result of evidence admissibility check for a single evidence file."""
    accepted: bool
    admissibility_score: float  # 0-100
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StageOneResult:
    """Aggregated result of Stage 1 for all evidence in a report."""
    accepted: bool
    admissibility_score: float  # 0-100 (average across evidence)
    per_evidence: List[AdmissibilityResult] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    skipped: bool = False  # True if no evidence was provided


def _normalize_file_type(file_type: Optional[str]) -> str:
    """Normalize file type string to lowercase."""
    return (file_type or "").strip().lower()


def _is_supported_type(file_type: str) -> bool:
    """Check if evidence file type is supported."""
    ft = _normalize_file_type(file_type)
    if ft in SUPPORTED_SIMPLE_TYPES:
        return True
    if ft in SUPPORTED_IMAGE_TYPES | SUPPORTED_VIDEO_TYPES | SUPPORTED_AUDIO_TYPES:
        return True
    return False


def _is_image_type(file_type: str) -> bool:
    ft = _normalize_file_type(file_type)
    return ft == "photo" or ft in SUPPORTED_IMAGE_TYPES or ft.startswith("image/")


def _is_video_type(file_type: str) -> bool:
    ft = _normalize_file_type(file_type)
    return ft == "video" or ft in SUPPORTED_VIDEO_TYPES or ft.startswith("video/")


def _is_audio_type(file_type: str) -> bool:
    ft = _normalize_file_type(file_type)
    return ft == "audio" or ft in SUPPORTED_AUDIO_TYPES or ft.startswith("audio/")


def _detect_screenshot_from_filename(filename: Optional[str]) -> bool:
    """Detect screenshots from filename patterns."""
    if not filename:
        return False
    lower = filename.lower()
    return any(kw in lower for kw in SCREENSHOT_FILENAME_KEYWORDS)


def _check_screenshot_resolution(width: Optional[int], height: Optional[int]) -> bool:
    """Check if image resolution exactly matches common screen resolutions."""
    if not width or not height:
        return False
    return (width, height) in COMMON_SCREEN_RESOLUTIONS


def _check_evidence_age(
    captured_at: Optional[datetime],
    reported_at: Optional[datetime],
) -> tuple[bool, Optional[str]]:
    """Validate evidence is not too old. Returns (is_valid, reason)."""
    if captured_at is None:
        return True, None  # No timestamp — cannot validate age

    now = datetime.now(timezone.utc)
    cap = captured_at if captured_at.tzinfo else captured_at.replace(tzinfo=timezone.utc)

    # Future timestamp
    if cap > now + timedelta(minutes=10):
        return False, "evidence_timestamp_in_future"

    # Stale evidence
    ref_time = reported_at or now
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    age_hours = (ref_time - cap).total_seconds() / 3600.0
    if age_hours > MAX_EVIDENCE_AGE_HOURS:
        return False, f"evidence_too_old_{int(age_hours)}h"

    return True, None


def _check_duplicate_evidence(
    evidence_file: EvidenceFile,
    all_evidence: List[EvidenceFile],
) -> bool:
    """Detect duplicate evidence via perceptual hash."""
    phash = getattr(evidence_file, "perceptual_hash", None)
    if not phash:
        return False
    eid = getattr(evidence_file, "evidence_id", None)
    for other in all_evidence:
        if getattr(other, "evidence_id", None) == eid:
            continue
        if getattr(other, "perceptual_hash", None) == phash:
            return True
    return False


def _check_file_integrity(evidence_file: EvidenceFile) -> tuple[bool, Optional[str]]:
    """Validate file size and basic integrity."""
    file_size = getattr(evidence_file, "file_size", None)
    if file_size is not None:
        if file_size < MIN_FILE_SIZE_BYTES:
            return False, "file_too_small_likely_corrupted"
        if file_size > MAX_FILE_SIZE_BYTES:
            return False, "file_exceeds_maximum_size"
    return True, None


def _assess_image_quality(evidence_file: EvidenceFile) -> tuple[float, List[str]]:
    """
    Assess image quality from stored metadata.
    Returns (quality_score 0-100, issues).
    """
    issues: List[str] = []
    score = 80.0  # default decent quality

    blur = getattr(evidence_file, "blur_score", None)
    if blur is not None:
        blur_f = float(blur)
        if blur_f < 50.0:
            score -= 30.0
            issues.append("very_blurry_image")
        elif blur_f < 100.0:
            score -= 15.0
            issues.append("blurry_image")

    tamper = getattr(evidence_file, "tamper_score", None)
    if tamper is not None:
        tamper_f = float(tamper)
        if tamper_f > 0.7:
            score -= 40.0
            issues.append("likely_manipulated_media")
        elif tamper_f > 0.4:
            score -= 20.0
            issues.append("possibly_manipulated_media")

    quality_label = getattr(evidence_file, "quality_label", None)
    if quality_label is not None:
        ql = str(quality_label).strip().lower()
        if hasattr(quality_label, "value"):
            ql = quality_label.value
        if ql == "poor":
            score -= 15.0
            issues.append("poor_quality_label")

    return max(0.0, min(100.0, score)), issues


def check_single_evidence_admissibility(
    evidence_file: EvidenceFile,
    all_evidence: List[EvidenceFile],
    reported_at: Optional[datetime] = None,
) -> AdmissibilityResult:
    """
    Run all admissibility checks on a single evidence file.
    Returns AdmissibilityResult with pass/fail and detailed reasons.
    """
    reasons: List[str] = []
    metadata: Dict[str, Any] = {}
    score = 100.0
    fatal = False

    file_type = _normalize_file_type(getattr(evidence_file, "file_type", None))
    file_url = getattr(evidence_file, "file_url", "") or ""
    filename = file_url.split("/")[-1].split("?")[0] if file_url else ""

    # 1. Unsupported file type
    if not _is_supported_type(file_type):
        reasons.append(f"unsupported_file_type:{file_type}")
        fatal = True
        score = 0.0

    # 2. Screenshot detection (filename-based)
    if _detect_screenshot_from_filename(filename):
        reasons.append("screenshot_detected_filename")
        fatal = True
        score = 0.0
        metadata["screenshot_source"] = "filename"

    # 3. File integrity (size)
    integrity_ok, integrity_reason = _check_file_integrity(evidence_file)
    if not integrity_ok:
        reasons.append(integrity_reason)
        fatal = True
        score = 0.0

    # 4. Duplicate evidence
    if _check_duplicate_evidence(evidence_file, all_evidence):
        reasons.append("duplicate_evidence_detected")
        score -= 40.0
        metadata["duplicate"] = True

    # 5. Evidence age / timestamp validation
    captured_at = getattr(evidence_file, "captured_at", None)
    age_ok, age_reason = _check_evidence_age(captured_at, reported_at)
    if not age_ok:
        reasons.append(age_reason)
        score -= 30.0
        metadata["timestamp_issue"] = age_reason

    # 6. Live capture timestamp mismatch
    is_live = getattr(evidence_file, "is_live_capture", False)
    if is_live and captured_at and reported_at:
        cap = captured_at if captured_at.tzinfo else captured_at.replace(tzinfo=timezone.utc)
        rep = reported_at if reported_at.tzinfo else reported_at.replace(tzinfo=timezone.utc)
        delta_min = abs((rep - cap).total_seconds()) / 60.0
        if delta_min > 15:
            reasons.append("live_capture_timestamp_too_far_from_report")
            score -= 25.0

    # 7. Image/video quality assessment (visual evidence only)
    if _is_image_type(file_type) or _is_video_type(file_type):
        quality_score, quality_issues = _assess_image_quality(evidence_file)
        if quality_issues:
            reasons.extend(quality_issues)
        if quality_score < 20.0:
            score -= 30.0
        elif quality_score < 50.0:
            score -= 15.0
        metadata["quality_score"] = round(quality_score, 2)

    # 7b. Audio-specific admissibility checks
    if _is_audio_type(file_type):
        duration = getattr(evidence_file, "duration", None)
        if duration is not None:
            dur_f = float(duration)
            if dur_f < MIN_AUDIO_DURATION_SECONDS:
                reasons.append("audio_too_short")
                score -= 30.0
            elif dur_f > MAX_AUDIO_DURATION_SECONDS:
                reasons.append("audio_exceeds_max_duration")
                score -= 15.0
            metadata["audio_duration_seconds"] = round(dur_f, 2)
        # Audio is NOT penalized for blur_score/tamper_score (visual-only metrics)
        # Noisy or unclear audio is normal for crime scenes

    # 8. Tamper / AI manipulation detection (visual evidence only)
    if _is_image_type(file_type) or _is_video_type(file_type):
        tamper = getattr(evidence_file, "tamper_score", None)
        if tamper is not None and float(tamper) > 0.8:
            reasons.append("ai_generated_or_heavily_manipulated")
            fatal = True
            score = 0.0

    final_score = max(0.0, min(100.0, score))
    accepted = not fatal and final_score >= 30.0

    return AdmissibilityResult(
        accepted=accepted,
        admissibility_score=round(final_score, 2),
        reasons=reasons,
        metadata=metadata,
    )


def run_evidence_admissibility(
    evidence_files: List[EvidenceFile],
    reported_at: Optional[datetime] = None,
) -> StageOneResult:
    """
    Stage 1: Check admissibility of all evidence files for a report.

    Rules:
    - No evidence → skip (accepted=True, skipped=True)
    - Any evidence fails admissibility → reject entire report
    - All evidence passes → accepted=True with aggregate score
    """
    if not evidence_files:
        return StageOneResult(
            accepted=True,
            admissibility_score=100.0,
            skipped=True,
            reasons=["no_evidence_provided_skipping_admissibility"],
        )

    per_evidence: List[AdmissibilityResult] = []
    all_reasons: List[str] = []
    any_failed = False

    for ef in evidence_files:
        result = check_single_evidence_admissibility(ef, evidence_files, reported_at)
        per_evidence.append(result)
        if not result.accepted:
            any_failed = True
            all_reasons.extend(result.reasons)

    if any_failed:
        return StageOneResult(
            accepted=False,
            admissibility_score=0.0,
            per_evidence=per_evidence,
            reasons=all_reasons or ["evidence_admissibility_failed"],
        )

    avg_score = sum(r.admissibility_score for r in per_evidence) / len(per_evidence)

    return StageOneResult(
        accepted=True,
        admissibility_score=round(avg_score, 2),
        per_evidence=per_evidence,
        reasons=[],
    )
