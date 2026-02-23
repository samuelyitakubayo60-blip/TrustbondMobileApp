"""
Send emails via SMTP (e.g. new user credentials).
Uses settings from config; no-op if SMTP not configured.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings


def is_smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


def send_email(to: str, subject: str, body_plain: str, body_html: str | None = None) -> tuple[bool, str | None]:
    """
    Send an email. Returns (True, None) if sent, (False, error_message) if not configured or send failed.
    """
    if not is_smtp_configured():
        return False, "SMTP not configured (SMTP_HOST, SMTP_USER, SMTP_PASS required)"
    from_addr = settings.smtp_from or settings.smtp_user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(body_plain, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))
    try:
        port = getattr(settings, "smtp_port", 587) or 587
        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, port) as server:
                server.login(settings.smtp_user, settings.smtp_pass)
                server.sendmail(from_addr, [to], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.sendmail(from_addr, [to], msg.as_string())
        return True, None
    except Exception as e:
        err = str(e).strip()
        print(f"[Email] Send failed: {err}")
        return False, err


def send_new_user_credentials(
    to_email: str,
    first_name: str,
    last_name: str,
    login_email: str,
    temporary_password: str,
    role: str,
    badge_number: str | None = None,
) -> tuple[bool, str | None]:
    """Send new police user their login credentials. Returns (True, None) if sent, (False, error_message) otherwise."""
    login_url = f"{settings.frontend_url.rstrip('/')}/login"
    subject = "Your TrustBond Police Dashboard account"
    badge_line = f"Badge number: {badge_number}\n" if badge_number else ""
    badge_line_html = f"  <li><strong>Badge number:</strong> {badge_number}</li>\n" if badge_number else ""
    body_plain = f"""Hello {first_name} {last_name},

Your TrustBond Police Dashboard account has been created.

Login URL: {login_url}
Email: {login_email}
{badge_line}Temporary password: {temporary_password}
Role: {role}

Please log in and change your password as soon as possible.

— TrustBond
"""
    body_html = f"""
<p>Hello {first_name} {last_name},</p>
<p>Your TrustBond Police Dashboard account has been created.</p>
<ul>
  <li><strong>Login URL:</strong> <a href="{login_url}">{login_url}</a></li>
  <li><strong>Email:</strong> {login_email}</li>
{badge_line_html}  <li><strong>Temporary password:</strong> {temporary_password}</li>
  <li><strong>Role:</strong> {role}</li>
</ul>
<p>Please log in and change your password as soon as possible.</p>
<p>— TrustBond</p>
"""
    ok, err = send_email(to_email, subject, body_plain, body_html)
    return ok, None if ok else err


def send_password_reset_code(to_email: str, code: str) -> tuple[bool, str | None]:
    """Send password reset code to the user's email. Returns (True, None) if sent, (False, error_message) otherwise."""
    subject = "TrustBond – Your password reset code"
    body_plain = f"""You requested a password reset for your TrustBond Police Dashboard account.

Your verification code is: {code}

This code expires in 15 minutes. If you did not request this, please ignore this email.

— TrustBond
"""
    body_html = f"""
<p>You requested a password reset for your TrustBond Police Dashboard account.</p>
<p>Your verification code is: <strong>{code}</strong></p>
<p>This code expires in 15 minutes. If you did not request this, please ignore this email.</p>
<p>— TrustBond</p>
"""
    return send_email(to_email, subject, body_plain, body_html)
