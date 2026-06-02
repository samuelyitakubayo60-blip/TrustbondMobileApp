"""
LLM-generated hotspot recommendations.

Hotspot deployments use active tactical units from ``special_assignment_units``
(investigation-only codes like RIB/CID/LIB are excluded). Cases keep the full unit dropdown.

Priority chain: Groq → Gemini (JSON). Set ``HOTSPOT_LLM_STRICT=true`` to disable template
fallback when keys are configured (empty briefing on quota failure). Default uses templates
after LLM failure so the map stays usable.
"""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Groq: skip repeat calls only after permanent account errors
_groq_skip_reason: Optional[str] = None
_groq_skip_logged = False
_last_hotspot_llm_error: Optional[str] = None

# Gemini: backoff after quota/rate-limit errors to avoid log spam
_gemini_quota_until: float = 0.0
_gemini_quota_skip_logged = False

_PERMANENT_GROQ_MARKERS = (
    "organization_restricted",
    "invalid_api_key",
    "authentication",
    "permission_denied",
)


def _hotspot_llm_required() -> bool:
    """True when .env has GROQ and/or GEMINI keys."""
    return bool(
        os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    )


def _hotspot_llm_strict() -> bool:
    """When true and API keys are set, failed LLM calls yield empty text (no template fallback)."""
    return os.getenv("HOTSPOT_LLM_STRICT", "").strip().lower() in ("1", "true", "yes")


def _gemini_quota_blocked() -> bool:
    return time.time() < _gemini_quota_until


def _mark_gemini_quota_cooldown(exc: BaseException, *, seconds: int = 300) -> None:
    global _gemini_quota_until, _gemini_quota_skip_logged
    msg = str(exc)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg and "quota" not in msg.lower():
        return
    _gemini_quota_until = max(_gemini_quota_until, time.time() + seconds)
    if not _gemini_quota_skip_logged:
        logger.warning(
            "Gemini quota/rate limit hit; skipping Gemini hotspot calls for %s seconds. "
            "Enable billing or set HOTSPOT_LLM_STRICT=false (default) for template fallbacks.",
            seconds,
        )
        _gemini_quota_skip_logged = True


def _gemini_model_candidates() -> List[str]:
    candidates: List[str] = []
    deprecated = frozenset({"gemini-1.5-flash-8b", "gemini-1.5-flash"})
    for raw in (
        os.getenv("GEMINI_HOTSPOT_MODEL"),
        os.getenv("GEMINI_MODEL"),
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ):
        name = (raw or "").strip()
        if name and name not in candidates and name not in deprecated:
            candidates.append(name)
    return candidates or ["gemini-2.5-flash", "gemini-2.0-flash"]


def _parse_llm_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse model JSON; attempt light repair on truncated responses."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*", raw)
    if not match:
        return None
    fragment = match.group(0).rstrip()
    if fragment.count("{") > fragment.count("}"):
        fragment += "}"
    if fragment.count('"') % 2 == 1:
        fragment += '"'
    try:
        parsed = json.loads(fragment)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _disable_groq(reason: str) -> None:
    global _groq_skip_reason, _groq_skip_logged
    _groq_skip_reason = reason[:240]
    if not _groq_skip_logged:
        logger.warning(
            "Groq hotspot LLM unavailable for this process: %s",
            _groq_skip_reason,
        )
        _groq_skip_logged = True


# ── LAW ENFORCEMENT / TACTICAL BRIEFING ──────────────────────────────────────
# These functions produce POLICE-FACING operational content.
# Unit codes, deployment tactics, and concentration windows are appropriate here.
# Used by: hotspots.py (authenticated officer/admin endpoint)
# ──────────────────────────────────────────────────────────────────────────────

# Investigation / case-handover units — not for hotspot tactical deployment
_HOTSPOT_EXCLUDED_UNITS = frozenset({"RIB", "CID", "LIB"})

_UNIT_TACTICS: Dict[str, str] = {
    "RRU": "rapid armed response and tactical intervention",
    "DEU": "covert surveillance and undercover drug enforcement operations",
    "TPU": "traffic checkpoints, vehicle interdiction, and road patrol",
    "TRAFFIC": "traffic checkpoints, road patrol, and vehicle interdiction",
    "CPU": "uniformed community patrol and neighborhood liaison",
    "GENERAL_PATROL": "visible patrol, community engagement, and preventive deterrence",
    "ISU": "plainclothes intelligence gathering and covert surveillance",
    "K9": "K9-assisted search operations and suspect tracking",
    "AFU": "anti-fraud awareness operations and financial crime deterrence",
    "VPU": "protective patrol and victim safety escort operations",
    "QUICK_RESPONSE": "rapid deployment to active incidents and interdiction",
    "COUNTER_TERROR": "counter-terrorism screening and high-threat response",
    "FIRE_RESCUE": "fire and rescue response with police coordination",
}

_DEFAULT_HOTSPOT_UNITS: Dict[str, Dict[str, str]] = {
    code: {
        "name": {
            "AFU": "Anti-Fraud Unit (AFU)",
            "CPU": "Community Policing Unit (CPU)",
            "COUNTER_TERROR": "Counter Terror Unit",
            "DEU": "Drug Enforcement Unit (DEU)",
            "FIRE_RESCUE": "Fire & Rescue",
            "GENERAL_PATROL": "General Patrol",
            "ISU": "Intelligence & Surveillance Unit (ISU)",
            "K9": "K9 / Canine Unit",
            "QUICK_RESPONSE": "Quick Response Team",
            "RRU": "Rapid Response Unit (RRU)",
            "TRAFFIC": "Traffic Police",
            "TPU": "Traffic Police Unit (TPU)",
            "VPU": "Victim Protection Unit (VPU)",
        }[code],
        "tactic": _UNIT_TACTICS[code],
    }
    for code in _UNIT_TACTICS
    if code not in _HOTSPOT_EXCLUDED_UNITS
}

_registry_cache: Optional[Dict[str, Dict[str, str]]] = None

