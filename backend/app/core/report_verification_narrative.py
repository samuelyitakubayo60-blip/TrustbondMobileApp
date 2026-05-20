"""
Plain-language verification briefs for police officers.

Hotspot recommendations avoid jargon; report verification should do the same.
Technical pattern codes are kept for API/UI chips — not in the main narrative.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _truncate(text: Optional[str], limit: int) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    return f"{t[: limit - 3]}..."


def _outcome_labels(
    verification_status: str,
    rule_status: str,
    is_flagged: bool,
) -> Tuple[str, str]:
    """Return (headline, one-line meaning) for officers."""
    vs = (verification_status or "pending").strip().lower()
    rs = (rule_status or "").strip().lower()

    if vs == "verified":
        return (
            "Automatically verified",
            "Automated screening passed; the report is treated as credible unless an officer changes it.",
        )
    if vs == "rejected" or rs == "rejected":
        return (
            "Automatically rejected",
            "Automated screening failed; the report should not be trusted without reopening and review.",
        )
    if rs == "flagged" or is_flagged:
        return (
            "Needs police review (flagged)",
            "Automated screening found concerns; an officer must confirm or reject.",
        )
    if vs == "under_review":
        return (
            "Awaiting police review",
            "Not auto-confirmed; an officer must decide after reading the report and evidence.",
        )
    return (
        "Pending automated review",
        "Screening is incomplete or inconclusive; treat as unconfirmed until an officer acts.",
    )


def _checks_performed(snapshot: Dict[str, Any]) -> List[str]:
    """What the three analysis layers actually did (YOLO / TrustBond / rules+text)."""
    checks: List[str] = []
    evid = (snapshot.get("model_signals") or {}).get("evidence_ai") or {}
    ec = int(evid.get("evidence_count") or 0)
    nl = (snapshot.get("model_signals") or {}).get("natural_language") or {}
    fd = snapshot.get("final_decision") or {}

    checks.append("Written description, incident category, and device metadata")
    if ec > 0:
        checks.append(
            f"Uploaded media ({ec} file(s)): visual screening (object/scene cues where available)"
        )
    else:
        checks.append("No photo, video, or audio — decision relies on text and location only")

    if nl.get("mismatch") is True or nl.get("description_incident_similarity") is not None:
        checks.append("Text compared with expected wording for the selected incident type")

    if fd.get("trust_score") is not None or fd.get("label"):
        checks.append("TrustBond credibility model (overall trust score and authenticity label)")

    if snapshot.get("rules") or snapshot.get("scorecard_digest"):
        checks.append("Policy rules and threshold scorecard (auto-confirm vs send to officer)")

    return checks


def _ranked_reasons(
    pattern_codes: List[str],
    pattern_explanations: List[str],
    snapshot: Dict[str, Any],
) -> List[str]:
    """Plain-English causes, most important first."""
    code_to_exp: Dict[str, str] = {}
    for i, code in enumerate(pattern_codes):
        exp = ""
        if i < len(pattern_explanations):
            exp = pattern_explanations[i].split(": ", 1)[-1].strip()
        code_to_exp[code] = exp or code.replace("_", " ").lower()

    priority = [
        "CONTEXT_MISMATCH",
        "EVIDENCE_INCIDENT_MISMATCH",
        "LOW_TRUST_SCORE",
        "HIGH_TRUST_SCORE",
        "RULE_REJECTION",
        "RULE_FLAGGED",
        "SHORT_DESCRIPTION",
        "SHORT_DESCRIPTION_PARTIAL",
        "SHORT_DESCRIPTION_RESCUED",
        "LOCATION_OUT_OF_BOUNDARY",
        "LOCATION_CONFLICT",
        "TAMPERED_EVIDENCE",
        "SCREENSHOT_EVIDENCE",
        "INVALID_EVIDENCE_SOURCE",
        "DUPLICATE_REPORT",
        "UNCLEAR_DESCRIPTION",
        "HUMAN_REJECTION",
        "HUMAN_CONFIRMED",
        "RULES_PASSED",
        "FINAL_REJECTED",
        "FINAL_PENDING_REVIEW",
        "FINAL_CONFIRMED",
    ]

    reasons: List[str] = []
    seen: set[str] = set()

    def add(code: str) -> None:
        if code in seen or code not in code_to_exp:
            return
        seen.add(code)
        text = code_to_exp[code]
        if code == "FINAL_PENDING_REVIEW":
            return
        if code.startswith("FINAL_"):
            text = text[0].upper() + text[1:] if text else text
        reasons.append(text[0].upper() + text[1:] if text and not text[0].isupper() else text)

    for code in priority:
        add(code)
    for code in pattern_codes:
        add(code)

    fd = snapshot.get("final_decision") or {}
    trig = snapshot.get("rules") or {}
    flagged = trig.get("triggered") if isinstance(trig.get("triggered"), list) else []
    if flagged and not any("mismatch" in r.lower() for r in reasons):
        prim = str((flagged[0] or {}).get("explanation") or "").strip()
        if prim and prim not in seen:
            reasons.insert(0, prim[0].upper() + prim[1:] if prim else prim)

    ts = fd.get("trust_score")
    label = fd.get("label")
    if ts is not None and not any("trust" in r.lower() or "credibility" in r.lower() for r in reasons):
        try:
            score = float(ts)
            if score < 70:
                reasons.append(
                    f"Credibility score {score:.0f}/100 is below the usual automatic confirmation level."
                )
            elif score >= 70:
                reasons.append(
                    f"Credibility score {score:.0f}/100 supports treating the report as trustworthy."
                )
        except (TypeError, ValueError):
            pass
    if label in {"fake", "suspicious"} and not any("credibility" in r.lower() for r in reasons):
        reasons.append("The credibility model rated this submission as low authenticity.")

    return reasons[:6]


def build_officer_verification_brief(
    *,
    snapshot: Dict[str, Any],
    verification_status: Optional[str],
    rule_status: Optional[str],
    is_flagged: Optional[bool],
    pattern_codes: List[str],
    pattern_explanations: List[str],
) -> str:
    """
    Hotspot-style briefing: what happened, outcome, why, what was checked, next step.
    No scorecard bands, pattern codes, or model jargon in this text.
    """
    if not isinstance(snapshot, dict):
        return "Verification summary is unavailable for this report."

    vs = (verification_status or "pending").strip().lower()
    rs = (rule_status or "").strip().lower()
    flagged = bool(is_flagged)

    incident = (snapshot.get("incident_type") or "incident").strip()
    if incident.lower().startswith("the incident"):
        incident = "incident"
    desc = _truncate(snapshot.get("reporter_description"), 400)
    loc = snapshot.get("location") or {}
    loc_label = (loc.get("label") or "").strip()
    coords = (loc.get("coordinates") or "").strip()

    headline, meaning = _outcome_labels(vs, rs, flagged)
    reasons = _ranked_reasons(pattern_codes, pattern_explanations, snapshot)
    checks = _checks_performed(snapshot)

    parts: List[str] = []

    parts.append("WHAT THE CITIZEN REPORTED")
    line = f"A {incident} report was submitted"
    if loc_label:
        line += f" in {loc_label}"
    elif coords:
        line += f" at coordinates {coords}"
    parts.append(line + ".")
    if desc:
        parts.append(f"In their words: \"{desc}\"")

    parts.append("")
    parts.append("AUTOMATED OUTCOME")
    parts.append(f"{headline}. {meaning}")

    parts.append("")
    parts.append("WHY THE SYSTEM REACHED THIS CONCLUSION")
    if reasons:
        for i, reason in enumerate(reasons, 1):
            parts.append(f"{i}. {reason}")
    else:
        parts.append("1. Screening completed without a single dominant concern recorded.")

    parts.append("")
    parts.append("WHAT WAS ANALYSED")
    for c in checks:
        parts.append(f"• {c}")

    parts.append("")
    parts.append("RECOMMENDED NEXT STEP FOR OFFICERS")
    if vs == "verified":
        parts.append(
            "Proceed with normal police workflow; override only if field knowledge contradicts the report."
        )
    elif vs == "rejected" or rs == "rejected":
        parts.append(
            "Open the report, verify incident type and description, then confirm rejection or reopen if the citizen was misclassified."
        )
    else:
        parts.append(
            "Read the description and any media, confirm or correct the incident type, then verify or reject manually."
        )

    return "\n".join(parts).strip()


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
                return text
        except Exception:
            pass
    return None


def build_officer_evidence_brief(snapshot: Dict[str, Any]) -> str:
    """Short plain-language evidence paragraph (no model jargon)."""
    if not isinstance(snapshot, dict):
        return ""
    incident = (snapshot.get("incident_type") or "incident").strip()
    desc = _truncate(snapshot.get("reporter_description"), 320)
    evid = (snapshot.get("model_signals") or {}).get("evidence_ai") or {}
    ec = int(evid.get("evidence_count") or 0)

    parts: List[str] = [f"Evidence review for this {incident} report:"]
    if ec <= 0:
        parts.append(
            "No photos, videos, or audio were uploaded. Screening used the written description, "
            "GPS location, and automated text checks only."
        )
    else:
        parts.append(
            f"{ec} media file(s) were screened for basic authenticity and scene content where supported."
        )
    if desc:
        parts.append(f"The citizen stated: \"{desc}\"")
    parts.append(
        "Officers should treat media screening as advisory and confirm details in the field."
    )
    return " ".join(parts).strip()[:2000]


def polish_officer_brief_with_llm(brief: str) -> str:
    """Optional Groq pass — plain language only, no new facts."""
    if not brief or len(brief) < 40:
        return brief

    prompt = (
        "Rewrite this police verification briefing for a district commander.\n"
        "Keep the same facts: outcome, numbered reasons, what was analysed, next step.\n"
        "Use simple language like a hotspot patrol brief.\n"
        "Do NOT use technical codes (CONTEXT_MISMATCH, scorecard, unified blend, ML label, FINAL_PENDING).\n"
        "Do NOT invent evidence or change the outcome.\n"
        "Return plain text only.\n\n"
        f"INPUT:\n{brief}"
    )
    polished = _llm_rewrite_plain(prompt)
    return polished[:3500] if polished else brief
