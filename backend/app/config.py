from typing import Optional, List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "TrustBond API"
    debug: bool = False
    database_url: str = "postgresql://postgres:postgres@localhost:5432/trustbond"
    secret_key: str = "change-me-in-production"

    # CORS: comma-separated origins, e.g. "https://dashboard.trustbond.rw". Empty = allow all ("*").
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
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

        if not self.cors_origins or not self.cors_origins.strip():
            return ["*"]

        configured = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if "*" in configured:
            return ["*"]

        merged: List[str] = []
        for origin in configured + default_local_origins:
            if origin not in merged:
                merged.append(origin)
        return merged

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
