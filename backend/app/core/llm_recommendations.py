"""
LLM-generated hotspot recommendations.

Priority chain:
  1. Groq  (free — llama-3.3-70b-versatile)   → set GROQ_API_KEY
  2. Gemini (free tier — gemini-1.5-flash)     → set GEMINI_API_KEY
  3. Template fallback (always works, no key)

Keys are read from environment variables; if a key is absent or the call
fails the next provider is tried automatically.
"""
import json
import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Unit configuration ────────────────────────────────────────────────────────

# Investigation-only bodies — never assigned to tactical hotspot deployments.
# Their incident types receive no unit recommendation; incidents are left as-is.
_INVESTIGATION_ONLY = {"CID", "RIB"}

# Tactical deployment mode per special assignment unit code.
# This drives both the LLM prompt and the template fallback so recommendations
# describe the correct tactic (covert, checkpoint, uniformed, etc.) not just
# "deploy patrol" for every situation.
_UNIT_TACTICS: Dict[str, str] = {
    "RRU": "rapid armed response and tactical intervention",
    "DEU": "covert surveillance and undercover drug enforcement operations",
    "TPU": "traffic checkpoints, vehicle interdiction, and road patrol",
    "CPU": "uniformed community patrol and neighborhood liaison",
    "ISU": "plainclothes intelligence gathering and covert surveillance",
    "K9":  "K9-assisted search operations and suspect tracking",
    "AFU": "anti-fraud awareness operations and financial crime deterrence",
    "VPU": "protective patrol and victim safety escort operations",
}


def _resolve_unit(unit: Optional[str]) -> Optional[str]:
    """Strip CID/RIB (investigation-only bodies); return all other units unchanged."""
    if not unit:
        return None
    u = unit.strip().upper()
    if any(excl in u for excl in _INVESTIGATION_ONLY):
        return None
    return unit.strip()


def _unit_tactic(unit: Optional[str]) -> str:
    """Return the tactical approach for a unit code, or generic 'security patrol'."""
    if not unit:
        return "security patrol"
    u = unit.strip().upper()
    for code, tactic in _UNIT_TACTICS.items():
        if code in u:
            return tactic
    return "security patrol"


# ── Operation duration helpers ────────────────────────────────────────────────

def _suggest_duration_hours(classification: str, cluster_kind: str) -> int:
    """Return the recommended total operation duration in hours.

    Severity bands:
      critical / mixed  → 48 h continuous (situation may escalate)
      active            → 24 h operation
      emerging          → 12 h operation
      low_activity      →  6 h observation window
    """
    if cluster_kind == "mixed_hotspot" or classification == "critical":
        return 48
    if classification == "active":
        return 24
    if classification == "emerging":
        return 12
    return 6


