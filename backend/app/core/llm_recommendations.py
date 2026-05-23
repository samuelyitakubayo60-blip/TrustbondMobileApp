"""
LLM-generated hotspot recommendations.

Hotspot deployments use active tactical units from ``special_assignment_units``
(investigation-only codes like RIB/CID/LIB are excluded). Cases keep the full unit dropdown.

Priority chain: Groq → Gemini (JSON). When API keys are set, only LLM text is used — no template fallback.
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Groq: skip repeat calls only after permanent account errors
_groq_skip_reason: Optional[str] = None
_groq_skip_logged = False
_last_hotspot_llm_error: Optional[str] = None

_PERMANENT_GROQ_MARKERS = (
    "organization_restricted",
    "invalid_api_key",
    "authentication",
    "permission_denied",
)


def _hotspot_llm_required() -> bool:
    """True when .env has GROQ and/or GEMINI keys — LLM-only briefings, no templates."""
    return bool(
        os.getenv("GROQ_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    )


def _gemini_model_candidates() -> List[str]:
    candidates: List[str] = []
    for raw in (
        os.getenv("GEMINI_HOTSPOT_MODEL"),
        os.getenv("GEMINI_MODEL"),
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-1.5-flash-8b",
    ):
        name = (raw or "").strip()
        if name and name not in candidates:
            candidates.append(name)
    return candidates or ["gemini-2.0-flash"]


def _disable_groq(reason: str) -> None:
    global _groq_skip_reason, _groq_skip_logged
    _groq_skip_reason = reason[:240]
    if not _groq_skip_logged:
        logger.warning(
            "Groq hotspot LLM unavailable for this process: %s",
            _groq_skip_reason,
        )
        _groq_skip_logged = True


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
) -> Dict[str, Any]:
    """Rule-based primary + support unit from crime mix, volume, and incident-type hint."""
    totals = {code: 0.0 for code in registry}

    if incident_mix:
        for name, count in incident_mix.items():
            c = max(1, int(count or 0))
            for code, w in _score_crime_text(name, registry).items():
                totals[code] += w * c
    elif dominant_crime:
        for code, w in _score_crime_text(dominant_crime, registry).items():
            totals[code] += w * max(1, incident_count)

    hint = _resolve_unit(incident_type_unit_hint, registry)
    if hint:
        totals[hint] = totals.get(hint, 0.0) + 5.0

    if sum(totals.values()) < 0.1:
        totals["GENERAL_PATROL"] = totals.get("GENERAL_PATROL", 0.0) + 3.0

    cls = (classification or "").strip().lower()
    if cls in {"critical", "active"}:
        for code in ("RRU", "QUICK_RESPONSE"):
            if code in registry:
                totals[code] = totals.get(code, 0.0) + 2.5
    if cluster_kind == "mixed_hotspot" and incident_count >= 6:
        if "QUICK_RESPONSE" in registry:
            totals["QUICK_RESPONSE"] = totals.get("QUICK_RESPONSE", 0.0) + 2.0
        if "CPU" in registry:
            totals["CPU"] = totals.get("CPU", 0.0) + 1.5

    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    primary_code = ranked[0][0] if ranked else "GENERAL_PATROL"
    support_code: Optional[str] = None
    if len(ranked) > 1 and ranked[1][1] >= ranked[0][1] * 0.4:
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
) -> str:
    """
    Community-facing notice (plain language). Uses case outcomes when available:
    e.g. suspect apprehended vs ongoing watch-and-report for theft clusters.
    """
    area = (area_label or "this area").strip()
    crime = (dominant_crime or "incidents").strip().lower()
    cls = (classification or "").strip().lower()
    ctx = cluster_case_context or {}
    theft_count = _theft_incident_weight(dominant_crime, incident_mix)
    is_theft_cluster = theft_count >= 1 or bool(
        re.search(r"theft|robbery|burglary|steal", crime, re.I)
    )

    if ctx.get("suspect_apprehended") and is_theft_cluster:
        return (
            f"Police have acted on theft-related reports in {area}. A suspect was apprehended "
            f"in connection with investigations linked to this area. Thank you to residents who reported. "
            f"Please continue to secure valuables and report anything new or seriously concerning."
        )

    if ctx.get("closed_cases", 0) >= 1 and is_theft_cluster:
        return (
            f"Police have closed at least one investigation tied to theft reports near {area}. "
            f"Thank you for reporting. Stay alert, protect your property, and contact police if you see "
            f"new suspicious activity or anything that should be investigated urgently."
        )

    if verified_report_count >= max(2, incident_count // 2) and incident_count >= 2:
        return (
            f"Police have responded to recent verified reports in {area}. Thank you for sharing information. "
            f"Please stay alert and report anything new or seriously concerning."
        )

    if is_theft_cluster:
        return (
            f"There have been theft-related reports near {area}. Secure valuables and shared spaces, "
            f"watch for suspicious behaviour, and report anything serious to police so patrols can respond."
        )

    if re.search(r"traffic|accident|road|vehicle", crime, re.I):
        return (
            f"Traffic-related incidents have been reported around {area}. Use caution on the road "
            f"and report dangerous driving or serious accidents to police."
        )

    if cls in {"critical", "active"} or cluster_kind == "mixed_hotspot":
        return (
            f"Police are monitoring increased incident reports in {area}. Avoid unnecessary risk, "
            f"look out for neighbours, and report emergencies or serious concerns immediately."
        )

    return (
        f"Occasional incident reports have been noted in {area}. Remain observant and contact police "
        f"if you see anything that should be investigated."
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

    return f"""You are a police intelligence analyst for Rwanda National Police (Musanze District).
Write a UNIQUE briefing for this specific hotspot — do not reuse generic wording from other clusters.

