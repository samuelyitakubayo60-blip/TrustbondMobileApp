from __future__ import annotations

from typing import Optional, Tuple

import requests

from app.config import settings


def _normalize_phone(phone: str) -> str:
    p = (phone or "").strip()
    if not p:
        return p
    if p.startswith("+"):
        return p
    digits = "".join(ch for ch in p if ch.isdigit())
    if not digits:
        return p
    return f"+{digits}"


def send_esms_sms(to_phone: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    Send SMS through eSMS Africa API.
    Returns (ok, error_message).
    """
    token = (settings.esms_token or "").strip()
    if not token:
        return False, "ESMS_TOKEN is not configured."

    base = (settings.esms_base_url or "https://sms.esmsafrica.io").rstrip("/")
    url = f"{base}/api/messages/send"
    payload = {
        "to": _normalize_phone(to_phone),
        "text": text,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=int(settings.esms_timeout_seconds or 12),
        )
    except Exception as exc:
        return False, f"eSMS request failed: {exc}"

    if 200 <= resp.status_code < 300:
        return True, None

    body = (resp.text or "").strip()
    return False, f"eSMS send failed ({resp.status_code}): {body[:300]}"

