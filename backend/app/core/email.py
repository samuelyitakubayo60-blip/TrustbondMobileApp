"""
Send emails via Brevo HTTP API (preferred) or SMTP.
Uses settings from config; no-op if neither provider is configured.
"""
import smtplib
import socket
from html import escape
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Iterable

from app.config import settings
from app.core.brevo_email import (
    deliver_brevo_from_mime,
    is_brevo_configured,
    send_brevo_email,
)
from app.core.smtp_config import clean_env_value, resolve_smtp_host, smtp_settings_ready


EMAIL_LOGO_CID = "trustbond-logo"
EMAIL_LOGO_PATH = Path(__file__).resolve().parents[2] / "logo.jpeg"


def is_email_configured() -> bool:
    """True when Brevo or SMTP can send mail."""
    if is_brevo_configured():
        return bool(resolved_from_address())
    if getattr(settings, "smtp_disable", False):
        return False
    return smtp_settings_ready(settings.smtp_host, settings.smtp_user, settings.smtp_pass)


def is_smtp_configured() -> bool:
    """Backward-compatible alias for is_email_configured()."""
    return is_email_configured()


def resolved_from_address() -> str | None:
    from app.core.brevo_email import resolved_from_address as _brevo_from

    return _brevo_from()


def _smtp_dns_error_message(host: str) -> str:
    return (
        f"Cannot resolve SMTP server hostname '{host}'. "
        "Set SMTP_HOST to your provider's SMTP server (e.g. smtp.gmail.com for Gmail), "
        "not your email address. Ensure backend/.env is loaded or set SMTP_* in the host environment."
    )