_CRIME_UNIT_HINTS: List[Tuple[re.Pattern[str], Dict[str, float]]] = [
    (
        re.compile(r"terror|explosive|bomb|extremist|hostage", re.I),
        {"COUNTER_TERROR": 9.0, "RRU": 2.0, "ISU": 1.5},
    ),
    (
        re.compile(r"traffic|accident|collision|reckless|speeding|road|vehicle|driving", re.I),
        {"TRAFFIC": 7.0, "TPU": 7.0, "GENERAL_PATROL": 1.0},
    ),
    (
        re.compile(r"theft|steal|stolen|robbery|burglary|pickpocket|snatch|break[\s-]?in", re.I),
        {"QUICK_RESPONSE": 5.0, "RRU": 4.0, "CPU": 4.0, "K9": 3.0},
    ),
    (
        re.compile(r"assault|fight|attack|violence|weapon|stabbing|shooting|murder", re.I),
        {"RRU": 8.0, "QUICK_RESPONSE": 6.0, "VPU": 2.0},
    ),
    (
        re.compile(r"drug|narcotic|traffick|substance|dealer", re.I),
        {"DEU": 9.0, "ISU": 2.0, "QUICK_RESPONSE": 2.0},
    ),
    (
        re.compile(r"fraud|scam|financial|cyber|identity", re.I),
        {"AFU": 9.0, "ISU": 2.0},
    ),
    (
        re.compile(r"domestic|gender|child|victim|abuse", re.I),
        {"VPU": 8.0, "CPU": 3.0},
    ),
    (
        re.compile(r"vandal|damage|destruction|graffiti|property", re.I),
        {"CPU": 5.0, "GENERAL_PATROL": 4.0},
    ),
    (
        re.compile(r"suspicious|loiter|stalk|harass|threat|intimidat", re.I),
        {"ISU": 7.0, "CPU": 3.0, "GENERAL_PATROL": 2.0},
    ),
    (
        re.compile(r"fire|rescue|burn", re.I),
        {"FIRE_RESCUE": 9.0, "QUICK_RESPONSE": 2.0},
    ),
]


def load_hotspot_deployment_units(db: Any = None) -> Dict[str, Dict[str, str]]:
    """Tactical deployment registry: built-in codes merged with active DB rows."""
    global _registry_cache
    merged: Dict[str, Dict[str, str]] = dict(_DEFAULT_HOTSPOT_UNITS)
    if db is not None:
        try:
            from app.models.special_assignment_unit import SpecialAssignmentUnit

            rows = (
                db.query(SpecialAssignmentUnit)
                .filter(SpecialAssignmentUnit.is_active.is_(True))
                .order_by(SpecialAssignmentUnit.unit_name)
                .all()
            )
            for row in rows:
                code = (row.unit_code or "").strip().upper()
                if not code or code in _HOTSPOT_EXCLUDED_UNITS:
                    continue
                merged[code] = {
                    "name": (row.unit_name or code).strip(),
                    "tactic": _UNIT_TACTICS.get(
                        code,
                        (row.description or "targeted security operations").strip()[:120],
                    ),
                }
            _registry_cache = merged
            return merged
        except Exception as exc:
            logger.warning("Could not load special_assignment_units for hotspots: %s", exc)
    if _registry_cache:
        return _registry_cache
    return merged


def clear_hotspot_units_registry_cache() -> None:
    global _registry_cache
    _registry_cache = None


def _resolve_unit(unit: Optional[str], registry: Dict[str, Dict[str, str]]) -> Optional[str]:
    if not unit or not registry:
        return None
    raw = unit.strip().upper().replace(" ", "_")
    if raw in registry:
        return raw
    if raw in _HOTSPOT_EXCLUDED_UNITS:
        return None
    for code in registry:
        if code in raw or raw in code:
            return code
    return None


def _unit_tactic(unit_code: Optional[str], registry: Dict[str, Dict[str, str]]) -> str:
    code = _resolve_unit(unit_code, registry) or "GENERAL_PATROL"
    if code in registry:
        return registry[code]["tactic"]
    return _UNIT_TACTICS.get(code, "targeted security operations")


def _score_crime_text(text: str, registry: Dict[str, Dict[str, str]]) -> Dict[str, float]:
    scores = {code: 0.0 for code in registry}
    t = (text or "").strip()
    if not t:
        return scores
    for pattern, weights in _CRIME_UNIT_HINTS:
        if pattern.search(t):
            for code, w in weights.items():
                if code in registry:
                    scores[code] = scores.get(code, 0.0) + w
    return scores


