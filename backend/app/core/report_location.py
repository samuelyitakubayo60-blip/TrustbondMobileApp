"""
Combine reporter location and evidence (EXIF/client) locations to derive incident location.
Used for display and map; no ML.
"""
from typing import Tuple, Optional, List

from app.models.report import Report
from app.models.evidence_file import EvidenceFile


def _float_or_none(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def compute_incident_location(
    report: Report,
    evidence_files: List[EvidenceFile],
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Compute a single incident location from reporter + evidence GPS.

    Returns:
        (latitude, longitude, source)
        source: "reporter_only" | "evidence_only" | "combined"
    """
    points: List[Tuple[float, float]] = []

    rep_lat = _float_or_none(report.latitude)
    rep_lon = _float_or_none(report.longitude)
    if rep_lat is not None and rep_lon is not None:
        points.append((rep_lat, rep_lon))

    for ef in evidence_files or []:
        lat = _float_or_none(ef.media_latitude)
        lon = _float_or_none(ef.media_longitude)
        if lat is not None and lon is not None:
            points.append((lat, lon))

    if not points:
        return None, None, "reporter_only"

    if len(points) == 1:
        return points[0][0], points[0][1], "reporter_only" if (rep_lat is not None and rep_lon is not None) else "evidence_only"

    # Average all points (reporter + evidence) for combined incident location
    avg_lat = sum(p[0] for p in points) / len(points)
    avg_lon = sum(p[1] for p in points) / len(points)
    has_reporter = rep_lat is not None and rep_lon is not None
    has_evidence = any(
        _float_or_none(ef.media_latitude) is not None and _float_or_none(ef.media_longitude) is not None
        for ef in (evidence_files or [])
    )
    source = "combined" if (has_reporter and has_evidence) else ("evidence_only" if has_evidence else "reporter_only")
    return round(avg_lat, 7), round(avg_lon, 7), source
