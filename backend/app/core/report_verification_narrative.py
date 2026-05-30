"""
Plain-language verification summaries for dashboard users.

One unified briefing (description + evidence + outcome). Technical codes stay
in structured fields only — never in text shown to officers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _truncate(text: Optional[str], limit: int) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return f"{t[: limit - 3]}..."


def humanize_flag_reason(reason: Optional[str]) -> str:
    """Turn internal flag_reason values into short plain English."""
    if not reason:
        return ""
    key = str(reason).strip().lower().replace("-", "_")
    mapping = {
        "incident_description_mismatch": (
            "The written description does not match the selected incident type."
        ),
        "incident_text_mismatch": (
            "The written description does not match the selected incident type."
        ),
        "description_evidence_mismatch": (
            "The description, uploaded media, and incident type do not line up."
        ),
        "evidence_incident_mismatch": (
            "Uploaded media does not support the selected incident type."
        ),
        "text_only_validation_failed": (
            "The description alone did not pass automated quality checks."
        ),
        "gibberish_description": (
            "The description appears unclear or not meaningful."
        ),
        "out_of_musanze_boundary": (
            "The report location is outside the allowed area."
        ),
        "evidence_time_mismatch": (
            "Evidence timestamps do not match when the report was filed."
        ),
        "stale_live_capture_timestamp": (
            "Live-capture evidence appears too old relative to the report time."
        ),
        "device_burst_reporting": (
            "Too many reports were submitted from this device in a short time."
        ),
        "duplicate_description_recent": (
            "The same description was submitted repeatedly from this device."
        ),
        "threshold_low_score": (
            "The automated credibility score was too low to auto-confirm."
        ),
        "hard_rule_reject": (
            "A mandatory policy rule blocked automatic acceptance."
        ),
        "evidence_integrity_check": (
            "Evidence failed an integrity check."
        ),
        "rejected_by_reviewer": (
            "A reviewer rejected this report."
        ),
        "rejected_by_local_leader": (
            "A local leader reviewed and rejected this report."
        ),
        "evidence_does_not_match_incident": (
            "The uploaded media contained no objects or content matching the selected incident type."
        ),
    }
    if key in mapping:
        return mapping[key]
    if "mismatch" in key and "incident" in key:
        return "The written description does not match the selected incident type."
    return str(reason).replace("_", " ").strip().capitalize() + "."


def _decision_headline(
    verification_status: str,
    rule_status: str,
    is_flagged: bool,
) -> Tuple[str, str]:
    vs = (verification_status or "pending").strip().lower()
    rs = (rule_status or "").strip().lower()

    if vs == "verified":
        return (
            "Confirmed",
            "Automated screening accepted this report. An officer may still change the decision.",
        )
    if vs == "rejected" or rs == "rejected":
        return (
            "Rejected",
            "Automated screening did not accept this report. An officer should review before treating it as valid.",
        )
    if rs == "flagged" or is_flagged:
        return (
            "Needs leader review",
            "Automated screening found concerns. A local leader must confirm or reject.",
        )
    if vs == "under_review":
        return (
            "Pending leader review",
            "The report was not auto-confirmed. A local leader must decide after reviewing it.",
        )
    return (
        "Pending",
        "Screening is incomplete or inconclusive.",
    )


def _evidence_paragraph(snapshot: Dict[str, Any]) -> str:
    evid = (snapshot.get("model_signals") or {}).get("evidence_ai") or {}
    ec = int(evid.get("evidence_count") or 0)
    try:
        ec = max(
            ec,
            int(snapshot.get("evidence_count") or 0),
            int(snapshot.get("evidence_file_count") or 0),
            len(snapshot.get("evidence_files") or []),
        )
    except Exception:
        pass

    if ec <= 0:
        return (
            "No photos, videos, or audio were uploaded. The decision used the written "
            "description, location, and automated text checks only."
        )

    nl = (snapshot.get("model_signals") or {}).get("natural_language") or {}
    mismatch = nl.get("mismatch") is True

    # Per-file details (richer data stored by _extract_evidence_per_file_summary)
    per_file: List[Dict[str, Any]] = evid.get("per_file") or []

    # Build one sentence per file
    file_lines: List[str] = []
    any_failed = False
    any_no_objects = False
    for i, f in enumerate(per_file, 1):
        mt = str(f.get("media_type") or "file").capitalize()
        valid = f.get("valid")
        score = f.get("volo_score")
        objects = f.get("detected_objects") or []
        issues = f.get("issues") or []

        score_txt = f" (AI score: {score}/100)" if score is not None else ""
        if objects:
            obj_txt = f"detected content: {', '.join(objects[:6])}"
        else:
            obj_txt = "no relevant objects detected"
            any_no_objects = True

        if valid is False:
            status_txt = "did not pass automated screening"
            any_failed = True
        elif valid is True:
            status_txt = "passed automated screening"
        else:
            status_txt = "analysis inconclusive"

        issue_txt = ""
        if issues:
            issue_txt = f" Issue: {issues[0]}."

        file_lines.append(
            f"File {i} ({mt}){score_txt}: {status_txt}. {obj_txt.capitalize()}.{issue_txt}"
        )

    # Fallback if per_file was not populated (older snapshot)
    if not file_lines:
        volo = evid.get("breakdown") if isinstance(evid.get("breakdown"), dict) else {}
        meta = volo.get("metadata") if isinstance(volo.get("metadata"), dict) else {}
        det = meta.get("detection_analysis") if isinstance(meta.get("detection_analysis"), dict) else {}
        objects = det.get("detected_objects") or []
        obj_txt = f" Screening noted: {', '.join(str(o) for o in objects[:8])}." if objects else " No relevant objects were detected in the media."
        header = f"{ec} media file(s) were reviewed for basic scene content and quality.{obj_txt}"
    else:
        header = f"{ec} media file(s) were reviewed by automated screening:"

    parts: List[str] = [header]
    parts.extend(file_lines)

    if any_failed or any_no_objects:
        parts.append(
            "The uploaded media did not contain clear visual evidence matching the selected incident type."
        )
    if mismatch:
        parts.append(
            "What was described in writing, what was seen in the media, and the selected "
            "incident type did not fully align."
        )
    elif not any_failed:
        parts.append(
            "Media should still be verified on scene; automated screening is advisory only."
        )

    return " ".join(parts)


def _plain_concerns(
    *,
    snapshot: Dict[str, Any],
    flag_reason: Optional[str],
    text_only_reason_codes: Optional[List[str]] = None,
) -> List[str]:
    concerns: List[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            concerns.append(line)

    fr_plain = humanize_flag_reason(flag_reason)
    if fr_plain:
        add(fr_plain)

    codes = {str(c).strip().upper() for c in (text_only_reason_codes or []) if str(c).strip()}
    if "INCIDENT_TEXT_MISMATCH" in codes:
        add("The written description does not match the selected incident type.")
    if "GIBBERISH" in codes or "REJECT_QUALITY" in codes:
        add("The description quality was too weak for reliable automated checks.")
    if "REVIEW_QUALITY" in codes:
        add("The description was borderline and needed closer review.")

    nl = (snapshot.get("model_signals") or {}).get("natural_language") or {}
    if nl.get("mismatch") is True:
        add(
            "The description, selected incident type, and evidence summary did not align."
        )

    fd = snapshot.get("final_decision") or {}
    label = (fd.get("label") or "").strip().lower()
    ts = fd.get("trust_score")
    if label in {"fake", "suspicious"}:
        add("The credibility model rated this submission as low authenticity.")
    elif ts is not None:
        try:
            score = float(ts)
            if score < 70:
                add(
                    f"The credibility score ({score:.0f} out of 100) is below the level "
                    "normally used for automatic confirmation."
                )
        except (TypeError, ValueError):
            pass

    rs = (fd.get("rule_status") or "").strip().lower()
    vs = (fd.get("status") or "").strip().lower()
    if rs == "rejected" and vs == "rejected" and len(concerns) < 2:
        add("Policy rules and score thresholds led to an automatic rejection.")

    return concerns[:5]


def build_unified_verification_summary(
    *,
    snapshot: Dict[str, Any],
    verification_status: Optional[str],
    rule_status: Optional[str],
    is_flagged: Optional[bool],
    flag_reason: Optional[str] = None,
    text_only_reason_codes: Optional[List[str]] = None,
    reviewer_note: Optional[str] = None,
) -> str:
    """Single inline briefing: report context, decision, why, evidence, next step."""
    if not isinstance(snapshot, dict):
        return "A verification summary is not available for this report."

    vs = (verification_status or "pending").strip().lower()
    rs = (rule_status or "").strip().lower()
    flagged = bool(is_flagged)
    effective_vs = "rejected" if rs == "rejected" else vs

    incident = (snapshot.get("incident_type") or "incident").strip() or "incident"
    desc = _truncate(snapshot.get("reporter_description"), 420)
    loc = snapshot.get("location") or {}
    loc_label = (loc.get("label") or "").strip()

    headline, meaning = _decision_headline(effective_vs, rs, flagged)
    concerns = _plain_concerns(
        snapshot=snapshot,
        flag_reason=flag_reason,
        text_only_reason_codes=text_only_reason_codes,
    )
    evidence_para = _evidence_paragraph(snapshot)

    parts: List[str] = []

    open_line = f"This {incident} report was submitted"
    if loc_label:
        open_line += f" from {loc_label}"
    parts.append(open_line + ".")
    if desc:
        parts.append(f'The citizen wrote: "{desc}"')

    parts.append("")
    parts.append(f"Automated result: {headline}. {meaning}")

    parts.append("")
    parts.append("Why:")
    if concerns:
        for i, c in enumerate(concerns, 1):
            parts.append(f"{i}. {c}")
    else:
        parts.append(
            "1. Screening completed without a single dominant concern on record."
        )

    parts.append("")
    parts.append(evidence_para)

    parts.append("")
    parts.append("Recommended next step:")
    if effective_vs == "verified":
        parts.append(
            "Proceed unless field knowledge contradicts this report."
        )
    elif effective_vs == "rejected" or rs == "rejected":
        parts.append(
            "Open the report, check whether the incident type fits the description, "
            "then confirm rejection or reopen if the citizen was misclassified."
        )
    else:
        parts.append(
            "Read the description and any media, confirm or correct the incident type, "
            "then verify or reject manually."
        )

    if (reviewer_note or "").strip():
        parts.append(f"\nNote on file: {reviewer_note.strip()}")

    return "\n".join(parts).strip()


def build_officer_verification_brief(
    *,
    snapshot: Dict[str, Any],
    verification_status: Optional[str],
    rule_status: Optional[str],
    is_flagged: Optional[bool],
    pattern_codes: List[str],
    pattern_explanations: List[str],
    flag_reason: Optional[str] = None,
    text_only_reason_codes: Optional[List[str]] = None,
) -> str:
    """Backward-compatible entry — returns unified plain summary (patterns ignored in text)."""
    del pattern_codes, pattern_explanations
    return build_unified_verification_summary(
        snapshot=snapshot,
        verification_status=verification_status,
        rule_status=rule_status,
        is_flagged=is_flagged,
        flag_reason=flag_reason,
        text_only_reason_codes=text_only_reason_codes,
    )


def build_officer_evidence_brief(snapshot: Dict[str, Any]) -> str:
    """Evidence is folded into the unified summary; keep empty to avoid duplicate UI blocks."""
    del snapshot
    return ""


def polish_unified_summary_with_llm(brief: str) -> str:
    """Optional Groq pass — one flowing summary, plain language, no codes."""
    if not brief or len(brief) < 40:
        return brief

    prompt = (
        "Rewrite this report screening summary for a district commander.\n"
        "Requirements:\n"
        "- Keep ONE unified narrative (do not split into separate 'evidence' and 'verification' documents).\n"
        "- Use simple, direct sentences. No technical codes (no INCIDENT_TEXT_MISMATCH, CONTEXT_MISMATCH, "
        "scorecard, ML label, trust band, unified blend, FINAL_REJECTED).\n"
        "- Say 'incident type mismatch' instead of codes when the description does not fit the category.\n"
        "- Keep: what the citizen reported, automated result (rejected / confirmed / pending review), "
        "clear reasons why, what was done with any photos/videos/audio, and the recommended next step.\n"
        "- Do not invent facts or change the outcome.\n"
        "- Return plain text only (short paragraphs, no ALL CAPS section headers).\n\n"
        f"INPUT:\n{brief}"
    )
    polished = _llm_rewrite_plain(prompt)
    return _strip_technical_tail(polished[:3800] if polished else brief)


def polish_officer_brief_with_llm(brief: str) -> str:
    return polish_unified_summary_with_llm(brief)


def _strip_technical_tail(text: str) -> str:
    for marker in (
        "Decision patterns:",
        "Pattern explanations:",
        "WHAT THE CITIZEN REPORTED",
        "AUTOMATED OUTCOME",
        "WHY THE SYSTEM REACHED",
        "WHAT WAS ANALYSED",
        "RECOMMENDED NEXT STEP FOR OFFICERS",
    ):
        idx = text.find(marker)
        if idx >= 0:
            text = text[:idx].strip()
    return text


def _llm_rewrite_plain(prompt: str) -> Optional[str]:
    import os

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key:
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_tokens=900,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return _strip_technical_tail(text)
        except Exception:
            pass
    return None