def _concentrate_window(peak_time: Optional[str], duration_hours: int) -> Optional[str]:
    """Derive a concentration window around the known peak activity hour.

    Extends the peak 2-hour window by buffer hours on each side so officers
    know when to intensify presence without staying at peak alert for the
    entire operation.

    Buffer sizing:
      48 h operation → ±4 h around peak  (8-hour intensive block)
      24 h           → ±3 h              (6-hour intensive block)
      12 h           → ±2 h              (4-hour intensive block)
       6 h           → ±1 h              (3-hour intensive block)
    """
    if not peak_time:
        return None
    try:
        # peak_time format: "HH:00–HH:00"
        start_str = peak_time.split("–")[0].strip()
        peak_hour = int(start_str.split(":")[0])
    except Exception:
        return None

    if duration_hours >= 48:
        buf = 4
    elif duration_hours >= 24:
        buf = 3
    elif duration_hours >= 12:
        buf = 2
    else:
        buf = 1

    c_start = (peak_hour - buf) % 24
    c_end   = (peak_hour + 2 + buf) % 24   # +2 because peak window is 2 h wide
    return f"{c_start:02d}:00–{c_end:02d}:00"


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    peak_time: Optional[str],
    recommended_unit: Optional[str],
    operation_hours: int,
    concentrate_window: Optional[str],
) -> str:
    crime      = dominant_crime or "mixed incidents"
    area       = area_label or "the area"
    unit       = recommended_unit or "General Patrol"
    tactic     = _unit_tactic(recommended_unit)
    conc_note  = (
        f"Concentrate operations between {concentrate_window}."
        if concentrate_window else "No peak window identified — distribute evenly."
    )

    mix_lines = ""
    if incident_mix:
        sorted_mix = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)
        mix_lines = "\n".join(f"  - {name}: {count}" for name, count in sorted_mix)

    return f"""You are a police intelligence analyst for the Rwanda National Police in Musanze District.
A DBSCAN algorithm has detected a crime hotspot. Produce an operational briefing.

Hotspot data:
- Classification          : {classification}
- Cluster type            : {cluster_kind}
- Location                : {area}
- Total incidents         : {incident_count}
- Dominant crime          : {crime}
- Incident mix            :
{mix_lines if mix_lines else "  - " + crime}
- Peak activity window    : {peak_time or "unknown"}
- Assigned unit           : {unit}
- Unit tactical role      : {tactic}
- Recommended operation   : {operation_hours}-hour operation
- Concentration window    : {conc_note}

Write a police intelligence briefing in JSON with these exact keys:
{{
  "recommendation": "...",
  "narrative": "...",
  "status": "..."
}}

WORD COUNT REQUIREMENTS — these are hard requirements, not suggestions:
  recommendation : 20–40 words
  narrative      : 50–80 words

EXAMPLE of a correctly sized output (do NOT copy this — use the real data above):
{{
  "recommendation": "Activate RRU immediately for a 48-hour rapid armed response and tactical intervention operation in Cyuve, concentrating patrol and interdiction efforts between 17:00 and 03:00 to disrupt the ongoing assault pattern.",
  "narrative": "A critical assault hotspot has been confirmed in Cyuve with 6 verified incidents recorded during the current monitoring period, with peak criminal activity concentrated between 21:00 and 23:00. The cluster exhibits rapid escalation characteristics supported by high-confidence evidence from community reports. If immediate tactical intervention is not deployed, further violent incidents are highly probable and the situation risks spreading to neighbouring villages. Commanding officers should treat this as a priority security threat requiring an active operational posture.",
  "status": "escalation_likely"
}}

Rules:
- recommendation: name the unit ({unit}), its tactic ({tactic}), the {operation_hours}-hour duration, and the concentration window. Write 20–40 words — count before submitting.
- narrative: cover (1) crime type and location, (2) incident count, (3) peak time, (4) severity, (5) escalation risk if unaddressed. Write 50–80 words in 3–4 full sentences — count before submitting.
- status must be one of: escalation_likely | monitor_growth | emerging_trend | security_alert
- Use the correct tactic for {unit} — NOT generic uniform patrol unless CPU is assigned.
- Use real data only (area, crime types, peak time). Do NOT invent facts.
- No markdown, no bullet points inside JSON strings.
- Return ONLY the JSON object, nothing else.
"""


# ── Providers ─────────────────────────────────────────────────────────────────

def _call_groq(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=600,
        )
        text = resp.choices[0].message.content.strip()
        # Extract JSON block from response (model may wrap with markdown)
        start = text.find("{")
        end   = text.rfind("}") + 1
        return json.loads(text[start:end]) if start != -1 else None
    except Exception as exc:
        logger.warning("Groq LLM call failed: %s", exc)
        return None


