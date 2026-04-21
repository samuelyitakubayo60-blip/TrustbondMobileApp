"""
Send emails via SMTP (e.g. new user credentials).
Uses settings from config; no-op if SMTP not configured.
"""
import smtplib
import socket
from html import escape
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

from app.config import settings


EMAIL_LOGO_CID = "trustbond-logo"
EMAIL_LOGO_PATH = Path(__file__).resolve().parents[2] / "logo.jpeg"


def is_smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


def get_email_logo_src() -> str:
    return f"cid:{EMAIL_LOGO_CID}"


def send_email(to: str, subject: str, body_plain: str, body_html: str | None = None) -> tuple[bool, str | None]:
    """
    Send an email. Returns (True, None) if sent, (False, error_message) if not configured or send failed.
    """
    if not is_smtp_configured():
        return False, "SMTP not configured (SMTP_HOST, SMTP_USER, SMTP_PASS required)"
    from_addr = settings.smtp_from or settings.smtp_user
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
    try:
        port = getattr(settings, "smtp_port", 587) or 587
        timeout = max(3, int(getattr(settings, "smtp_timeout_seconds", 12) or 12))
        if port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, port, timeout=timeout) as server:
                server.login(settings.smtp_user, settings.smtp_pass)
                server.sendmail(from_addr, [to], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, port, timeout=timeout) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_pass)
                server.sendmail(from_addr, [to], msg.as_string())
        return True, None
    except (socket.timeout, TimeoutError):
        err = "SMTP connection timed out. Check SMTP settings/network or reduce SMTP_TIMEOUT_SECONDS."
        print(f"[Email] Send failed: {err}")
        return False, err
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
{badge_line}Temporary password: {temporary_password}
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
