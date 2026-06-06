"""Case status normalization and RIB handover workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

RIB_UNIT_CODE = "RIB"
RIB_OUTCOME = "handed_to_rib"

# Canonical active statuses (Security Situation / sidebar).
ACTIVE_CASE_STATUSES = ("open", "assigned", "in_progress")

# Legacy alias kept in DB until migrated on write.
_LEGACY_INVESTIGATING = "investigating"


def normalize_case_status(status: Optional[str]) -> str:
    """Map legacy UI/API values to canonical case statuses."""
    s = (status or "").strip().lower()
    if s == _LEGACY_INVESTIGATING:
        return "in_progress"
    if s in ACTIVE_CASE_STATUSES or s == "closed":
        return s
    return s or "open"


def is_active_case_status(status: Optional[str]) -> bool:
    return normalize_case_status(status) in ACTIVE_CASE_STATUSES


def apply_rib_handover(
    case,
    *,
    summary: str,
    prerequisites_acknowledged: bool,
    handed_over_at: Optional[datetime] = None,
) -> None:
    """
    Close a case and record RIB handover in one atomic update.
    Removes the case from Security Situation active lists (status=closed).
    """
    now = handed_over_at or datetime.now(timezone.utc)
    case.special_assignment_unit = RIB_UNIT_CODE
    case.rib_handed_over_at = now
    case.rib_handover_summary = (summary or "").strip() or None
    case.rib_handover_prerequisites_acknowledged = bool(prerequisites_acknowledged)
    case.status = "closed"
    case.outcome = RIB_OUTCOME
    case.closed_at = now


def should_auto_close_for_rib_patch(
    *,
    special_assignment_unit: Optional[str],
    rib_handed_over_at,
    rib_handover_summary: Optional[str],
) -> bool:
    """PATCH update: auto-close when RIB unit + handover timestamp are set."""
    unit = (special_assignment_unit or "").strip().upper()
    if unit != RIB_UNIT_CODE:
        return False
    return rib_handed_over_at is not None or bool((rib_handover_summary or "").strip())