def _pick_hotspot_deployment_plan(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    incident_mix: Optional[Dict[str, int]],
    registry: Dict[str, Dict[str, str]],
    incident_type_unit_hint: Optional[str] = None,
    # Improvement 7 — additional multi-factor inputs
    trend_direction: Optional[str] = None,
    severity_score: Optional[float] = None,
    lifecycle_state: Optional[str] = None,
    nearby_cluster_count: int = 0,
    time_of_day_peak: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Multi-factor unit selection (Improvement 7).

    Scoring layers:
      L1 – Crime-text matching (existing keyword regex table)
      L2 – Volume multiplier (more incidents → boost primary crime unit)
      L3 – Severity multiplier (sev ≥ 7 → +20 % on specialist unit)
      L4 – Trend multiplier (rising → +2.0 on rapid/response units)
      L5 – Lifecycle multiplier (escalating → +3.0 on RRU/QUICK_RESPONSE)
      L6 – Nearby clusters (≥ 2 → boost CPU/GENERAL_PATROL for area coordination)
      L7 – Mixed-hotspot premium (multi-crime → boost QUICK_RESPONSE + CPU)
      L8 – Incident-type DB hint override
      L9 – Classification guardrail (critical/active always boost fast-response)

    Support unit: selected when its score ≥ 35 % of primary (lowered from 40 %)
    to encourage dual-unit recommendations on higher-severity hotspots.
    """
    totals: Dict[str, float] = {code: 0.0 for code in registry}

    # L1 + L2 — crime text with volume weighting
    if incident_mix:
        for name, count in incident_mix.items():
            c = max(1, int(count or 0))
            for code, w in _score_crime_text(name, registry).items():
                totals[code] = totals.get(code, 0.0) + w * c
    elif dominant_crime:
        for code, w in _score_crime_text(dominant_crime, registry).items():
            totals[code] = totals.get(code, 0.0) + w * max(1, incident_count)

    # L3 — severity multiplier
    sev = float(severity_score or 0.0)
    if sev >= 7.0:
        # High-severity: boost RRU, QUICK_RESPONSE, and the highest-scored crime unit
        for code in ("RRU", "QUICK_RESPONSE", "VPU"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + (sev - 5.0) * 0.6
    elif sev >= 5.0:
        # Moderate severity: modest boost on specialist units already high-scored
        top_code = max(totals, key=totals.get) if totals else None
        if top_code and top_code in registry:
            totals[top_code] = totals.get(top_code, 0.0) + 1.0

    # L4 — trend multiplier
    trend = (trend_direction or "stable").lower()
    if trend == "rising":
        for code in ("RRU", "QUICK_RESPONSE", "DEU"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 2.0
    elif trend == "falling":
        # Declining trend — community policing is sufficient
        for code in ("CPU", "GENERAL_PATROL"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 1.5

    # L5 — lifecycle multiplier
    lc = (lifecycle_state or "active").lower()
    if lc == "escalating":
        for code in ("RRU", "QUICK_RESPONSE"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 3.0
    elif lc == "declining":
        for code in ("CPU", "GENERAL_PATROL"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 2.0

    # L6 — nearby clusters → area coordination
    if nearby_cluster_count >= 2:
        for code in ("CPU", "GENERAL_PATROL", "QUICK_RESPONSE"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 1.5

    # L7 — multi-crime zone premium
    if cluster_kind == "mixed_hotspot" and incident_count >= 6:
        for code in ("QUICK_RESPONSE", "CPU"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 2.0
        if "ISU" in registry:
            totals["ISU"] = totals.get("ISU", 0.0) + 1.5

    # L8 — incident-type DB unit hint
    hint = _resolve_unit(incident_type_unit_hint, registry)
    if hint:
        totals[hint] = totals.get(hint, 0.0) + 5.0

    # Ensure a default when no crime text scored
    if sum(totals.values()) < 0.1:
        totals["GENERAL_PATROL"] = totals.get("GENERAL_PATROL", 0.0) + 3.0

    # L9 — critical/active classification guardrail
    cls = (classification or "").strip().lower()
    if cls in {"critical", "active"}:
        for code in ("RRU", "QUICK_RESPONSE"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 2.5

    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    primary_code = ranked[0][0] if ranked else "GENERAL_PATROL"
    support_code: Optional[str] = None
    # Support unit threshold lowered to 35 % for escalating/critical clusters
    support_threshold = 0.30 if (lc == "escalating" or cls == "critical") else 0.35
    if len(ranked) > 1 and ranked[1][1] >= ranked[0][1] * support_threshold:
        support_code = ranked[1][0]
        if support_code == primary_code and len(ranked) > 2:
            support_code = ranked[2][0]

    units_out: List[Dict[str, str]] = [
        {
            "unit_code": primary_code,
            "unit_name": registry[primary_code]["name"],
            "role": "primary",
        },
    ]
    if support_code and support_code != primary_code:
        units_out.append(
            {
                "unit_code": support_code,
                "unit_name": registry[support_code]["name"],
                "role": "support",
            }
        )

    return {
        "primary_code": primary_code,
        "primary_name": registry[primary_code]["name"],
        "support_code": support_code,
        "support_name": registry[support_code]["name"] if support_code else None,
        "recommended_units": units_out,
        # Expose the scoring vector for explainability
        "unit_scores": {k: round(v, 2) for k, v in ranked[:6]},
    }


def _theft_incident_weight(
    dominant_crime: Optional[str],
    incident_mix: Optional[Dict[str, int]],
) -> int:
    total = 0
    if incident_mix:
        for name, count in incident_mix.items():
            if re.search(r"theft|robbery|burglary|steal|stolen|pickpocket", name, re.I):
                total += int(count or 0)
    elif dominant_crime and re.search(
        r"theft|robbery|burglary|steal|stolen|pickpocket", dominant_crime, re.I
    ):
        total = 1
    return total


def _build_citizen_advisory(
    *,
    area_label: Optional[str],
    dominant_crime: Optional[str],
    incident_count: int,
    classification: str,
    cluster_kind: str,
    incident_mix: Optional[Dict[str, int]],
    verified_report_count: int = 0,
    cluster_case_context: Optional[Dict[str, Any]] = None,
    time_window_hours: Optional[int] = None,
) -> str:
    """
    CITIZEN-FACING template advisory (plain language, time-aware).

    Audience: ordinary residents, commuters, and members of the public.
    Purpose : inform them of nearby risk and encourage TrustBond reporting.
    Rules   : no police unit names, no tactical language, no jargon.
              Empowering and calm — help people act, not panic.

    This function is the template fallback used by generate_citizen_advisory()
    when no LLM key is configured.  It is SEPARATE from _template_fallback()
    which is the law-enforcement-only tactical briefing template.
    """
    area = (area_label or "your area").strip()
    crime = (dominant_crime or "incidents").strip().lower()
    cls = (classification or "").strip().lower()
    ctx = cluster_case_context or {}
    t = _time_window_label(time_window_hours)   # e.g. "in the past 24 hours"
    n = incident_count
    count_phrase = f"{n} {'report' if n == 1 else 'reports'}"
    theft_count = _theft_incident_weight(dominant_crime, incident_mix)
    is_theft_cluster = theft_count >= 1 or bool(
        re.search(r"theft|robbery|burglary|steal", crime, re.I)
    )

    if ctx.get("suspect_apprehended") and is_theft_cluster:
        return (
            f"A suspect linked to theft reports near {area} has been apprehended. "
            f"Thank you to everyone who reported — your contributions made a difference. "
            f"Please continue to secure valuables and report anything new or suspicious through TrustBond."
        )

    if ctx.get("closed_cases", 0) >= 1 and is_theft_cluster:
        return (
            f"An investigation tied to theft reports near {area} has been closed. "
            f"Stay alert, secure your property, and report new suspicious activity through TrustBond."
        )

    if is_theft_cluster:
        if cls in ("critical", "active") and n >= 5:
            return (
                f"{n} theft incidents have been reported near {area} {t} — this is an elevated-risk zone right now. "
                f"Keep phones and bags out of sight, avoid walking alone especially after dark, and lock your property. "
                f"Report any suspicious activity or attempted theft through TrustBond immediately."
            )
        urgency = "There is elevated risk" if cls in ("critical", "active") else "There have been reports"
        return (
            f"{urgency} of theft near {area} — {count_phrase} {t}. "
            f"Secure your valuables, keep your phone and bag close, and avoid isolated spots especially at night. "
            f"Report any suspicious behaviour through TrustBond right away."
        )

    if re.search(r"traffic|accident|road|vehicle", crime, re.I):
        if n >= 3:
            return (
                f"{count_phrase} of traffic incidents near {area} {t} — drive with extra caution in this area. "
                f"Slow down, watch for pedestrians, and report dangerous driving or road hazards through TrustBond."
            )
        return (
            f"A traffic incident was reported near {area} {t}. "
            f"Drive carefully in this area, stay alert, and report any dangerous driving through TrustBond."
        )

    if re.search(r"assault|fight|violence|attack", crime, re.I):
        if cls in ("critical", "active"):
            return (
                f"{count_phrase} of violent incidents near {area} {t} — avoid this area if possible, especially at night. "
                f"Stay in well-lit and populated places, move in groups, and report anything alarming through TrustBond."
            )
        return (
            f"Reports of violent incidents near {area} — {count_phrase} {t}. "
            f"Avoid confrontations, stay in well-lit areas, and report anything that feels unsafe through TrustBond."
        )

    if cls in {"critical"} or (cls == "active" and n >= 3):
        return (
            f"There is high risk of incidents near {area} — {count_phrase} of {crime} reported {t}. "
            f"Be attentive, avoid unnecessary movement in the area, look out for your neighbours, "
            f"and report any unusual behaviour or incident immediately through TrustBond."
        )

    if cls in {"active", "high"} or cluster_kind == "mixed_hotspot":
        mix_note = ""
        if incident_mix and len(incident_mix) > 1:
            top_types = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:2]
            mix_note = f" ({' and '.join(k for k, _ in top_types)})"
        return (
            f"Multiple suspicious cases{mix_note} were reported near {area} {t} ({count_phrase}). "
            f"Stay alert and report any incident or unusual behaviour through TrustBond."
        )

    if verified_report_count >= max(2, n // 2) and n >= 2:
        return (
            f"Verified incidents have been reported near {area} {t}. "
            f"Stay vigilant and report anything new or concerning through TrustBond."
        )

    return (
        f"Incident activity has been noted near {area} {t} ({count_phrase}). "
        f"Remain observant and report anything unusual through TrustBond."
    )


def _suggest_duration_hours(classification: str, cluster_kind: str) -> int:
    if cluster_kind == "mixed_hotspot" or classification == "critical":
        return 48
    if classification == "active":
        return 24
    if classification == "emerging":
        return 12
    return 6


def _concentrate_window(peak_time: Optional[str], duration_hours: int) -> Optional[str]:
    if not peak_time:
        return None
    try:
        start_str = peak_time.split("–")[0].strip()
        peak_hour = int(start_str.split(":")[0])
    except Exception:
        return None

    buf = 4 if duration_hours >= 48 else 3 if duration_hours >= 24 else 2 if duration_hours >= 12 else 1
    c_start = (peak_hour - buf) % 24
    c_end = (peak_hour + 2 + buf) % 24
    return f"{c_start:02d}:00–{c_end:02d}:00"


def _mix_summary(incident_mix: Optional[Dict[str, int]], dominant_crime: Optional[str]) -> str:
    if incident_mix:
        top = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:4]
        return ", ".join(f"{name} ({cnt})" for name, cnt in top)
    return dominant_crime or "mixed incidents"


def _build_prompt(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    peak_time: Optional[str],
    plan: Dict[str, Any],
    operation_hours: int,
    concentrate_window: Optional[str],
    citizen_advisory: str,
    registry: Dict[str, Dict[str, str]],
    cluster_evolution: Optional[Dict[str, Any]] = None,
) -> str:
    area = area_label or "the area"
    mix_lines = ""
    if incident_mix:
        sorted_mix = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)
        mix_lines = "\n".join(f"  - {name}: {count}" for name, count in sorted_mix)

    primary = plan["primary_name"]
    support = plan.get("support_name")
    units_line = primary + (f" with {support} support" if support else "")
    tactic = _unit_tactic(plan["primary_code"], registry)
    allowed_units = ", ".join(sorted(u["name"] for u in registry.values()))
    conc_note = (
        f"Concentrate operations between {concentrate_window}."
        if concentrate_window
        else "Distribute patrol evenly across the operation period."
    )

    # Build cluster evolution section
    evo = cluster_evolution or {}
    lifecycle   = evo.get("lifecycle_state") or "unknown"
    trend       = evo.get("trend_direction") or "stable"
    crime_grp   = evo.get("crime_group") or "general"
    confidence  = evo.get("cluster_confidence")
    severity    = evo.get("severity_score")
    t_intensity = evo.get("temporal_intensity")
    nearby      = evo.get("nearby_clusters", 0)
    composition = evo.get("composition") or {}

    conf_pct    = f"{round(float(confidence) * 100)}%" if confidence is not None else "unknown"
    sev_str     = f"{round(float(severity), 1)}/10" if severity is not None else "unknown"
    intensity_str = f"{round(float(t_intensity), 2)} incidents/hr" if t_intensity is not None else "unknown"

    trend_note = {
        "rising":  "⚠ Incident rate is RISING — escalation likely if unaddressed.",
        "falling": "✓ Incident rate is declining — current measures may be working.",
        "stable":  "→ Incident rate is stable — sustained presence needed.",
    }.get(trend, "→ Trend unknown.")

    nearby_note = (
        f"{nearby} other active cluster(s) within ~2 km — coordinated area response may be needed."
        if nearby > 0
        else "No other active clusters nearby — localized response is sufficient."
    )

    comp_lines = ""
    if composition:
        comp_sorted = sorted(composition.items(), key=lambda x: x[1], reverse=True)
        comp_lines = ", ".join(f"{k}({v})" for k, v in comp_sorted)

    return f"""You are a police intelligence analyst for Rwanda National Police (Musanze District).
Write a UNIQUE operational briefing for this specific cluster — do not reuse generic wording.

── HOTSPOT DATA ──────────────────────────────────────────────────
- Classification       : {classification}
- Cluster type         : {cluster_kind}
- Location             : {area}
- Total incidents      : {incident_count}
- Dominant crime       : {dominant_crime or "mixed"}
- Incident mix         :
{mix_lines if mix_lines else "  - " + (dominant_crime or "unknown")}
- Peak activity        : {peak_time or "unknown"}

── CLUSTER EVOLUTION ─────────────────────────────────────────────
- Lifecycle state      : {lifecycle}   (emerging → active → escalating → stable → declining)
- Trend direction      : {trend}   {trend_note}
- Crime group          : {crime_grp}
- Severity score       : {sev_str}
- Temporal intensity   : {intensity_str}
- Cluster confidence   : {conf_pct}
- Full composition     : {comp_lines or dominant_crime or "unknown"}
- Area pressure        : {nearby_note}

── RESPONSE PLAN ─────────────────────────────────────────────────
- Deploy units         : {units_line}
- Primary tactic       : {tactic}
- Operation duration   : {operation_hours} hours
- Concentration window : {conc_note}
- Citizen message hint : {citizen_advisory}

Allowed deployment units (pick from this list only; do NOT use RIB/CID/LIB):
  {allowed_units}

Return JSON only:
{{
  "recommendation": "<20-40 words: name primary unit, tactic, duration, concentration window — reference the trend and lifecycle state>",
  "narrative": "<60-90 words: describe the cluster evolution in {area}, reference the trend direction, severity, nearby clusters if any, and why the chosen units fit this specific crime mix>",
  "status": "<escalation_likely | monitor_growth | emerging_trend | security_alert>",
  "citizen_advisory": "<Internal hint only — 1-2 sentences a community liaison officer could relay to residents; plain language, no unit codes, no tactical details>"
}}

Rules:
- recommendation and narrative are LAW ENFORCEMENT content — tactical language, unit names, and operational details are appropriate here.
- citizen_advisory is an INTERNAL COMMUNITY MESSAGE HINT for officers — plain language, no unit codes, no classified tactics. It is NOT published directly to the public; the public receives a separately generated civilian advisory.
- recommendation MUST name "{primary}" (and "{support}" if support).
- If trend is "rising" or lifecycle is "escalating", reflect urgency in the recommendation.
- If nearby_clusters > 1, suggest coordinated multi-location response.
- Use real numbers and place names. No markdown.
"""


def _call_groq(prompt: str) -> Optional[Dict[str, Any]]:
    if _groq_skip_reason:
        return None
    if os.getenv("HOTSPOT_SKIP_GROQ", "").strip().lower() in ("1", "true", "yes"):
        return None
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("GROQ_HOTSPOT_MODEL", "llama-3.3-70b-versatile"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.45,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        err = str(exc).lower()
        if any(marker in err for marker in _PERMANENT_GROQ_MARKERS):
            _disable_groq(str(exc))
        else:
            logger.warning("Groq hotspot recommendation failed: %s", exc)
        return None


_gemini_sdk_missing_logged = False


def verify_google_genai_installed() -> bool:
    """True if ``google-genai`` package is importable (installed on deploy)."""
    try:
        from google import genai  # noqa: F401
        from google.genai import types  # noqa: F401
        return True
    except ImportError:
        return False


def gemini_generate_json(
    prompt: str,
    api_key: str,
    model_name: str,
    *,
    max_tokens: int = 700,
    temperature: float = 0.35,
) -> Optional[Dict[str, Any]]:
    """Call Gemini via ``google.genai`` (installed as ``google-genai`` on deploy)."""
    global _gemini_sdk_missing_logged
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        if not _gemini_sdk_missing_logged:
            logger.error(
                "google-genai is not installed. Add google-genai to requirements.txt and redeploy."
            )
            _gemini_sdk_missing_logged = True
        return None

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            return None
        parsed = _parse_llm_json(text)
        if parsed is None:
            logger.warning("Gemini (%s) returned invalid JSON", model_name)
        return parsed
    except Exception as exc:
        _mark_gemini_quota_cooldown(exc)
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            logger.warning("Gemini (%s) quota exceeded", model_name)
        else:
            logger.warning("Gemini (%s) failed: %s", model_name, exc)
        return None


def _call_gemini_model(prompt: str, model_name: str, api_key: str) -> Optional[Dict[str, Any]]:
    return gemini_generate_json(
        prompt, api_key, model_name, max_tokens=700, temperature=0.35
    )


def _call_gemini(prompt: str) -> Optional[Dict[str, Any]]:
    global _last_hotspot_llm_error, _gemini_quota_skip_logged
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    if _gemini_quota_blocked():
        _last_hotspot_llm_error = "Gemini quota cooldown active"
        return None

    errors: List[str] = []
    for model_name in _gemini_model_candidates():
        parsed = _call_gemini_model(prompt, model_name, api_key)
        if parsed and parsed.get("recommendation") and parsed.get("narrative"):
            logger.info("Hotspot briefing generated via Gemini model %s", model_name)
            _gemini_quota_skip_logged = False
            return parsed
        errors.append(model_name)
        if _gemini_quota_blocked():
            break

    _last_hotspot_llm_error = (
        f"Gemini failed for models: {', '.join(errors)}"
        if errors
        else "Gemini returned empty JSON"
    )
    if not _gemini_quota_blocked():
        logger.warning("%s", _last_hotspot_llm_error)
    return None


def _call_hotspot_llm(prompt: str) -> Optional[Dict[str, Any]]:
    global _last_hotspot_llm_error
    _last_hotspot_llm_error = None

    if os.getenv("GEMINI_API_KEY", "").strip():
        gemini_result = _call_gemini(prompt)
        if gemini_result and gemini_result.get("recommendation") and gemini_result.get("narrative"):
            return gemini_result

    result = _call_groq(prompt)
    if result and result.get("recommendation") and result.get("narrative"):
        return result
    if _groq_skip_reason and not _last_hotspot_llm_error:
        _last_hotspot_llm_error = f"Groq: {_groq_skip_reason}"
    elif not _last_hotspot_llm_error:
        _last_hotspot_llm_error = "No LLM provider returned valid JSON"
    return None


_recommendation_cache: Dict[tuple, Dict[str, Any]] = {}


def clear_recommendation_cache() -> int:
    count = len(_recommendation_cache)
    _recommendation_cache.clear()
    logger.info("Recommendation cache cleared (%d entries removed).", count)
    return count


def _cache_key(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    peak_time: Optional[str],
    mix_tuple: tuple,
    primary_code: str,
    cluster_case_context: Optional[Dict[str, Any]] = None,
) -> tuple:
    ctx = cluster_case_context or {}
    return (
        classification,
        incident_count,
        dominant_crime,
        cluster_kind,
        area_label,
        peak_time,
        mix_tuple,
        primary_code,
        ctx.get("suspect_apprehended"),
        ctx.get("closed_cases"),
        ctx.get("linked_cases"),
    )


def _template_fallback(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    peak_time: Optional[str],
    plan: Dict[str, Any],
    operation_hours: int,
    concentrate_window: Optional[str],
    citizen_advisory: str,
    registry: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """
    LAW-ENFORCEMENT-ONLY tactical template (used when no LLM key is configured).

    Audience: police officers and security dispatchers.
    Purpose : recommend which unit to deploy, for how long, and what tactic to use.
    Rules   : tactical and operational language is appropriate here.
              Unit codes, deployment instructions, and concentration windows are expected.

    The `citizen_advisory` field this returns is sourced from _build_citizen_advisory()
    and is kept as an INTERNAL HINT for officers.  It is NOT published to the public;
    the public advisory is generated separately via generate_citizen_advisory().
    """
    area = area_label or "this area"
    crime = (dominant_crime or "incidents").strip()
    primary = plan["primary_name"]
    pcode = plan["primary_code"]
    support = plan.get("support_name")
    tactic = _unit_tactic(pcode, registry)
    dur = f"{operation_hours}-hour"
    conc = f", concentrating efforts between {concentrate_window}" if concentrate_window else ""
    peak_note = f" Peak activity is around {peak_time}." if peak_time else ""
    mix_txt = _mix_summary(incident_mix, dominant_crime)
    support_clause = f" Coordinate with {support}." if support else ""

    rec = (
        f"Deploy {primary} for a {dur} {tactic} operation in {area}{conc}."
        f"{support_clause}"
    )

    if pcode in ("TRAFFIC", "TPU"):
        nar = (
            f"Traffic-related incidents in {area} total {incident_count} verified reports ({mix_txt})."
            f"{peak_note} Road enforcement and checkpoint presence should reduce repeat collisions and unsafe driving."
        )
        status = "monitor_growth" if classification != "critical" else "escalation_likely"
    elif pcode == "DEU":
        nar = (
            f"Drug-related activity in {area} ({incident_count} incidents; {mix_txt}) needs targeted enforcement."
            f"{peak_note} Covert and overt operations together can disrupt supply patterns."
        )
        status = "escalation_likely" if classification in {"critical", "active"} else "monitor_growth"
    elif pcode in ("RRU", "QUICK_RESPONSE") and re.search(
        r"assault|violence|theft|robbery", crime, re.I
    ):
        nar = (
            f"High-impact incidents in {area} ({incident_count} reports; {mix_txt}) require rapid tactical response."
            f"{peak_note} Visible deployment during peak hours can prevent further harm or property loss."
        )
        status = "escalation_likely" if classification in {"critical", "active"} else "monitor_growth"
    elif pcode == "AFU":
        nar = (
            f"Fraud or financial-crime reports in {area} ({mix_txt}) need specialist follow-up and public awareness."
            f"{peak_note} Coordinated outreach can limit further victim losses."
        )
        status = "monitor_growth"
    elif pcode == "VPU":
        nar = (
            f"Vulnerable-person incidents in {area} ({incident_count} reports; {mix_txt}) need protective response."
            f"{peak_note} Victim-centred patrol reduces repeat harm and builds trust."
        )
        status = "monitor_growth"
    elif pcode == "ISU":
        nar = (
            f"Suspicious or intelligence-sensitive patterns in {area} ({mix_txt}) warrant discreet assessment."
            f"{peak_note} Intelligence-led tasks should inform visible patrol timing."
        )
        status = "security_alert" if cluster_kind == "mixed_hotspot" else "monitor_growth"
    elif pcode == "K9":
        nar = (
            f"Search and tracking needs in {area} ({incident_count} incidents; {mix_txt}) suit canine support."
            f"{peak_note} K9 teams can strengthen interdiction during peak activity windows."
        )
        status = "monitor_growth"
    elif pcode == "COUNTER_TERROR":
        nar = (
            f"Elevated threat indicators in {area} ({mix_txt}) require counter-terror coordination."
            f"{peak_note} Treat the cluster as high sensitivity until screening tasks complete."
        )
        status = "security_alert"
    else:
        nar = (
            f"Community policing needs in {area} ({incident_count} incidents; {mix_txt}) are best met with steady presence."
            f"{peak_note} Patrol visibility and local engagement can stabilise the area."
        )
        status = "emerging_trend" if classification in {"low_activity", "emerging"} else "monitor_growth"

    if cluster_kind == "mixed_hotspot":
        status = "security_alert"
        nar += " Multiple crime types overlap, so coordinated unit coverage is required."

    return {
        "recommendation": rec,
        "narrative": nar,
        "status": status,
        "citizen_advisory": citizen_advisory,
    }


def _package_result(
    body: Dict[str, Any],
    plan: Dict[str, Any],
    operation_hours: int,
    concentrate_window: Optional[str],
    *,
    citizen_advisory_hint: str = "",
) -> Dict[str, Any]:
    llm_citizen = str(body.get("citizen_advisory", "")).strip()
    citizen = llm_citizen or (citizen_advisory_hint or "").strip()
    return {
        "recommendation": str(body.get("recommendation", "")).strip(),
        "narrative": str(body.get("narrative", "")).strip(),
        "status": str(body.get("status", "monitor_growth")).strip(),
        "citizen_advisory": citizen,
        "recommended_unit": plan["primary_code"],
        "recommended_unit_name": plan["primary_name"],
        "recommended_units": plan["recommended_units"],
        "operation_hours": operation_hours,
        "concentrate_window": concentrate_window,
    }


def gather_cluster_case_context(db: Any, report_ids: List[Any]) -> Dict[str, Any]:
    """Linked case outcomes for citizen advisories (LIB/RIB investigation is separate)."""
    if not db or not report_ids:
        return {}
    try:
        from app.models.case import Case, CaseReport

        cases = (
            db.query(Case)
            .join(CaseReport, CaseReport.case_id == Case.case_id)
            .filter(CaseReport.report_id.in_(list(report_ids)))
            .all()
        )
    except Exception as exc:
        logger.debug("Could not load cluster case context: %s", exc)
        return {}

    closed = 0
    suspect_apprehended = False
    apprehend_markers = (
        "apprehend",
        "arrest",
        "arrested",
        "caught",
        "custody",
        "suspect_identified",
        "suspect identified",
    )
    for case in cases:
        status = (getattr(case, "status", None) or "").strip().lower()
        if status in {"closed", "resolved"} or getattr(case, "closed_at", None):
            closed += 1
        outcome = (getattr(case, "outcome", None) or "").strip().lower()
        if any(m in outcome for m in apprehend_markers):
            suspect_apprehended = True

    return {
        "linked_cases": len(cases),
        "closed_cases": closed,
        "suspect_apprehended": suspect_apprehended,
    }


def generate_recommendation(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str] = None,
    incident_mix: Optional[Dict[str, int]] = None,
    peak_time: Optional[str] = None,
    recommended_unit: Optional[str] = None,
    verified_report_count: int = 0,
    deployment_units: Optional[Dict[str, Dict[str, str]]] = None,
    cluster_case_context: Optional[Dict[str, Any]] = None,
    cluster_evolution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Hotspot briefing: rule-picked units + Groq/Gemini JSON text when API keys are set.
    No template fallback when ``GROQ_API_KEY`` / ``GEMINI_API_KEY`` are configured.

    Improvement 7: passes trend_direction, severity_score, lifecycle_state,
    and nearby_cluster_count from cluster_evolution into _pick_hotspot_deployment_plan
    for multi-factor unit scoring.
    """
    evo = cluster_evolution or {}
    registry = deployment_units or load_hotspot_deployment_units()
    plan = _pick_hotspot_deployment_plan(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        cluster_kind=cluster_kind,
        incident_mix=incident_mix,
        registry=registry,
        incident_type_unit_hint=recommended_unit,
        # Improvement 7 — multi-factor inputs from cluster evolution
        trend_direction=evo.get("trend_direction"),
        severity_score=float(evo.get("severity_score") or 0.0),
        lifecycle_state=evo.get("lifecycle_state"),
        nearby_cluster_count=int(evo.get("nearby_clusters") or 0),
    )

    operation_hours = _suggest_duration_hours(classification, cluster_kind)
    concentrate_window = _concentrate_window(peak_time, operation_hours)
    citizen_advisory_hint = _build_citizen_advisory(
        area_label=area_label,
        dominant_crime=dominant_crime,
        incident_count=incident_count,
        classification=classification,
        cluster_kind=cluster_kind,
        incident_mix=incident_mix,
        verified_report_count=verified_report_count,
        cluster_case_context=cluster_case_context,
    )

    mix_tuple = tuple(sorted((incident_mix or {}).items()))
    key = _cache_key(
        classification,
        incident_count,
        dominant_crime,
        cluster_kind,
        area_label,
        peak_time,
        mix_tuple,
        plan["primary_code"],
        cluster_case_context,
    )
    if key in _recommendation_cache:
        return _recommendation_cache[key]

    prompt = _build_prompt(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        cluster_kind=cluster_kind,
        area_label=area_label,
        incident_mix=incident_mix,
        peak_time=peak_time,
        plan=plan,
        operation_hours=operation_hours,
        concentrate_window=concentrate_window,
        citizen_advisory=citizen_advisory_hint,
        registry=registry,
        cluster_evolution=cluster_evolution,
    )

    result = _call_hotspot_llm(prompt)
    if result and result.get("recommendation") and result.get("narrative"):
        if not result.get("citizen_advisory") and not _hotspot_llm_required():
            result["citizen_advisory"] = citizen_advisory_hint
        clean = _package_result(
            result,
            plan,
            operation_hours,
            concentrate_window,
            citizen_advisory_hint=citizen_advisory_hint,
        )
        _recommendation_cache[key] = clean
        return clean

    if _hotspot_llm_required() and _hotspot_llm_strict():
        logger.error(
            "Hotspot briefing requires LLM output but generation failed. %s",
            _last_hotspot_llm_error or "No provider returned valid JSON.",
        )
        return _package_result(
            {
                "recommendation": "",
                "narrative": "",
            "status": "monitor_growth",
                "citizen_advisory": "",
            },
            plan,
            operation_hours,
            concentrate_window,
            citizen_advisory_hint=citizen_advisory_hint,
        )

    if _hotspot_llm_required() and _last_hotspot_llm_error:
        logger.warning(
            "Hotspot LLM unavailable; using template briefing. %s",
            _last_hotspot_llm_error,
        )

    fallback = _template_fallback(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        cluster_kind=cluster_kind,
        area_label=area_label,
        incident_mix=incident_mix,
        peak_time=peak_time,
        plan=plan,
        operation_hours=operation_hours,
        concentrate_window=concentrate_window,
        citizen_advisory=citizen_advisory_hint,
        registry=registry,
    )
    clean = _package_result(
        fallback,
        plan,
        operation_hours,
        concentrate_window,
        citizen_advisory_hint=citizen_advisory_hint,
    )
    _recommendation_cache[key] = clean
    return clean


# ── PUBLIC / CITIZEN ADVISORY ────────────────────────────────────────────────
# These functions produce CIVILIAN-FACING text only.
# They must NEVER mention police units, tactics, or operational plans.
# Used by: public_hotspots.py (no-auth mobile endpoint)
# ──────────────────────────────────────────────────────────────────────────────

_citizen_advisory_cache: Dict[tuple, str] = {}
# Maps hotspot_id → cache_key tuple for targeted invalidation (Improvement 10)
_advisory_hotspot_index: Dict[int, tuple] = {}


def clear_citizen_advisory_cache(hotspot_id: Optional[int] = None) -> int:
    """
    Invalidate cached citizen advisories.

    When ``hotspot_id`` is given, only the entry for that hotspot is removed
    (trust score change, re-verification, evidence update, etc.).
    When called with no argument, the entire cache is cleared (recompute).
    Returns number of entries removed.
    """
    global _citizen_advisory_cache, _advisory_hotspot_index
    if hotspot_id is not None:
        key = _advisory_hotspot_index.pop(hotspot_id, None)
        if key and key in _citizen_advisory_cache:
            del _citizen_advisory_cache[key]
            logger.debug("Citizen advisory cache invalidated for hotspot_id=%d", hotspot_id)
            return 1
        return 0
    count = len(_citizen_advisory_cache)
    _citizen_advisory_cache.clear()
    _advisory_hotspot_index.clear()
    logger.info("Citizen advisory cache cleared (%d entries removed).", count)
    return count


def _extract_grounded_facts(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    time_window_hours: Optional[int],
    area_label: Optional[str],
) -> Dict[str, Any]:
    """
    Improvement 6 — data-first advisory grounding.

    Extract structured, verifiable facts from hotspot data before any LLM
    call.  These facts are:
      - passed to the LLM as an explicit "ground these facts" instruction
      - used as the sole basis for the template fallback

    No claim can appear in the advisory that is not derivable from these facts.
    """
    time_label = _time_window_label(time_window_hours)
    top_crimes = sorted((incident_mix or {}).items(), key=lambda x: x[1], reverse=True)[:3]
    severity_class = (
        "high" if classification in ("critical", "active")
        else "moderate" if classification == "emerging"
        else "low"
    )
    return {
        "area": area_label or "the area",
        "time_label": time_label,
        "incident_count": incident_count,
        "dominant_crime": dominant_crime or "incidents",
        "top_crimes": top_crimes,
        "severity_class": severity_class,
        "classification": classification,
    }


def _time_window_label(hours: Optional[int]) -> str:
    """Human-readable label for a time window."""
    if not hours or hours <= 0:
        return "recently"
    if hours <= 6:
        return "in the past few hours"
    if hours <= 24:
        return "in the past 24 hours"
    if hours <= 48:
        return "in the past 2 days"
    if hours <= 72:
        return "in the past 3 days"
    if hours <= 168:
        return "in the past week"
    if hours <= 360:
        return "in the past 2 weeks"
    if hours <= 720:
        return "in the past month"
    return "recently"


def _build_citizen_advisory_prompt(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    time_window_hours: Optional[int] = None,
) -> str:
    area = area_label or "your area"
    crime = dominant_crime or "incidents"
    time_label = _time_window_label(time_window_hours)
    mix_lines = ""
    if incident_mix:
        top = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:4]
        mix_lines = ", ".join(f"{name} ({cnt})" for name, cnt in top)

    urgency_note = ""
    if classification in ("critical",):
        urgency_note = "This is a high-urgency situation. The advisory should convey clear and immediate risk without causing panic."
    elif classification in ("active", "high"):
        urgency_note = "This is an elevated-risk situation. The advisory should convey noticeable concern while keeping a calm tone."

    return f"""You are writing a PUBLIC SAFETY NOTICE for ordinary citizens (residents, commuters, and members of the public) in Musanze, Rwanda.

IMPORTANT: This is NOT a police briefing. Your reader is a civilian — not a law enforcement officer, not a security professional.
Write as if you are informing a neighbour, not briefing a patrol unit.

Situation:
- Area              : {area}
- Time period       : {time_label}
- Security level    : {classification}
- Incident type     : {crime}
- Incident count    : {incident_count} reports
- Incident breakdown: {mix_lines or crime}
{urgency_note}

Write 2–3 plain sentences in calm, everyday English that any adult can understand.
You MUST mention the time period ("{time_label}") naturally in the advisory.
Tell them:
1. What kind of incidents have been reported nearby and when (use the time period naturally).
2. Simple, practical steps they can take to stay safe (tailored to the incident type — e.g. secure valuables for theft, stay off the road for traffic, stay in groups for assault).
3. Encourage them to stay alert and report incidents or unusual behaviour through the TrustBond app.

Tone guidelines:
- Empowering, not alarming — help people feel informed and able to act, not frightened.
- Simple language — no jargon, no acronyms, no technical terms.
- Community-focused — use "you", "your neighbours", "your area" to make it feel personal.

Example tone (adapt the content — do NOT copy verbatim):
"Several theft incidents were reported near {area} {time_label}. Secure your valuables, avoid isolated spots especially after dark, and look out for your neighbours. If you see anything suspicious, report it through TrustBond right away."

STRICT RULES — your response MUST NOT include any of the following:
- Police unit names, team codes, or department names (e.g. RRU, CPU, DEU, K9, RNP — none of these).
- Tactical deployments, patrol instructions, or operational plans.
- Internal security classifications or police procedures.
- Any language that implies the reader is a law enforcement officer.

Return JSON only:
{{
  "advisory": "<2-3 sentences, plain everyday English for ordinary citizens>"
}}
"""


