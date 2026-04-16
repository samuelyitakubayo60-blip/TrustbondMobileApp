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

# Filename substrings that suggest a screenshot (case-insensitive) - FIXED to reduce false positives
SCREENSHOT_FILENAME_KEYWORDS = (
    "screenshot", "screencap", "screencapture",
    "scrn", "snapshot", "screen shot",
    # More specific patterns to avoid false positives
    "screen_shot_", "screenrec", "screenrecord",
)
# Filename substrings that suggest screen recording (audio or video) - FIXED to reduce false positives
SCREEN_RECORDING_KEYWORDS = (
    "screen record", "screen recording", "screen_recording",
    "screencast", "screen cast", "screen capture", "screen_capture",
    "recorded screen", "screen_record",
    # More specific patterns
    "screenrecord_", "screencast_",
)
# Combined for single filename check
ALL_SCREEN_CAPTURE_KEYWORDS = SCREENSHOT_FILENAME_KEYWORDS + SCREEN_RECORDING_KEYWORDS

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
    - DISABLED: Image dimensions match common screen resolutions (too many false positives).
    """
    if _filename_looks_like_screen_capture(filename):
        return True
    # DISABLED: Image dimension check causes too many false positives with legitimate photos
    # if image_bytes:
    #     try:
    #         from PIL import Image
    #         img = Image.open(io.BytesIO(image_bytes))
    #         w, h = img.size
    #         if (w, h) in COMMON_SCREEN_RESOLUTIONS:
    #             return True
    #     except Exception:
    #         pass
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


# Deterministic validation thresholds for rule engine.
# AI/ML credibility analysis happens separately in backend scoring.
MAX_GPS_ACCURACY_METERS = 200.0
HIGH_SPEED_MPS = 30.0
IMPOSSIBLE_SPEED_MPS = 55.0
STATIONARY_SPEED_TOLERANCE_MPS = 2.0


def apply_rule_based_status(
    report: Report,
    evidence_count: int,
    db: Session,
) -> tuple[str, bool, str | None]:
    """
    Apply rule-based logic to set rule_status and is_flagged.
    Returns (rule_status, is_flagged, flag_reason or None).
    """
    # Validate incident type exists and is active (domain validity).
    incident_type = (
        db.query(IncidentType)
        .filter(IncidentType.incident_type_id == report.incident_type_id)
        .first()
    )
    if incident_type is None:
        return "rejected", True, "invalid_incident_type"

    # Validate coordinates range.
    try:
        lat = float(report.latitude)
        lon = float(report.longitude)
    except Exception:
        return "rejected", True, "invalid_coordinates"
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return "rejected", True, "invalid_coordinates"

    # Validate GPS accuracy quality.
    gps_accuracy = getattr(report, "gps_accuracy", None)
    if gps_accuracy is not None:
        try:
            gps_acc = float(gps_accuracy)
            if gps_acc <= 0:
                return "flagged", True, "invalid_gps_accuracy"
            if gps_acc > MAX_GPS_ACCURACY_METERS:
                return "flagged", True, "poor_gps_accuracy"
        except Exception:
            return "flagged", True, "invalid_gps_accuracy"

    # Validate speed plausibility.
    speed_mps = getattr(report, "movement_speed", None)
    if speed_mps is not None:
        try:
            speed = float(speed_mps)
            if speed < 0:
                return "flagged", True, "invalid_movement_speed"
            if speed > IMPOSSIBLE_SPEED_MPS:
                return "rejected", True, "implausible_speed"
            if speed > HIGH_SPEED_MPS:
                return "flagged", True, "high_speed_report"
        except Exception:
            return "flagged", True, "invalid_movement_speed"

    # Validate motion consistency.
    motion_level = getattr(report, "motion_level", None)
    if motion_level is not None and str(motion_level).strip():
        motion = str(motion_level).strip().lower()
        if motion not in {"low", "medium", "high"}:
            return "flagged", True, "invalid_motion_level"

    was_stationary = getattr(report, "was_stationary", None)
    if was_stationary is True and speed_mps is not None:
        try:
            if float(speed_mps) > STATIONARY_SPEED_TOLERANCE_MPS:
                return "flagged", True, "stationary_motion_mismatch"
        except Exception:
            return "flagged", True, "stationary_motion_mismatch"

    # Deterministic rule checks passed; deeper validity/trust is handled by AI/ML pipeline.
    return "passed", False, None
