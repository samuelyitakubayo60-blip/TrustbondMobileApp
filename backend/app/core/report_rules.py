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
import os
from datetime import datetime, timezone

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


def enhanced_screenshot_detection(
    *,
    filename: str | None = None,
    image_bytes: bytes | None = None,
    file_path: str | None = None,
) -> dict:
    """
    Enhanced screenshot detection with multiple analysis methods.
    Returns dict with detection results and details.
    """
    result = {
        "is_screenshot": False,
        "detection_methods": [],
        "details": {}
    }
    
    if not filename and not image_bytes:
        return result
    
    # 1. Filename analysis
    if filename and _filename_looks_like_screen_capture(filename):
        result["is_screenshot"] = True
        result["detection_methods"].append("filename_keywords")
        result["details"]["filename"] = filename
    
    # 2. Image resolution analysis (re-enabled with better logic)
    if image_bytes:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            
            # Check exact resolution matches
            if (w, h) in COMMON_SCREEN_RESOLUTIONS:
                result["is_screenshot"] = True
                result["detection_methods"].append("exact_resolution")
                result["details"]["resolution"] = f"{w}x{h}"
            
            # Check for common aspect ratios with exact pixel dimensions
            common_ratios = [(16, 9), (9, 16), (16, 10), (10, 16), (3, 2), (2, 3)]
            for ratio_w, ratio_h in common_ratios:
                if w % ratio_w == 0 and h % ratio_h == 0:
                    scale_w = w // ratio_w
                    scale_h = h // ratio_h
                    if scale_w == scale_h and scale_w in [1, 2, 3, 4]:  # Common scaling
                        if w >= 720 and h >= 480:  # Minimum reasonable size
                            result["is_screenshot"] = True
                            result["detection_methods"].append("scaled_resolution")
                            result["details"]["scaled_resolution"] = f"{w}x{h} ({ratio_w}:{ratio_h})"
                            break
        except Exception:
            pass
    
    # 3. EXIF data analysis
    if image_bytes:
        try:
            from PIL.ExifTags import TAGS
            img = Image.open(io.BytesIO(image_bytes))
            exif_data = img._getexif()
            
            if not exif_data or len(exif_data) == 0:
                # No EXIF data is common for screenshots
                result["is_screenshot"] = True
                result["detection_methods"].append("no_exif_data")
                result["details"]["exif_status"] = "no_exif"
            else:
                # Check for screenshot software in EXIF
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == "Software" and value:
                        software = str(value).lower()
                        screenshot_software = ["screenshot", "snip", "capture", "screen"]
                        if any(sw in software for sw in screenshot_software):
                            result["is_screenshot"] = True
                            result["detection_methods"].append("exif_software")
                            result["details"]["software"] = str(value)
                            break
        except Exception:
            pass
    
    # 4. File path analysis
    if file_path:
        path_lower = file_path.lower()
        suspicious_paths = ["download", "cache", "temp", "tmp", "screenshots", "captures"]
        if any(sp in path_lower for sp in suspicious_paths):
            result["detection_methods"].append("suspicious_path")
            result["details"]["path"] = file_path
            # Path alone doesn't confirm screenshot, but adds weight
    
    return result


def analyze_file_timing(
    *,
    file_path: str | None = None,
    file_created_at: datetime | None = None,
) -> dict:
    """
    Analyze file timing to detect old or suspicious content.
    Returns dict with timing analysis results.
    """
    result = {
        "is_suspicious": False,
        "suspicious_reasons": [],
        "details": {}
    }
    
    if not file_path and not file_created_at:
        return result
    
    file_time = file_created_at
    
    # Try to get file creation time from filesystem if not provided
    if not file_time and file_path and os.path.exists(file_path):
        try:
            file_time = datetime.fromtimestamp(os.path.getctime(file_path), tz=timezone.utc)
        except Exception:
            pass
    
    if file_time:
        now = datetime.now(timezone.utc)
        time_diff = now - file_time
        
        result["details"]["file_age_hours"] = time_diff.total_seconds() / 3600
        result["details"]["file_created_at"] = file_time.isoformat()
        
        # Flag files older than 12 hours (updated from 24 hours)
        if time_diff.total_seconds() > 12 * 3600:
            result["is_suspicious"] = True
            result["suspicious_reasons"].append("old_file_12h")
            result["details"]["suspicious_age"] = f"{time_diff.total_seconds() / 3600:.1f} hours"
        
        # Extra suspicion for files older than 24 hours
        if time_diff.total_seconds() > 24 * 3600:
            result["suspicious_reasons"].append("very_old_file_24h")
        
        # Very old files (>7 days) are highly suspicious
        if time_diff.total_seconds() > 7 * 24 * 3600:
            result["suspicious_reasons"].append("extremely_old_file_7d")
        
        # Future timestamps are highly suspicious
        if file_time > now:
            result["is_suspicious"] = True
            result["suspicious_reasons"].append("future_timestamp")
    
    return result


