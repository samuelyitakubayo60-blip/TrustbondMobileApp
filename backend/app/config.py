import os
import logging
from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "TrustBond API"
    debug: bool = False
    database_url: str = "postgresql://postgres:postgres@localhost:5432/trustbond"
    secret_key: str = "change-me-in-production"

    # CORS: comma-separated origins, e.g. "https://dashboard.trustbond.rw". Empty = allow all ("*").
    cors_origins: str = ""
    # Optional regex for dynamic origins (e.g. ngrok): r"https://.*\\.ngrok-free\\.dev"
    cors_origin_regex: Optional[str] = None

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
    # Base URL of the police dashboard (for login link in email)
    frontend_url: str = "http://localhost:5173"

    # How many hours after submitting a report the user (device) can still add evidence (mobile).
    evidence_add_window_hours: int = 72
    # Optional semantic description matcher (disabled by default to avoid model downloads/runtime overhead).
    enable_semantic_match: bool = False

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

    # eSMS Africa (OTP SMS)
    esms_base_url: str = "https://sms.esmsafrica.io"
    esms_token: Optional[str] = None
    esms_timeout_seconds: int = 12

    # Device anti-abuse guardrails for report creation.
    duplicate_report_time_window_seconds: int = 120
    duplicate_report_radius_meters: int = 250
    device_activity_window_minutes: int = 30
    impossible_travel_window_seconds: int = 300
    impossible_travel_min_distance_km: float = 20.0
    max_plausible_speed_kmh: float = 250.0

    def get_cors_origins_list(self) -> List[str]:
        default_local_origins = [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ]

        # Auto-detect frontend URL from frontend_url setting
        auto_detected_origins = []
        if self.frontend_url and self.frontend_url.strip():
            frontend_url = self.frontend_url.strip()
            # Add both http and https variants for the frontend URL
            if frontend_url.startswith("http://"):
                auto_detected_origins.append(frontend_url)
                auto_detected_origins.append(frontend_url.replace("http://", "https://"))
            elif frontend_url.startswith("https://"):
                auto_detected_origins.append(frontend_url)
                auto_detected_origins.append(frontend_url.replace("https://", "http://"))

        if not self.cors_origins or not self.cors_origins.strip():
            # If no explicit CORS origins, use auto-detected + defaults
            all_origins = auto_detected_origins + default_local_origins
            return list(set(all_origins)) if all_origins else ["*"]

        configured = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if "*" in configured:
            return ["*"]

        # Merge configured origins with auto-detected and defaults
        merged: List[str] = []
        for origin in configured + auto_detected_origins + default_local_origins:
            if origin not in merged:
                merged.append(origin)
        return merged

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


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
