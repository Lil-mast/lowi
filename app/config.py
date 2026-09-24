"""Application settings loaded from the environment and an optional .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