def _call_gemini(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return json.loads(resp.text)
    except Exception as exc:
        logger.warning("Gemini LLM call failed: %s", exc)
        return None


# ── Cache ─────────────────────────────────────────────────────────────────────
# Keyed by cluster fingerprint — LLM is called only when cluster data changes.
# Clear this whenever hotspot clusters are recomputed so weekly/periodic reports
# always get fresh analysis that reflects the new cluster state.

_recommendation_cache: Dict[tuple, Dict[str, Any]] = {}


def clear_recommendation_cache() -> int:
    """Discard all cached recommendations. Returns the number of entries removed.
    Call this whenever hotspot clusters are recomputed."""
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
    recommended_unit: Optional[str],
) -> tuple:
    return (classification, incident_count, dominant_crime, cluster_kind,
            area_label, peak_time, mix_tuple, recommended_unit)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_recommendation(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]] = None,
    peak_time: Optional[str] = None,
    recommended_unit: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return a dict with keys:
      recommendation, narrative, status, recommended_unit,
      operation_hours, concentrate_window.

    CID/RIB are silently excluded — their incidents carry no unit assignment.
    Operation duration and concentration window are computed from classification
    and peak activity data, then fed into the LLM prompt so recommendations
    specify exact hours rather than open-ended deployment language.

    Tries Groq → Gemini → template fallback, with in-memory caching.
    """
    resolved_unit      = _resolve_unit(recommended_unit)
    operation_hours    = _suggest_duration_hours(classification, cluster_kind)
    concentrate_window = _concentrate_window(peak_time, operation_hours)

    mix_tuple = tuple(sorted((incident_mix or {}).items()))
    key = _cache_key(
        classification, incident_count, dominant_crime,
        cluster_kind, area_label, peak_time, mix_tuple, resolved_unit,
    )
    if key in _recommendation_cache:
        return _recommendation_cache[key]

    prompt = _build_prompt(
        classification, incident_count, dominant_crime,
        cluster_kind, area_label, incident_mix, peak_time,
        resolved_unit, operation_hours, concentrate_window,
    )

    result = _call_groq(prompt) or _call_gemini(prompt)

    if result and all(k in result for k in ("recommendation", "narrative", "status")):
        clean = {
            "recommendation":    str(result["recommendation"]),
            "narrative":          str(result["narrative"]),
            "status":             str(result["status"]),
            "recommended_unit":   resolved_unit,
            "operation_hours":    operation_hours,
            "concentrate_window": concentrate_window,
        }
        _recommendation_cache[key] = clean
        return clean

    # ── Template fallback ─────────────────────────────────────────────────────
    logger.info("Using template fallback for hotspot recommendation (no LLM key configured)")
    crime  = dominant_crime or "incident"
    area   = area_label or "this area"
    unit   = resolved_unit or "patrol units"
    tactic = _unit_tactic(resolved_unit)
    dur    = f"{operation_hours}-hour"
    conc   = (
        f", concentrating between {concentrate_window}"
        if concentrate_window else ""
    )
    peak_note = f" Peak activity recorded at {peak_time}." if peak_time else ""

    mix_detail = ""
    if incident_mix and len(incident_mix) > 1:
        top = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)[:3]
        mix_detail = f" The cluster includes {', '.join(f'{v} {k.lower()}' for k, v in top)}."

    if cluster_kind == "mixed_hotspot":
        fallback = {
            "recommendation": (
                f"Deploy {unit} for a {dur} {tactic} operation across {area}{conc}."
                f" All affected villages must be covered and sector leadership notified."
            ),
            "narrative": (
                f"A mixed crime hotspot has been detected in {area} with {incident_count} verified incidents"
                f" spanning multiple crime types.{mix_detail}{peak_note}"
                f" The convergence of different crime categories signals a general security breakdown."
                f" Immediate coordinated response is required to prevent further deterioration."
            ),
            "status": "security_alert",
        }
    elif classification == "critical":
        fallback = {
            "recommendation": (
                f"Activate {unit} immediately for a {dur} {tactic} operation targeting"
                f" the {crime.lower()} cluster in {area}{conc}."
                f" Report operational status every 6 hours to the duty commander."
            ),
            "narrative": (
                f"A critical {crime.lower()} hotspot has been confirmed in {area} with {incident_count} verified incidents."
                f"{peak_note}{mix_detail}"
                f" The cluster score indicates rapid escalation with a high probability of further violence"
                f" if left unaddressed. Immediate tactical deployment is essential to contain the situation."
            ),
            "status": "escalation_likely",
        }
    elif classification == "active":
        fallback = {
            "recommendation": (
                f"Task {unit} to conduct a {dur} {tactic} operation focused on {crime.lower()} activity in {area}{conc}."
                f" Engage cell and village leadership to strengthen community reporting."
            ),
            "narrative": (
                f"An active {crime.lower()} hotspot is developing in {area} with {incident_count} incidents recorded."
                f"{peak_note}{mix_detail}"
                f" Incident frequency is growing and the pattern suggests continued escalation without intervention."
                f" Increased operational presence is required to deter further criminal activity."
            ),
            "status": "monitor_growth",
        }
    else:
        fallback = {
            "recommendation": (
                f"Direct {unit} to begin a {dur} {tactic} to monitor early {crime.lower()} signals in {area}{conc}."
                f" Escalate immediately if incident count increases by two or more."
            ),
            "narrative": (
                f"An emerging pattern of {crime.lower()} has been detected in {area} with {incident_count} incident{'' if incident_count == 1 else 's'} reported."
                f"{peak_note}{mix_detail}"
                f" The situation is at an early stage but requires monitoring to prevent escalation."
                f" Early intervention at this stage can significantly reduce the risk of the cluster becoming active."
            ),
            "status": "emerging_trend",
        }

    fallback["recommended_unit"]   = resolved_unit
    fallback["operation_hours"]    = operation_hours
    fallback["concentrate_window"] = concentrate_window
    _recommendation_cache[key] = fallback
    return fallback
