"""Password setup codes for local leaders (email OTP)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.email import (
    is_smtp_configured,
    send_leader_account_ready_email,
    send_leader_otp_email,
)
from app.models.local_leader import LocalLeader
from app.models.local_leader_auth_code import LocalLeaderAuthCode

_log = logging.getLogger(__name__)

CODE_EXPIRE_MINUTES = 10

_LEADER_ROLE_LABELS = {
    "chief_of_village": "Village chief",
    "executive_of_cell": "Cell executive",
}


def notify_leader_account_ready(leader: LocalLeader) -> tuple[bool, str | None]:
    """Email that the account exists; leader requests OTP in the mobile app."""
    email = (leader.email or "").strip()
    if not email:
        return False, "Leader has no email address."
    if not is_smtp_configured():
        return False, "Email is not configured (set BREVO_API_KEY and BREVO_SENDER_EMAIL, or SMTP)."
    role_label = _LEADER_ROLE_LABELS.get((leader.role or "").strip())
    ok, err = send_leader_account_ready_email(
        email,
        leader_name=(leader.full_name or "").strip() or None,
        role_label=role_label,
    )
    if not ok:
        _log.warning("Account-ready email failed for leader %s: %s", leader.local_leader_id, err)
    return ok, err


def issue_password_setup_code(db: Session, leader: LocalLeader) -> tuple[bool, str | None]:
    """
    Invalidate prior unused setup codes, store a new code, and email it.
    Returns (success, error_message).
    """
    email = (leader.email or "").strip()
    if not email:
        return False, "Leader has no email address."
    if not is_smtp_configured():
        return False, "Email is not configured (set BREVO_API_KEY and BREVO_SENDER_EMAIL, or SMTP)."

    db.query(LocalLeaderAuthCode).filter(
        LocalLeaderAuthCode.local_leader_id == leader.local_leader_id,
        LocalLeaderAuthCode.purpose == "password_setup",
        LocalLeaderAuthCode.used_at.is_(None),
    ).delete(synchronize_session=False)

    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRE_MINUTES)
    db.add(
        LocalLeaderAuthCode(
            local_leader_id=leader.local_leader_id,
            phone_number=None,
            code=code,
            purpose="password_setup",
            expires_at=expires_at,
        )
    )
    db.commit()

    ok, err = send_leader_otp_email(
        email,
        code,
        "password_setup",
        leader_name=(leader.full_name or "").strip() or None,
    )
    if not ok:
        _log.warning("Setup email failed for leader %s: %s", leader.local_leader_id, err)
        return False, err or "Failed to send setup email."
    return True, None