Hotspot data:
- Classification       : {classification}
- Cluster type         : {cluster_kind}
- Location             : {area}
- Total incidents      : {incident_count}
- Dominant crime       : {dominant_crime or "mixed"}
- Incident mix         :
{mix_lines if mix_lines else "  - " + (dominant_crime or "unknown")}
- Peak activity        : {peak_time or "unknown"}
- Deploy units         : {units_line}
- Primary tactic       : {tactic}
- Operation duration   : {operation_hours} hours
- Concentration window : {conc_note}
- Citizen message hint : {citizen_advisory}

Allowed deployment units (pick from this list only; do NOT use RIB/CID/LIB investigation units):
  {allowed_units}

Return JSON only:
{{
  "recommendation": "<20-40 words: name primary unit, tactic, duration, concentration window, specific to THIS crime mix>",
  "narrative": "<50-80 words: situation in {area}, counts, peak time, risk, why these units>",
  "status": "<escalation_likely | monitor_growth | emerging_trend | security_alert>",
  "citizen_advisory": "<2-3 sentences plain Kinyaranda-friendly English for citizens; calm, no police codes>"
}}

Rules:
- recommendation MUST name "{primary}" (and "{support}" if support) — not "multi-unit" without names.
- Vary wording using the incident mix ({_mix_summary(incident_mix, dominant_crime)}).
- citizen_advisory: community-facing only; do not mention unit codes or classified tactics.
- Use real numbers and place names only. No markdown.
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
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Gemini (%s) returned invalid JSON: %s", model_name, exc)
        return None
    except Exception as exc:
        logger.warning("Gemini (%s) failed: %s", model_name, exc)
        return None


def _call_gemini_model(prompt: str, model_name: str, api_key: str) -> Optional[Dict[str, Any]]:
    return gemini_generate_json(
        prompt, api_key, model_name, max_tokens=700, temperature=0.35
    )


def _call_gemini(prompt: str) -> Optional[Dict[str, Any]]:
    global _last_hotspot_llm_error
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    errors: List[str] = []
    for model_name in _gemini_model_candidates():
        parsed = _call_gemini_model(prompt, model_name, api_key)
        if parsed and parsed.get("recommendation") and parsed.get("narrative"):
            logger.info("Hotspot briefing generated via Gemini model %s", model_name)
            return parsed
        errors.append(model_name)
    _last_hotspot_llm_error = (
        f"Gemini failed for models: {', '.join(errors)}"
        if errors
        else "Gemini returned empty JSON"
    )
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
    """Crime- and unit-specific templates using the full tactical unit registry."""
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
) -> Dict[str, Any]:
    """
    Hotspot briefing: rule-picked units + Groq/Gemini JSON text when API keys are set.
    No template fallback when ``GROQ_API_KEY`` / ``GEMINI_API_KEY`` are configured.
    """
    registry = deployment_units or load_hotspot_deployment_units()
    plan = _pick_hotspot_deployment_plan(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        cluster_kind=cluster_kind,
        incident_mix=incident_mix,
        registry=registry,
        incident_type_unit_hint=recommended_unit,
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

    if _hotspot_llm_required():
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


# ── Public / citizen-only advisory (no unit or tactical details) ──────────────

_citizen_advisory_cache: Dict[tuple, str] = {}


def _build_citizen_advisory_prompt(
    *,
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
) -> str:
    area = area_label or "your area"
    crime = dominant_crime or "incidents"
    mix_lines = ""
    if incident_mix:
        top = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:4]
        mix_lines = ", ".join(f"{name} ({cnt})" for name, cnt in top)

    return f"""You are writing a short public safety notice for citizens in Musanze, Rwanda.

Situation:
- Area              : {area}
- Security level    : {classification}
- Incident type     : {crime}
- Incident count    : {incident_count}
- Incident breakdown: {mix_lines or crime}

Write 2–3 plain sentences in calm, clear English for the general public.
Tell them:
1. What kind of security situation has been reported nearby.
2. What practical steps they should take (e.g. stay alert, secure valuables, avoid the area at night, report anything suspicious).
3. Encourage them to report incidents through the TrustBond app.

STRICT RULES — your response must NOT mention:
- Any police unit names, team names, or department codes (e.g. RRU, DEU, CPU).
- Any police tactics, deployments, or operational plans.
- Any classified or internal police information.

Return JSON only:
{{
  "advisory": "<2-3 sentences, plain citizen-facing English>"
}}
"""


def generate_citizen_advisory(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    area_label: Optional[str] = None,
    incident_mix: Optional[Dict[str, int]] = None,
) -> str:
    """
    Generate a plain-language public safety advisory for citizens.
    Contains no police unit names, tactical details, or operational information.
    Falls back to a template when no LLM key is configured.
    """
    mix_tuple = tuple(sorted((incident_mix or {}).items()))
    cache_key = (classification, incident_count, dominant_crime, area_label, mix_tuple)
    if cache_key in _citizen_advisory_cache:
        return _citizen_advisory_cache[cache_key]

    prompt = _build_citizen_advisory_prompt(
        classification=classification,
        incident_count=incident_count,
        dominant_crime=dominant_crime,
        area_label=area_label,
        incident_mix=incident_mix,
    )

    result = _call_hotspot_llm(prompt)
    advisory = (result or {}).get("advisory", "").strip()

    if not advisory:
        # Template fallback — still unit-free
        advisory = _build_citizen_advisory(
            area_label=area_label,
            dominant_crime=dominant_crime,
            incident_count=incident_count,
            classification=classification,
            cluster_kind="single_type",
            incident_mix=incident_mix,
        )

    _citizen_advisory_cache[cache_key] = advisory
    return advisory
