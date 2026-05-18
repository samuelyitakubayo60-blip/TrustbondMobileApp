"""Build police/leader-facing credibility summaries from report feature_vector."""
from __future__ import annotations

from typing import Any, Optional


def description_credibility_from_report(report: Any) -> dict[str, Any]:
    fv = getattr(report, "feature_vector", None)
    if isinstance(fv, dict):
        meta = fv.get("description_credibility")
        if isinstance(meta, dict):
            return dict(meta)
    return {}


def credibility_detail_lines(
    desc_meta: dict[str, Any],
    *,
    evidence_count: int = 0,
) -> list[str]:
    """Human-readable bullets explaining description/evidence impact on score."""
    lines: list[str] = []
    if not desc_meta and evidence_count <= 0:
        return lines

    wc = desc_meta.get("word_count")
    min_w = desc_meta.get("min_recommended_words", 15)
    if wc is not None:
        lines.append(f"Reporter text: {wc} words (recommended {min_w}+ for full credit)")

    adj = desc_meta.get("length_adjustment")
    if adj == "bonus":
        pts = desc_meta.get("length_points")
        if pts is not None:
            lines.append(f"Longer description added +{pts} credibility points")
        else:
            lines.append("Longer description improved credibility")
    elif adj == "penalty":
        applied = desc_meta.get("applied_penalty_points")
        if applied is not None:
            lines.append(f"Short description reduced credibility by {applied} points")
        else:
            lines.append("Short description lowered credibility")

    if desc_meta.get("short_description_rescue"):
        sem = desc_meta.get("semantic_similarity")
        sem_txt = f" (semantic match {sem:.0f}%)" if isinstance(sem, (int, float)) else ""
        lines.append(
            f"Short text accepted: matches incident type and evidence{sem_txt} "
            f"(penalty capped at 30%)"
        )
    elif desc_meta.get("partial_rescue") == "semantic_only":
        lines.append(
            "Description matches incident type but needs evidence for full short-text credit"
        )

    sem = desc_meta.get("semantic_similarity")
    if sem is not None and not desc_meta.get("short_description_rescue"):
        lines.append(f"Description vs incident semantic match: {float(sem):.0f}%")

    if evidence_count > 0:
        lines.append(f"Evidence files attached: {evidence_count}")
    elif desc_meta and not desc_meta.get("has_evidence"):
        lines.append("No evidence files — short descriptions are penalized more")

    return lines


def build_credibility_summary_parts(
    *,
    report: Any,
    trust_score: Optional[float] = None,
    flag_reason: Optional[str] = None,
    evidence_count: int = 0,
    verification_status: Optional[str] = None,
    rule_status: Optional[str] = None,
) -> list[str]:
    desc_meta = description_credibility_from_report(report)
    parts: list[str] = []

    vs = (verification_status or getattr(report, "verification_status", None) or "").strip().lower()
    rs = (rule_status or getattr(report, "rule_status", None) or "").strip().lower()
    if vs == "verified":
        parts.append("Police outcome: confirmed")
    elif vs == "rejected":
        parts.append("Police outcome: rejected")
    elif rs == "rejected":
        parts.append("AI screening: rejected")
    elif rs == "flagged" or getattr(report, "is_flagged", False):
        parts.append("AI screening: flagged for review")

    if trust_score is not None:
        parts.append(f"Credibility score: {float(trust_score):.0f}/100")
    elif getattr(report, "trust_score", None) is not None:
        parts.append(f"Credibility score: {float(report.trust_score):.0f}/100")

    fr = flag_reason or getattr(report, "flag_reason", None)
    if fr:
        parts.append(f"Flag: {fr}")

    if desc_meta:
        wc = desc_meta.get("word_count")
        if wc is not None:
            parts.append(f"Description: {wc} words")
        if desc_meta.get("short_description_rescue"):
            parts.append("Short text but matches incident and evidence")
        elif desc_meta.get("length_adjustment") == "penalty":
            parts.append("Short description lowered credibility")

    if evidence_count > 0:
        parts.append(f"Evidence files: {evidence_count}")

    desc_text = (getattr(report, "description", None) or "").strip()
    if not desc_text and evidence_count == 0:
        parts.append("No description or evidence on file")

    return parts


def build_credibility_summary(
    *,
    report: Any,
    trust_score: Optional[float] = None,
    flag_reason: Optional[str] = None,
    evidence_count: int = 0,
    verification_status: Optional[str] = None,
    rule_status: Optional[str] = None,
) -> Optional[str]:
    parts = build_credibility_summary_parts(
        report=report,
        trust_score=trust_score,
        flag_reason=flag_reason,
        evidence_count=evidence_count,
        verification_status=verification_status,
        rule_status=rule_status,
    )
    return " · ".join(parts) if parts else None


def report_credibility_api_fields(
    report: Any,
    *,
    trust_score: Optional[float] = None,
    evidence_count: Optional[int] = None,
) -> dict[str, Any]:
    ec = (
        evidence_count
        if evidence_count is not None
        else len(getattr(report, "evidence_files", None) or [])
    )
    ts = trust_score
    if ts is None and getattr(report, "trust_score", None) is not None:
        ts = float(report.trust_score)
    desc_meta = description_credibility_from_report(report)
    detail_lines = credibility_detail_lines(desc_meta, evidence_count=ec)
    summary = build_credibility_summary(
        report=report,
        trust_score=ts,
        flag_reason=getattr(report, "flag_reason", None),
        evidence_count=ec,
    )
    return {
        "description_credibility": desc_meta if desc_meta else None,
        "credibility_summary": summary,
        "credibility_detail_lines": detail_lines,
    }
