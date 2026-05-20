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
from functools import lru_cache
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]],
    peak_time: Optional[str],
) -> str:
    crime = dominant_crime or "mixed incidents"
    area  = area_label or "the area"
    mix_lines = ""
    if incident_mix:
        sorted_mix = sorted(incident_mix.items(), key=lambda x: x[1], reverse=True)
        mix_lines = "\n".join(f"  - {name}: {count}" for name, count in sorted_mix)

    return f"""You are a police intelligence analyst for the Rwanda National Police in Musanze District.
A DBSCAN algorithm has detected a crime hotspot with the following data:

- Classification  : {classification}
- Cluster type    : {cluster_kind}
- Location        : {area}
- Total incidents : {incident_count}
- Dominant crime  : {crime}
- Incident mix    :
{mix_lines if mix_lines else "  - " + crime}
- Peak activity   : {peak_time or "unknown"}

Write a SHORT police intelligence briefing in JSON with these exact keys:
{{
  "recommendation": "<one concise action sentence for patrol commanders, max 20 words>",
  "narrative": "<two sentences describing the pattern and risk, grounded in the data above>",
  "status": "<one of: escalation_likely | monitor_growth | emerging_trend | security_alert>"
}}

Rules:
- Use the real data (area name, crime types, peak time) — do NOT invent facts.
- Tone: professional police report, no markdown, no bullet points inside the JSON strings.
- Return ONLY the JSON object, nothing else.
"""


# ── Provider: Groq ────────────────────────────────────────────────────────────

def _call_groq(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as exc:
        logger.warning("Groq LLM call failed: %s", exc)
        return None


# ── Provider: Gemini ──────────────────────────────────────────────────────────

def _call_gemini(prompt: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json", "temperature": 0.3},
        )
        resp = model.generate_content(prompt)
        return json.loads(resp.text)
    except Exception as exc:
        logger.warning("Gemini LLM call failed: %s", exc)
        return None


# ── Cache key helper ──────────────────────────────────────────────────────────

def _cache_key(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    peak_time: Optional[str],
    mix_tuple: tuple,
) -> tuple:
    return (classification, incident_count, dominant_crime, cluster_kind,
            area_label, peak_time, mix_tuple)


# Simple in-memory cache — keyed by cluster fingerprint so the LLM is only
# called when the cluster data changes, not on every API request.
_recommendation_cache: Dict[tuple, Dict[str, Any]] = {}


# ── Public entry point ────────────────────────────────────────────────────────

def generate_recommendation(
    classification: str,
    incident_count: int,
    dominant_crime: Optional[str],
    cluster_kind: str,
    area_label: Optional[str],
    incident_mix: Optional[Dict[str, int]] = None,
    peak_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return a dict with keys: recommendation, narrative, status.
    Tries Groq → Gemini → template, caches by cluster fingerprint.
    """
    mix_tuple = tuple(sorted((incident_mix or {}).items()))
    key = _cache_key(
        classification, incident_count, dominant_crime,
        cluster_kind, area_label, peak_time, mix_tuple,
    )
    if key in _recommendation_cache:
        return _recommendation_cache[key]

    prompt = _build_prompt(
        classification, incident_count, dominant_crime,
        cluster_kind, area_label, incident_mix, peak_time,
    )

    result = _call_groq(prompt) or _call_gemini(prompt)

    if result and all(k in result for k in ("recommendation", "narrative", "status")):
        # Validate and strip to only the keys we need
        clean = {
            "recommendation": str(result["recommendation"]),
            "narrative":       str(result["narrative"]),
            "status":          str(result["status"]),
        }
        _recommendation_cache[key] = clean
        return clean

    # ── Template fallback ────────────────────────────────────────────────────
    logger.info("Using template fallback for hotspot recommendation (no LLM key configured)")
    crime  = dominant_crime or "incident"
    area   = area_label or "this area"
    peak   = f" Peak activity at {peak_time}." if peak_time else ""

    if cluster_kind == "mixed_hotspot":
        fallback = {
            "recommendation": f"Coordinate multi-unit response in {area} for mixed incident cluster.",
            "narrative": (
                f"Multiple crime types are converging in {area}, indicating a general disorder zone.{peak}"
            ),
            "status": "security_alert",
        }
    elif classification == "critical":
        fallback = {
            "recommendation": f"Deploy patrol units around {crime} cluster in {area}.",
            "narrative": (
                f"{crime.capitalize()} is rapidly escalating in {area} with {incident_count} incidents recorded.{peak}"
            ),
            "status": "escalation_likely",
        }
    elif classification == "active":
        fallback = {
            "recommendation": f"Increase monitoring of {crime} activity in {area}.",
            "narrative": (
                f"{crime.capitalize()} incidents are growing in {area}.{peak}"
            ),
            "status": "monitor_growth",
        }
    else:
        fallback = {
            "recommendation": f"Track early signals of {crime} in {area}.",
            "narrative": (
                f"An emerging pattern of {crime} has been detected in {area}.{peak}"
            ),
            "status": "emerging_trend",
        }

    _recommendation_cache[key] = fallback
    return fallback
