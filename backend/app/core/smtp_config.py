"""Normalize SMTP settings from environment / .env."""
from __future__ import annotations

from urllib.parse import urlparse

# Common providers when SMTP_HOST is missing or set to the mailbox address by mistake.
_SMTP_HOST_BY_DOMAIN: dict[str, str] = {
    "gmail.com": "smtp.gmail.com",
    "googlemail.com": "smtp.gmail.com",
    "outlook.com": "smtp-mail.outlook.com",
    "hotmail.com": "smtp-mail.outlook.com",
    "live.com": "smtp-mail.outlook.com",
    "yahoo.com": "smtp.mail.yahoo.com",
}


def clean_env_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().strip('"').strip("'").strip()
    return cleaned or None


def resolve_smtp_host(host: str | None, smtp_user: str | None = None) -> str | None:
    """
    Return a connectable SMTP hostname.

    Fixes common misconfigurations:
    - SMTP_HOST set to the email address instead of smtp.gmail.com
    - smtp:// URL or host:port pasted into SMTP_HOST
    - Missing SMTP_HOST when SMTP_USER is a known provider
    """
    host = clean_env_value(host)
    user = clean_env_value(smtp_user)

    if host:
        lowered = host.lower()
        if lowered.startswith("smtp://") or lowered.startswith("smtps://"):
            parsed = urlparse(host if "://" in host else f"smtp://{host}")
            host = parsed.hostname or host
        elif "://" not in host and host.count(":") == 1 and not host.startswith("["):
            # host:port without scheme
            host = host.rsplit(":", 1)[0]

    if host and "@" in host:
        domain = host.split("@", 1)[1].lower()
        host = _SMTP_HOST_BY_DOMAIN.get(domain) or f"smtp.{domain}"

    if not host and user and "@" in user:
        domain = user.split("@", 1)[1].lower()
        host = _SMTP_HOST_BY_DOMAIN.get(domain) or f"smtp.{domain}"

    return clean_env_value(host)


def smtp_settings_ready(host: str | None, user: str | None, password: str | None) -> bool:
    return bool(resolve_smtp_host(host, user) and clean_env_value(user) and clean_env_value(password))