def deliver_smtp_message(
    msg: MIMEMultipart,
    from_addr: str,
    to_addrs: Iterable[str],
) -> tuple[bool, str | None]:
    """Send a prepared MIME message via SMTP. Returns (success, error_message)."""
    host = resolve_smtp_host(settings.smtp_host, settings.smtp_user)
    user = clean_env_value(settings.smtp_user)
    password = clean_env_value(settings.smtp_pass)
    if not host or not user or not password:
        return False, "SMTP not configured (SMTP_HOST, SMTP_USER, SMTP_PASS required)"

    recipients = [a.strip() for a in to_addrs if a and str(a).strip()]
    if not recipients:
        return False, "No recipient email addresses provided."

    port = int(getattr(settings, "smtp_port", 587) or 587)
    timeout = max(3, int(getattr(settings, "smtp_timeout_seconds", 12) or 12))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                server.login(user, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(user, password)
                server.sendmail(from_addr, recipients, msg.as_string())
        return True, None
    except (socket.timeout, TimeoutError):
        err = "SMTP connection timed out. Check SMTP settings/network or reduce SMTP_TIMEOUT_SECONDS."
        print(f"[Email] Send failed: {err}")
        return False, err
    except OSError as e:
        errno = getattr(e, "errno", None)
        if errno in (-2, 11001, 11003) or "Name or service not known" in str(e) or "getaddrinfo failed" in str(e):
            err = _smtp_dns_error_message(host)
            print(f"[Email] Send failed: {err}")
            return False, err
        if errno == 101:
            err = (
                f"Network is unreachable when connecting to SMTP server {host}:{port}. "
                "This usually means outbound SMTP is blocked by the hosting provider/firewall. "
                "Allow egress to the SMTP host/port or switch to an email HTTP API provider."
            )
            print(f"[Email] Send failed: {err}")
            return False, err
        err = str(e).strip() or "SMTP send failed (OS error)."
        print(f"[Email] Send failed: {err}")
        return False, err
    except smtplib.SMTPAuthenticationError:
        err = "SMTP authentication failed. Check SMTP_USER and SMTP_PASS (use an app password for Gmail)."
        print(f"[Email] Send failed: {err}")
        return False, err
    except Exception as e:
        err = str(e).strip() or "SMTP send failed."
        print(f"[Email] Send failed: {err}")
        return False, err


def get_email_logo_src() -> str:
    return f"cid:{EMAIL_LOGO_CID}"


def deliver_email_message(
    msg: MIMEMultipart,
    from_addr: str,
    to_addrs: Iterable[str],
) -> tuple[bool, str | None]:
    """Send via Brevo when configured, otherwise SMTP."""
    if is_brevo_configured():
        return deliver_brevo_from_mime(msg, to_addrs)
    return deliver_smtp_message(msg, from_addr, to_addrs)


def send_email(to: str, subject: str, body_plain: str, body_html: str | None = None) -> tuple[bool, str | None]:
    """
    Send an email via Brevo (preferred) or SMTP.
    Returns (True, None) if sent, (False, error_message) if not configured or send failed.
    """
    if not is_email_configured():
        return False, (
            "Email is not configured. Set BREVO_API_KEY and BREVO_SENDER_EMAIL, "
            "or SMTP_HOST, SMTP_USER, and SMTP_PASS."
        )

    if is_brevo_configured():
        return send_brevo_email(
            to,
            subject,
            html=body_html,
            text=body_plain,
        )

    from_addr = clean_env_value(settings.smtp_from) or clean_env_value(settings.smtp_user) or ""
    embed_logo = bool(body_html and EMAIL_LOGO_PATH.exists())
    msg = MIMEMultipart("related") if embed_logo else MIMEMultipart("alternative")
    content = MIMEMultipart("alternative") if embed_logo else msg
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    content.attach(MIMEText(body_plain, "plain", "utf-8"))
    if body_html:
        content.attach(MIMEText(body_html, "html", "utf-8"))
    if embed_logo:
        msg.attach(content)
        with EMAIL_LOGO_PATH.open("rb") as logo_file:
            logo = MIMEImage(logo_file.read(), _subtype="jpeg")
        logo.add_header("Content-ID", f"<{EMAIL_LOGO_CID}>")
        logo.add_header("Content-Disposition", "inline", filename=EMAIL_LOGO_PATH.name)
        msg.attach(logo)
    return deliver_smtp_message(msg, from_addr, [to])


def send_new_user_credentials(
    to_email: str,
    first_name: str,
    last_name: str,
    login_email: str,
    temporary_password: str,
    role: str,
    badge_number: str | None = None,
    rank: str | None = None,
) -> tuple[bool, str | None]:
    """Send new police user their login credentials. Returns (True, None) if sent, (False, error_message) otherwise."""
    subject = "Welcome to TrustBond Police Dashboard"
    login_url = settings.frontend_url.rstrip("/")
    logo_src = get_email_logo_src()

    first_name_html = escape(first_name)
    last_name_html = escape(last_name)
    login_email_html = escape(login_email)
    temporary_password_html = escape(temporary_password)
    role_html = escape(role)
    badge_number_html = escape(badge_number) if badge_number else None
    login_url_html = escape(login_url)
    logo_src_html = escape(logo_src)

    rank_line = f"Rank: {rank}\n" if rank else ""
    badge_line = f"Badge number: {badge_number}\n" if badge_number else ""
    badge_line_html = (
        f"""
                <tr style="background:#ffffff;">
                    <td style="padding:12px 16px;font-size:13px;color:#185fa5;font-weight:600;">Badge number</td>
                    <td style="padding:12px 16px;font-size:13px;color:#0c447c;">{badge_number_html}</td>
          </tr>
"""
        if badge_number_html
        else ""
    )
    body_plain = f"""Hello {first_name} {last_name},

Your TrustBond Police Dashboard account has been created. You can now sign in with the details below.

Email: {login_email}
{rank_line}{badge_line}Temporary password: {temporary_password}
Role: {role}

Login: {login_url}

For your security, please sign in and update your temporary password as soon as possible.

This message was sent because an administrator created an account on your behalf.
If you did not expect this email, please contact your department administrator.

TrustBond
"""
    body_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TrustBond Email</title>
</head>
<body style="margin:0;padding:0;background:#eef4fb;font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;">

<div style="background:#eef4fb;padding:32px 16px;">
    <div style="max-width:600px;margin:0 auto;background-color:#ffffff;background-image:url('{logo_src_html}');background-repeat:no-repeat;background-position:center 58%;background-size:240px auto;border-radius:4px;overflow:hidden;border:1px solid #b5d4f4;">

        <div style="background:#185fa5;padding:28px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:collapse;">
                <tr>
                    <td width="54" valign="middle" style="padding:0 14px 0 0;">
                        <img src="{logo_src_html}" width="44" height="44" alt="TrustBond logo" style="display:block;width:44px;height:44px;border-radius:8px;background:#ffffff;border:1px solid #85b7eb;">
                    </td>
                    <td valign="middle" style="padding:0;">
                        <p style="margin:0 0 4px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#85b7eb;">
                            TrustBond Police Dashboard
                        </p>
                        <h2 style="margin:0;font-size:22px;font-weight:400;color:#ffffff;">
                            Your account is ready
                        </h2>
                    </td>
                </tr>
            </table>
        </div>

        <div style="padding:32px;">
            <p style="margin:0 0 10px;font-size:15px;color:#0c447c;">
                Hello {first_name_html} {last_name_html},
            </p>

            <p style="margin:0 0 24px;font-size:15px;color:#334155;line-height:1.6;">
                Your TrustBond Police Dashboard account has been created. You can now sign in with the details below.
                For your security, please update your temporary password as soon as possible.
            </p>

            <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #b5d4f4;">
                <tr style="background:#e6f1fb;">
                    <td style="padding:12px 16px;font-size:13px;color:#185fa5;font-weight:600;">Email</td>
                    <td style="padding:12px 16px;font-size:13px;color:#0c447c;">{login_email_html}</td>
                </tr>

{badge_line_html}        <tr style="background:#e6f1fb;">
                    <td style="padding:12px 16px;font-size:13px;color:#185fa5;font-weight:600;">Temporary password</td>
                    <td style="padding:12px 16px;font-size:13px;color:#0c447c;font-family:monospace;">{temporary_password_html}</td>
                </tr>

                <tr style="background:#ffffff;">
                    <td style="padding:12px 16px;font-size:13px;color:#185fa5;font-weight:600;">Role</td>
                    <td style="padding:12px 16px;font-size:13px;color:#0c447c;">{role_html.capitalize()}</td>
                </tr>
            </table>

            <div style="padding-top:28px;text-align:center;">
                <a href="{login_url_html}"
                     style="display:inline-block;background:#185fa5;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;padding:13px 30px;border-radius:3px;">
                    Sign in to Dashboard
                </a>
            </div>

            <p style="margin:16px 0 0;font-size:12px;color:#378add;text-align:center;">
                If the button does not work, copy this link:
                <a href="{login_url_html}" style="color:#0c447c;text-decoration:underline;">
                    {login_url_html}
                </a>
            </p>

            <hr style="margin:28px 0 20px;border:none;border-top:1px solid #b5d4f4;">

            <p style="margin:0;font-size:13px;color:#64748b;line-height:1.6;">
                This email was sent because an administrator created an account for you.
                If you were not expecting this message, please contact your department administrator.
            </p>

            <p style="margin:16px 0 0;font-size:13px;color:#185fa5;font-weight:600;">
                - TrustBond
            </p>
        </div>

        <div style="background:#e6f1fb;padding:14px 32px;border-top:1px solid #b5d4f4;">
            <p style="margin:0;font-size:11px;color:#378add;text-align:center;">
                TrustBond Police Dashboard - Confidential communication
            </p>
        </div>

    </div>
</div>

</body>
</html>
"""
    ok, err = send_email(to_email, subject, body_plain, body_html)
    return ok, None if ok else err


def send_password_reset_code(to_email: str, code: str) -> tuple[bool, str | None]:
    """Send password reset code to the user's email. Returns (True, None) if sent, (False, error_message) otherwise."""
    subject = "TrustBond - Your password reset code"
    logo_src_html = escape(get_email_logo_src())
    body_plain = f"""Hello,

We received a request to reset the password for your TrustBond Police Dashboard account.

Your verification code is: {code}

This code expires in 15 minutes. If you did not request a password reset, you can safely ignore this email.

TrustBond
"""
    body_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>TrustBond Password Reset</title>
</head>
<body style="margin:0;padding:0;background:#eef4fb;font-family:Segoe UI,Tahoma,Geneva,Verdana,sans-serif;">

<div style="background:#eef4fb;padding:32px 16px;">
    <div style="max-width:600px;margin:0 auto;background-color:#ffffff;background-image:url('{logo_src_html}');background-repeat:no-repeat;background-position:center 58%;background-size:220px auto;border-radius:4px;overflow:hidden;border:1px solid #b5d4f4;">

        <div style="background:#185fa5;padding:28px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="border-collapse:collapse;">
                <tr>
                    <td width="54" valign="middle" style="padding:0 14px 0 0;">
                        <img src="{logo_src_html}" width="44" height="44" alt="TrustBond logo" style="display:block;width:44px;height:44px;border-radius:8px;background:#ffffff;border:1px solid #85b7eb;">
                    </td>
                    <td valign="middle" style="padding:0;">
                        <p style="margin:0 0 4px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#85b7eb;">
                            TrustBond Police Dashboard
                        </p>
                        <h2 style="margin:0;font-size:22px;font-weight:400;color:#ffffff;">
                            Password reset code
                        </h2>
                    </td>
                </tr>
            </table>
        </div>

        <div style="padding:32px;">
            <p style="margin:0 0 16px;font-size:15px;color:#0c447c;">
                Hello,
            </p>

            <p style="margin:0 0 22px;font-size:15px;color:#334155;line-height:1.6;">
                We received a request to reset the password for your TrustBond Police Dashboard account.
            </p>

            <div style="margin:0 0 22px;padding:18px 20px;background:#e6f1fb;border:1px solid #b5d4f4;text-align:center;">
                <p style="margin:0 0 8px;font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#185fa5;font-weight:600;">
                    Verification code
                </p>
                <p style="margin:0;font-size:28px;letter-spacing:5px;color:#0c447c;font-family:Consolas,Menlo,monospace;font-weight:700;">
                    {escape(code)}
                </p>
            </div>

            <p style="margin:0;font-size:13px;color:#64748b;line-height:1.6;">
                This code expires in 15 minutes. If you did not request a password reset,
                you can safely ignore this email.
            </p>

            <p style="margin:16px 0 0;font-size:13px;color:#185fa5;font-weight:600;">
                - TrustBond
            </p>
        </div>

        <div style="background:#e6f1fb;padding:14px 32px;border-top:1px solid #b5d4f4;">
            <p style="margin:0;font-size:11px;color:#378add;text-align:center;">
                TrustBond Police Dashboard - Confidential communication
            </p>
        </div>

    </div>
</div>

</body>
</html>
"""
    return send_email(to_email, subject, body_plain, body_html)


def send_leader_new_incident_email(
    to_email: str,
    leader_name: str,
    report_number: str | None,
    village_label: str | None,
) -> tuple[bool, str | None]:
    rn = report_number or "new"
    loc = village_label or "your area"
    subject = f"TrustBond — New incident report ({rn})"
    body_plain = f"""Hello {leader_name},

A new incident report was submitted in {loc} (report {rn}).

Open the TrustBond Local Leader app to review and confirm or reject the incident.

TrustBond
"""
    return send_email(to_email.strip(), subject, body_plain, None)


def send_leader_account_ready_email(
    to_email: str,
    *,
    leader_name: str | None = None,
    role_label: str | None = None,
) -> tuple[bool, str | None]:
    """
    Notify a newly registered local leader that their account exists.
    Does not include an OTP — the leader requests a setup code in the mobile app.
    """
    to_email = (to_email or "").strip()
    greeting = f"Hello {leader_name}," if leader_name else "Hello,"
    role_line = f"\nYour role: {role_label}." if role_label else ""
    subject = "TrustBond — Your local leader account is ready"
    body_plain = f"""{greeting}

Your TrustBond local leader account has been registered by your police administrator.{role_line}

Open the TrustBond mobile app on your phone:
1. Go to Local leader sign-in
2. Choose first-time setup / set password
3. Enter your email ({to_email}) and tap to send a setup code
4. Enter the code from your email and choose your password

After that you can sign in with your email and password, or use email OTP login.

If you did not expect this message, contact your police administrator.

TrustBond
"""
    return send_email(to_email, subject, body_plain, None)


def send_unit_commander_hotspot_deployment_email(
    to_email: str,
    *,
    commander_name: str,
    unit_name: str,
    unit_code: str,
    hotspot_id: int,
    incident_count: int,
    area_label: str,
    deployed_by_name: str,
    note: str | None = None,
) -> tuple[bool, str | None]:
    """Notify the special-assignment unit commander that their unit was deployed to a hotspot."""
    subject = f"TrustBond — Deployment order: {unit_name} to {area_label}"
    body_plain = f"""Hello {commander_name},

You are the commander for {unit_name} ({unit_code}).

{deployed_by_name} has deployed your unit to hotspot #{hotspot_id} in {area_label}.
Verified incidents in this cluster: {incident_count}.

Please coordinate your team and acknowledge deployment in the TrustBond dashboard.

{f'Note: {note}' if note else ''}

TrustBond Police Operations
"""
    return send_email(to_email.strip(), subject, body_plain.strip(), None)


def send_leader_otp_email(
    to_email: str,
    code: str,
    purpose: str,
    *,
    leader_name: str | None = None,
) -> tuple[bool, str | None]:
    """
    purpose: 'login_otp' | 'password_setup'
    """
    to_email = (to_email or "").strip()
    greeting = f"Hello {leader_name}," if leader_name else "Hello,"
    if purpose == "login_otp":
        subject = "TrustBond — Login verification code"
        body_plain = f"""{greeting}

Your TrustBond local leader login code is: {code}

This code expires in 10 minutes. If you did not request it, ignore this email.

TrustBond
"""
    else:
        subject = "TrustBond — Password setup code"
        body_plain = f"""{greeting}

Your TrustBond local leader password setup code is: {code}

This code expires in 10 minutes. Open the TrustBond mobile app, go to leader first-time setup, and enter this code with your email ({to_email}).

If you did not request this code, ignore this email.

TrustBond
"""
    return send_email(to_email, subject, body_plain, None)
