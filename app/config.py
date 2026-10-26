"""Application settings loaded from the environment and an optional .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "production", "test"]
AuthMode = Literal["dev", "neon", "test"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: AppEnv = "development"
    database_url: str = "sqlite:///./data/lowi.db"
    elevenlabs_api_key: str = ""
    agentrouter_api_key: str = ""
    agentrouter_base_url: str = "https://agentrouter.org/v1"
    agentrouter_summary_model: str = "claude-opus-4-8"
    agentrouter_prep_model: str = "deepseek-v4-flash"
    discord_webhook_url: str = ""
    data_dir: Path = Path("data")
    secret_key: str = "change-me"
    redis_url: str = "redis://localhost:6379"
    default_user_email: str = "local@lowi.local"
    default_user_name: str = "Local"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/calendar/callback"
    google_refresh_token: str = ""
    google_oauth_enabled: bool = False

    # Auth
    auth_mode: AuthMode = "dev"
    neon_auth_base_url: str = ""
    neon_auth_jwks_url: str = ""
    neon_auth_issuer: str = ""
    neon_auth_audience: str = ""
    session_ttl_days: int = 30
    test_user_email: str = "test@lowi.local"
    test_user_name: str = "Test"

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_force_path_style: bool = True
    max_upload_mb: int = 500

    # Jobs
    job_backend: Literal["inline", "arq"] = "inline"

    # Public URLs
    public_base_url: str = "http://127.0.0.1:8000"
    ui_base_url: str = "http://127.0.0.1:8501"
    log_level: str = "INFO"


def validate_settings(settings: Settings) -> None:
    """Fail fast on unsafe or incomplete production configuration."""
    if settings.app_env == "production":
        if settings.auth_mode != "neon":
            raise ValueError("AUTH_MODE must be 'neon' when APP_ENV=production")
        if settings.secret_key == "change-me":
            raise ValueError("SECRET_KEY must be set when APP_ENV=production")
        if settings.job_backend != "arq":
            raise ValueError("JOB_BACKEND must be 'arq' when APP_ENV=production")

    if settings.auth_mode == "neon":
        missing = [
            name
            for name, value in (
                ("NEON_AUTH_BASE_URL", settings.neon_auth_base_url),
                ("NEON_AUTH_JWKS_URL", settings.neon_auth_jwks_url),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing auth configuration: {', '.join(missing)}")

    if settings.session_ttl_days < 1:
        raise ValueError("SESSION_TTL_DAYS must be at least 1")

    if settings.storage_backend == "s3" and not settings.s3_bucket:
        raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")

    if settings.max_upload_mb < 1:
        raise ValueError("MAX_UPLOAD_MB must be at least 1")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def normalize_database_url(url: str) -> str:
    """Point Postgres URLs at the psycopg 3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
