"""
Rule-based report verification (no ML).
Runs on report creation and optionally after evidence upload.
Sets rule_status (pending, passed, flagged, rejected) and is_flagged.
Screenshot images and screen recordings (audio/video) are not allowed.
Detected by filename or image dimensions. Machine learning later.

Report status semantics:
- Out of scope (banned): Reports outside Musanze district are rejected at submit
  (HTTP 400). They are never stored; not "flagged" or "suspicious".
- Flagged / suspicious: A stored report that the system marked for review.
  rule_status='flagged', is_flagged=True. Same concept: "suspicious" in the sense
  that it needs human review (e.g. no description, high severity, screenshot-like
  evidence). No separate "suspicious" field; use is_flagged and rule_status.
"""
from sqlalchemy.orm import Session
import io

from app.models.report import Report
from app.models.incident_type import IncidentType

# Filename substrings that suggest a screenshot (case-insensitive)
SCREENSHOT_FILENAME_KEYWORDS = (
    "screenshot", "screen_", "screencap", "screencapture",
    "scrn", "capture", "snapshot", "screen shot",
)
# Filename substrings that suggest screen recording (audio or video)
SCREEN_RECORDING_FILENAME_KEYWORDS = (
    "screen record", "screen recording", "screen_recording",
    "screencast", "screen cast", "screen capture", "screen_capture",
    "recorded screen", "screen_record",
)
# Combined for single filename check
ALL_SCREEN_CAPTURE_KEYWORDS = SCREENSHOT_FILENAME_KEYWORDS + SCREEN_RECORDING_FILENAME_KEYWORDS

# Common screen resolutions (width, height); screenshots often match these exactly
COMMON_SCREEN_RESOLUTIONS = frozenset({
    (1920, 1080), (1080, 1920), (1366, 768), (768, 1366),
    (1280, 720), (720, 1280), (2560, 1440), (1440, 2560),
    (3840, 2160), (2160, 3840), (1536, 864), (864, 1536),
    (1600, 900), (900, 1600), (1280, 800), (800, 1280),
    (1440, 900), (900, 1440), (1680, 1050), (1050, 1680),
    (750, 1334), (1334, 750), (1125, 2436), (2436, 1125),
    (1242, 2688), (2688, 1242), (828, 1792), (1792, 828),
    (1170, 2532), (2532, 1170), (1284, 2778), (2778, 1284),
    (1080, 1920), (1440, 2560), (720, 1280), (1080, 2340),
    (2340, 1080), (1440, 3120), (3120, 1440),
})


def _filename_looks_like_screen_capture(filename: str | None) -> bool:
    """True if filename suggests screenshot or screen recording (any media type)."""
    if not filename:
        return False
    lower = filename.lower()
    for kw in ALL_SCREEN_CAPTURE_KEYWORDS:
        if kw in lower:
            return True
    return False


def is_likely_screenshot(
    *,
    filename: str | None = None,
    image_bytes: bytes | None = None,
) -> bool:
    """
    Return True if the upload looks like a screenshot image (rule-based; no ML).
    - Filename contains screenshot-like keywords.
    - Image dimensions match common screen resolutions.
    """
    if _filename_looks_like_screen_capture(filename):
        return True
    if image_bytes:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            if (w, h) in COMMON_SCREEN_RESOLUTIONS:
                return True
        except Exception:
            pass
    return False


def is_likely_screenshot_or_screen_recording(
    *,
    filename: str | None = None,
    image_bytes: bytes | None = None,
) -> bool:
    """
    True if upload looks like a screenshot (image) or screen recording (audio/video).
    Use for all evidence types: images (pass filename + image_bytes), audio/video (pass filename only).
    """
    if _filename_looks_like_screen_capture(filename):
        return True
    if image_bytes:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            if (w, h) in COMMON_SCREEN_RESOLUTIONS:
                return True
        except Exception:
            pass
    return False


# Configurable thresholds (can be moved to config later)
MIN_DESCRIPTION_LENGTH = 10
MIN_DESCRIPTION_LENGTH_WITH_EVIDENCE = 5
HIGH_SEVERITY_WEIGHT = 1.5  # incident types with severity_weight >= this get extra scrutiny


def apply_rule_based_status(
    report: Report,
    evidence_count: int,
    db: Session,
) -> tuple[str, bool, str | None]:
    """
    Apply rule-based logic to set rule_status and is_flagged.
    Returns (rule_status, is_flagged, flag_reason or None).
    """
    description = (report.description or "").strip()
    has_description = len(description) >= MIN_DESCRIPTION_LENGTH
    has_short_description = len(description) >= MIN_DESCRIPTION_LENGTH_WITH_EVIDENCE
    has_evidence = evidence_count > 0

    # Load incident type for severity
    incident_type = (
        db.query(IncidentType)
        .filter(IncidentType.incident_type_id == report.incident_type_id)
        .first()
    )
    severity = float(incident_type.severity_weight) if incident_type and incident_type.severity_weight else 1.0

    # Rule 1: Reject — no description and no evidence (too sparse to be useful)
    if not has_short_description and not has_evidence:
        return "rejected", True, "no_description_or_evidence"

    # Rule 2: Flag — has evidence but no/minimal description
    if has_evidence and not has_description:
        return "flagged", True, "no_description_with_evidence"

    # Rule 3: Flag — very short description (even with evidence)
    if has_short_description and not has_description and has_evidence:
        return "flagged", True, "minimal_description"

    # Rule 4: Flag — high severity incident type (needs review)
    if severity >= HIGH_SEVERITY_WEIGHT:
        return "flagged", True, "high_severity_incident"

    # Rule 5: Pass — has reasonable description; optional evidence
    if has_description:
        return "passed", False, None

    # Default: pending (e.g. short description but has evidence)
    if has_evidence:
        return "passed", False, None
    return "pending", False, None