def validate_evidence_source(
    *,
    filename: str | None = None,
    file_path: str | None = None,
    file_size: int | None = None,
) -> dict:
    """
    Enhanced evidence source validation to detect downloaded content.
    Returns dict with validation results.
    """
    result = {
        "is_valid": True,
        "is_downloaded": False,
        "suspicious_indicators": [],
        "details": {}
    }
    
    if not filename:
        return result
    
    filename_lower = filename.lower()
    
    # 1. Check for download indicators in filename
    download_keywords = ["download", "save", "cache", "temp", "tmp"]
    for keyword in download_keywords:
        if keyword in filename_lower:
            result["is_valid"] = False
            result["is_downloaded"] = True
            result["suspicious_indicators"].append(f"filename_contains_{keyword}")
            result["details"]["download_keyword"] = keyword
            break
    
    # 2. Check file path for suspicious locations
    if file_path:
        path_lower = file_path.lower()
        suspicious_paths = [
            "download", "downloads", "cache", "caches", "temp", "tmp",
            "recycle", "trash", "backup", "copy", "duplicate"
        ]
        for path in suspicious_paths:
            if path in path_lower:
                result["is_valid"] = False
                result["is_downloaded"] = True
                result["suspicious_indicators"].append(f"path_contains_{path}")
                result["details"]["suspicious_path"] = path
                break
    
    # 3. Check for suspicious filename patterns
    suspicious_patterns = [
        "copy", "duplicate", "clone", "fake", "edited", "modified", 
        "altered", "photoshop", "edit", "sample", "test", "demo"
    ]
    for pattern in suspicious_patterns:
        if pattern in filename_lower:
            result["is_valid"] = False
            result["suspicious_indicators"].append(f"suspicious_pattern_{pattern}")
            result["details"]["suspicious_pattern"] = pattern
            break
    
    # 4. File size analysis for videos
    if file_size and filename_lower.endswith(('.mp4', '.mov', '.avi', '.mkv')):
        # Very small video files might be suspicious
        if file_size < 100 * 1024:  # Less than 100KB
            result["is_valid"] = False
            result["suspicious_indicators"].append("very_small_video")
            result["details"]["video_size_kb"] = file_size // 1024
    
    result["details"]["filename"] = filename
    if file_path:
        result["details"]["file_path"] = file_path
    if file_size:
        result["details"]["file_size_bytes"] = file_size
    
    return result


def enhanced_screen_recording_detection(
    *,
    filename: str | None = None,
    file_size: int | None = None,
) -> dict:
    """
    Enhanced screen recording detection with multiple analysis methods.
    Returns dict with detection results and details.
    """
    result = {
        "is_screen_recording": False,
        "detection_methods": [],
        "details": {}
    }
    
    if not filename:
        return result
    
    filename_lower = filename.lower()
    
    # 1. Enhanced filename patterns
    screen_recording_indicators = [
        "screen", "record", "capture", "mirror", "cast", "zoom", 
        "teams", "meet", "recorded", "session", "call", "conference",
        "webex", "skype", "discord", "slack", "presentation"
    ]
    
    for indicator in screen_recording_indicators:
        if indicator in filename_lower:
            result["is_screen_recording"] = True
            result["detection_methods"].append("filename_keywords")
            result["details"]["matched_keyword"] = indicator
            break
    
    # 2. File size analysis for suspicious patterns
    if file_size and filename_lower.endswith(('.mp4', '.mov', '.avi', '.mkv')):
        result["details"]["file_size_mb"] = round(file_size / (1024 * 1024), 2)
        
        # Very small video files are suspicious
        if file_size < 100 * 1024:  # Less than 100KB
            result["is_screen_recording"] = True
            result["detection_methods"].append("very_small_size")
            result["details"]["suspicious_size"] = f"{file_size // 1024} KB"
        
        # Unusually large files for short recordings might be suspicious
        elif file_size > 5 * 1024 * 1024 * 1024:  # > 5GB
            result["detection_methods"].append("large_file")
            result["details"]["large_size"] = f"{file_size / (1024 * 1024 * 1024):.1f} GB"
    
    return result


def validate_location_consistency(
    *,
    report_latitude: float,
    report_longitude: float,
    evidence_metadata: list[dict] | None = None,
) -> dict:
    """
    Validate location consistency between report and evidence GPS metadata.
    Returns dict with validation results.
    """
    result = {
        "is_consistent": True,
        "has_warnings": False,
        "evidence_checks": [],
        "details": {}
    }
    
    if not evidence_metadata:
        result["details"]["no_evidence_metadata"] = True
        return result
    
    for i, metadata in enumerate(evidence_metadata):
        check = {
            "evidence_index": i,
            "has_gps_metadata": False,
            "distance_meters": None,
            "is_consistent": True,
            "warning": False
        }
        
        # Check if evidence has GPS metadata
        if metadata.get("media_latitude") and metadata.get("media_longitude"):
            evidence_lat = float(metadata["media_latitude"])
            evidence_lon = float(metadata["media_longitude"])
            
            check["has_gps_metadata"] = True
            check["evidence_lat"] = evidence_lat
            check["evidence_lon"] = evidence_lon
            
            # Calculate distance between report and evidence locations
            try:
                from geopy.distance import geodesic
                distance = geodesic(
                    (report_latitude, report_longitude),
                    (evidence_lat, evidence_lon)
                ).meters
            except ImportError:
                # Fallback to haversine if geopy not available
                distance = _haversine_distance(
                    report_latitude, report_longitude,
                    evidence_lat, evidence_lon
                )
            
            check["distance_meters"] = round(distance, 2)
            
            # Allow up to 100 meters difference for consistency
            if distance > 100:
                check["is_consistent"] = False
                result["is_consistent"] = False
            
            # Warn if distance is significant but within tolerance
            if distance > 50:
                check["warning"] = True
                result["has_warnings"] = True
        else:
            # Missing GPS metadata is a warning, not failure
            check["warning"] = True
            result["has_warnings"] = True
            check["missing_gps"] = True
        
        result["evidence_checks"].append(check)
    
    result["details"]["total_evidence"] = len(evidence_metadata)
    result["details"]["consistent_evidence"] = sum(1 for check in result["evidence_checks"] if check["is_consistent"])
    result["details"]["evidence_with_gps"] = sum(1 for check in result["evidence_checks"] if check["has_gps_metadata"])
    
    return result


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.
    Returns distance in meters.
    """
    import math
    
    R = 6371000  # Earth's radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * 
         math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


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
