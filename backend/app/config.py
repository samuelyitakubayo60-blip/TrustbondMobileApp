import os
import logging
from pathlib import Path
from typing import Optional, List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.smtp_config import clean_env_value, resolve_smtp_host

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "TrustBond API"
    debug: bool = False
    database_url: str = "postgresql://postgres:postgres@localhost:5432/trustbond"
    secret_key: str = "change-me-in-production"

    # CORS: comma-separated origins, e.g. "https://dashboard.trustbond.rw".
    # Leave empty to allow all origins (default for deployed environments).
    cors_origins: str = ""

    # Optional Cloudinary configuration (pulled from .env if present)
    cloudinary_cloud_name: Optional[str] = None
    cloudinary_api_key: Optional[str] = None
    cloudinary_api_secret: Optional[str] = None

    # Optional SMTP for sending user credentials email
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_timeout_seconds: int = 12
    # Set SMTP_DISABLE=true on hosts that block outbound SMTP (e.g. Render free tier).
    smtp_disable: bool = False
    # Brevo transactional email API (preferred on HF Space / Render). Docs: https://developers.brevo.com/
    brevo_api_key: Optional[str] = None
    brevo_sender_email: Optional[str] = None
    brevo_sender_name: str = "TrustBond"
    brevo_api_url: str = "https://api.brevo.com/v3/smtp/email"
    brevo_timeout_seconds: int = 30
    # Base URL of the police dashboard (for login link in email)
    frontend_url: str = "http://localhost:5173"

    @field_validator(
        "smtp_host",
        "smtp_user",
        "smtp_pass",
        "smtp_from",
        "brevo_api_key",
        "brevo_sender_email",
        "brevo_sender_name",
        mode="before",
    )
    @classmethod
    def _strip_smtp_strings(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        return clean_env_value(value)

    def resolved_smtp_host(self) -> str | None:
        return resolve_smtp_host(self.smtp_host, self.smtp_user)

    # How many hours after submitting a report the user (device) can still add evidence (mobile).
    evidence_add_window_hours: int = 72
    # Optional semantic description matcher (disabled by default to avoid model downloads/runtime overhead).
    enable_semantic_match: bool = False
    # Run unified verification backlog on API startup (replaces legacy ml_evaluator auto-verify).
    verification_startup_backlog_enabled: bool = True

    # Optional LLM narrative generation for human-like AI explanations.
    llm_narrative_enabled: bool = True
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_use_local_fallback: bool = True
    # Hugging Face id or path, cached under backend/models/local_narrative/…
    # Default: open instruct causal LM (~1.5B) — better prose than FLAN-T5-small; expect ~3–4GB disk and ~4–8GB RAM on CPU inference (more if GPU).
    llm_local_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    # New tokens per local generate() call (512–1024 typical for 1.5B instruct; lower if OOM or slow on CPU).
    llm_local_max_new_tokens: int = 768
    llm_timeout_seconds: int = 12
    llm_max_tokens: int = 420

    # Hugging Face Hub (optional). Set in .env as HF_TOKEN=... or hf_token=... for authenticated downloads
    # and to avoid "unauthenticated requests" warnings from huggingface_hub / transformers.
    hf_token: Optional[str] = None

    # Local leader workflow: require community confirmation before DPU map analytics, hotspots, auto-cases.
    require_leader_confirmation_for_workflow: bool = True
    # Legacy alias — runtime gates use require_leader_confirmation_for_workflow via leader_gate_enabled().
    dpu_analytics_require_leader_confirmation: bool = True
    notify_local_leaders_new_report_email: bool = True
    # FCM HTTP v1: path to Firebase service account JSON (same project as the mobile app).
    firebase_credentials_path: Optional[str] = None
    # Optional override; defaults to project_id inside the JSON file.
    firebase_project_id: Optional[str] = None
    notify_local_leaders_new_report_fcm: bool = True
    notify_citizen_report_status_fcm: bool = True

    # Device anti-abuse guardrails for report creation.
    duplicate_report_time_window_seconds: int = 120
    duplicate_report_radius_meters: int = 250
    device_activity_window_minutes: int = 30
    impossible_travel_window_seconds: int = 300
    impossible_travel_min_distance_km: float = 20.0
    max_plausible_speed_kmh: float = 250.0

    def get_cors_origins_list(self) -> List[str]:
        if not self.cors_origins or not self.cors_origins.strip():
            # No explicit list configured → open to all (handled via regex in middleware)
            return []

        configured = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return configured

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def _sync_hf_hub_token_to_environ() -> None:
    # Support common token variable names used across HF docs/CI platforms.
    env_candidates = (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HF_API_TOKEN",
    )
    tok = (
        (getattr(settings, "hf_token", None) or "").strip()
        or next((os.environ.get(k, "").strip() for k in env_candidates if os.environ.get(k, "").strip()), "")
    )
    if tok:
        for k in env_candidates:
            os.environ.setdefault(k, tok)
    else:
        # Keep startup logs clean when anonymous Hub access is intentional.
        # (Model loading still works without a token, just with lower rate limits.)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


_sync_hf_hub_token_to_environ()