def generate_citizen_advisory(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    area_label: Optional[str] = None,
    incident_mix: Optional[Dict[str, int]] = None,
    time_window_hours: Optional[int] = None,
    hotspot_id: Optional[int] = None,
) -> str:
    """
    Generate a plain-language public safety advisory for citizens.

    Improvement 6 — data-first architecture:
      1. Extract verified facts (incident count, crime type, time window, area).
      2. Build template advisory directly from these facts (always available).
      3. Optionally enhance wording with LLM, strictly anchored to the same facts.
      4. The LLM can only *rephrase* — it cannot introduce new claims.

    Mentions the observation time window so advisories never feel stale.
    Falls back to the template when no LLM key is configured.
    """
    mix_tuple = tuple(sorted((incident_mix or {}).items()))
    # Include hotspot_id so distinct hotspots never share the same cached advisory
    # even when their aggregate parameters happen to match.
    cache_key = (hotspot_id, classification, incident_count, dominant_crime, area_label, mix_tuple, time_window_hours)
    if cache_key in _citizen_advisory_cache:
        return _citizen_advisory_cache[cache_key]

    # ── Step 1: extract verifiable facts ────────────────────────────────────
    facts = _extract_grounded_facts(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        incident_mix=incident_mix,
        time_window_hours=time_window_hours,
        area_label=area_label,
    )

    # ── Step 2: template advisory (always factual, always available) ─────────
    template_advisory = _build_citizen_advisory(
        area_label=facts["area"],
        dominant_crime=facts["dominant_crime"],
        incident_count=incident_count,
        classification=classification,
        cluster_kind="single_type",
        incident_mix=incident_mix,
        time_window_hours=time_window_hours,
    )

    # ── Step 3: LLM wording enhancement (anchored to the same facts) ────────
    advisory = template_advisory  # start from template; LLM overrides only if valid

    if _hotspot_llm_required():
        prompt = _build_citizen_advisory_prompt(
            classification=classification,
            incident_count=incident_count,
            dominant_crime=dominant_crime,
            area_label=area_label,
            incident_mix=incident_mix,
            time_window_hours=time_window_hours,
        )
        result = _call_hotspot_llm(prompt)
        llm_advisory = (result or {}).get("advisory", "").strip()

        # Improvement 6 — validation: reject LLM output if it fails fact-checks
        if llm_advisory and _advisory_passes_fact_check(llm_advisory, facts):
            advisory = llm_advisory
        elif llm_advisory:
            logger.warning(
                "[citizen_advisory] LLM advisory failed fact-check "
                "(hotspot_id=%s, classification=%s) — using template fallback",
                hotspot_id, classification,
            )

    # ── Step 4: cache and return ─────────────────────────────────────────────
    _citizen_advisory_cache[cache_key] = advisory
    if hotspot_id is not None:
        _advisory_hotspot_index[hotspot_id] = cache_key
    return advisory


def _advisory_passes_fact_check(advisory: str, facts: Dict[str, Any]) -> bool:
    """
    Improvement 6 — lightweight fact-check for LLM advisory output.

    Rejects text that:
    - Is shorter than 40 characters (truncated / empty)
    - Contains police unit codes or internal jargon
    - Does NOT mention the time period (advisory must be time-anchored)
    """
    if len(advisory) < 40:
        return False

    # Hard-block: police operational language must never reach citizens
    _BANNED_TERMS = re.compile(
        r"\b(RRU|DEU|TPU|CPU|ISU|AFU|VPU|K9|RNP|QUICK_RESPONSE|COUNTER_TERROR|"
        r"FIRE_RESCUE|GENERAL_PATROL|deploy|deployed|patrol unit|tactical|"
        r"operation|dispatch|armed response|surveillance)\b",
        re.I,
    )
    if _BANNED_TERMS.search(advisory):
        return False

    # Soft-check: advisory should reference the time window
    time_label = facts.get("time_label", "")
    time_words = re.compile(r"past|hour|day|week|month|recently|period|lately", re.I)
    if time_label and not time_words.search(advisory):
        return False

    return True
