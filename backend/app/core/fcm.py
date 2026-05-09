"""Firebase Cloud Messaging (HTTP v1) for device tokens."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from app.config import settings

logger = logging.getLogger(__name__)

_SCOPES = ("https://www.googleapis.com/auth/firebase.messaging",)


def fcm_is_configured() -> bool:
    path = getattr(settings, "firebase_credentials_path", None) or ""
    if not path.strip():
        return False
    return Path(path).expanduser().is_file()


def _project_id() -> str | None:
    explicit = getattr(settings, "firebase_project_id", None)
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    path = getattr(settings, "firebase_credentials_path", None) or ""
    if not path:
        return None
    try:
        with open(Path(path).expanduser(), encoding="utf-8") as f:
            return json.load(f).get("project_id")
    except Exception:
        return None


def _access_token() -> str | None:
    if not fcm_is_configured():
        return None
    path = str(Path(settings.firebase_credentials_path).expanduser())
    try:
        creds = service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)
        creds.refresh(Request())
        return creds.token
    except Exception as exc:
        logger.warning("FCM: could not refresh access token: %s", exc)
        return None


def send_fcm_notification(
    device_token: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> bool:
    """Send a notification to one device. Returns True if FCM accepted the message."""
    token = (device_token or "").strip()
    if len(token) < 10:
        return False
    access = _access_token()
    project = _project_id()
    if not access or not project:
        return False
    url = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    msg: dict[str, Any] = {
        "token": token,
        "notification": {"title": title, "body": body},
    }
    if data:
        msg["data"] = {k: str(v) for k, v in data.items()}
    payload = {"message": msg}
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {access}"},
            json=payload,
            timeout=20,
        )
        if r.status_code == 200:
            return True
        logger.warning("FCM send failed HTTP %s: %s", r.status_code, r.text[:500])
    except Exception as exc:
        logger.warning("FCM send error: %s", exc)
    return False


def send_leader_new_report_notification(
    device_token: str,
    report_ref: str,
    village_name: str | None,
    report_id: str,
) -> bool:
    title = "New incident report"
    body = f"Report {report_ref}"
    if village_name:
        body = f"{body} — {village_name}"
    return send_fcm_notification(
        device_token,
        title,
        body,
        {"type": "leader_new_report", "report_id": str(report_id)},
    )
