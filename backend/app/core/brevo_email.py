"""Send transactional email via Brevo HTTP API (v3)."""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from typing import Iterable

import requests

from app.config import settings
from app.core.smtp_config import clean_env_value

logger = logging.getLogger(__name__)

DEFAULT_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def is_brevo_configured() -> bool:
    return bool(clean_env_value(getattr(settings, "brevo_api_key", None)))


def resolved_from_address() -> str | None:
    return (
        clean_env_value(getattr(settings, "brevo_sender_email", None))
        or clean_env_value(settings.smtp_from)
        or clean_env_value(settings.smtp_user)
    )


def resolved_sender_name() -> str:
    return clean_env_value(getattr(settings, "brevo_sender_name", None)) or "TrustBond"


def _brevo_api_url() -> str:
    return (getattr(settings, "brevo_api_url", None) or DEFAULT_BREVO_URL).strip().rstrip("/")


def _parse_brevo_error(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
            code = data.get("code")
            if message and code:
                return f"{message} (code: {code})"
            if message:
                return str(message)
    except Exception:
        pass
    text = (response.text or "").strip()
    return text or f"Brevo request failed (HTTP {response.status_code})"


def send_brevo_email(
    to: str,
    subject: str,
    *,
    html: str | None = None,
    text: str | None = None,
    sender_email: str | None = None,
    sender_name: str | None = None,
) -> tuple[bool, str | None]:
    """Send one transactional email through Brevo."""
    api_key = clean_env_value(getattr(settings, "brevo_api_key", None))
    if not api_key:
        return False, "Brevo is not configured (set BREVO_API_KEY)."

    from_email = clean_env_value(sender_email) or resolved_from_address()
    if not from_email:
        return False, "Brevo sender is not configured (set BREVO_SENDER_EMAIL)."

    recipient = (to or "").strip()
    if not recipient:
        return False, "No recipient email address provided."

    subject_clean = (subject or "").strip() or "(no subject)"
    html_body = (html or "").strip() or None
    text_body = (text or "").strip() or None
    if not html_body and not text_body:
        return False, "Email body is empty."
    if not html_body and text_body:
        html_body = (
            f'<pre style="font-family:Segoe UI,sans-serif;white-space:pre-wrap">'
            f"{text_body}</pre>"
        )

    payload: dict[str, object] = {
        "sender": {
            "name": clean_env_value(sender_name) or resolved_sender_name(),
            "email": from_email,
        },
        "to": [{"email": recipient}],
        "subject": subject_clean,
        "htmlContent": html_body,
    }
    if text_body:
        payload["textContent"] = text_body

    timeout = max(5, int(getattr(settings, "brevo_timeout_seconds", 30) or 30))
    try:
        response = requests.post(
            _brevo_api_url(),
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.Timeout:
        err = "Brevo request timed out."
        logger.warning("[Email] %s", err)
        return False, err
    except requests.RequestException as e:
        err = f"Brevo request failed: {e}"
        logger.warning("[Email] %s", err)
        return False, err

    if response.status_code in (200, 201, 202):
        return True, None

    err = _parse_brevo_error(response)
    logger.warning("[Email] Brevo send failed (%s): %s", response.status_code, err)
    return False, err


def _extract_bodies_from_mime(msg: MIMEMultipart) -> tuple[str | None, str | None]:
    plain: str | None = None
    html: str | None = None

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            content_type = part.get_content_type()
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if content_type == "text/plain" and plain is None:
                plain = decoded
            elif content_type == "text/html" and html is None:
                html = decoded
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html = decoded
                else:
                    plain = decoded
        except Exception:
            pass

    return plain, html


def deliver_brevo_from_mime(
    msg: MIMEMultipart,
    to_addrs: Iterable[str],
) -> tuple[bool, str | None]:
    """Send a MIME message via Brevo transactional API."""
    recipients = [a.strip() for a in to_addrs if a and str(a).strip()]
    if not recipients:
        return False, "No recipient email addresses provided."

    subject = msg.get("Subject", "") or ""
    plain, html = _extract_bodies_from_mime(msg)

    last_err: str | None = None
    for recipient in recipients:
        ok, err = send_brevo_email(recipient, subject, html=html, text=plain)
        if not ok:
            last_err = err
    if last_err:
        return False, last_err
    return True, None
