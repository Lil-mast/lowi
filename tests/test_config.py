from __future__ import annotations

import pytest
from app.config import Settings, normalize_database_url, validate_settings


def test_development_defaults_are_valid():
    validate_settings(Settings(_env_file=None))


def test_production_requires_neon_auth_and_arq():
    with pytest.raises(ValueError, match="AUTH_MODE"):
        validate_settings(
            Settings(
                _env_file=None,
                app_env="production",
                auth_mode="dev",
                secret_key="x" * 32,
                job_backend="arq",
            )
        )

    with pytest.raises(ValueError, match="JOB_BACKEND"):
        validate_settings(
            Settings(
                _env_file=None,
                app_env="production",
                auth_mode="neon",
                secret_key="x" * 32,
                job_backend="inline",
                neon_auth_base_url="https://auth.example/auth",
                neon_auth_jwks_url="https://auth.example/auth/.well-known/jwks.json",
            )
        )


def test_neon_auth_requires_urls():
    with pytest.raises(ValueError, match="NEON_AUTH_BASE_URL"):
        validate_settings(Settings(_env_file=None, auth_mode="neon"))
    with pytest.raises(ValueError, match="NEON_AUTH_JWKS_URL"):
        validate_settings(
            Settings(
                _env_file=None,
                auth_mode="neon",
                neon_auth_base_url="https://auth.example/auth",
            )
        )


def test_s3_requires_a_bucket():
    with pytest.raises(ValueError, match="S3_BUCKET"):
        validate_settings(Settings(_env_file=None, storage_backend="s3"))


def test_production_valid_settings_pass():
    validate_settings(
        Settings(
            _env_file=None,
            app_env="production",
            auth_mode="neon",
            secret_key="x" * 32,
            job_backend="arq",
            neon_auth_base_url="https://auth.example/auth",
            neon_auth_jwks_url="https://auth.example/auth/.well-known/jwks.json",
            storage_backend="s3",
            s3_bucket="bucket",
            public_base_url="https://api.example.com",
            ui_base_url="https://ui.example.com",
        )
    )


def test_production_rejects_short_secret_key():
    with pytest.raises(ValueError, match="32 characters"):
        validate_settings(
            Settings(
                _env_file=None,
                app_env="production",
                auth_mode="neon",
                secret_key="short",
                job_backend="arq",
                neon_auth_base_url="https://auth.example/auth",
                neon_auth_jwks_url="https://auth.example/auth/.well-known/jwks.json",
                storage_backend="s3",
                s3_bucket="bucket",
                public_base_url="https://api.example.com",
                ui_base_url="https://ui.example.com",
            )
        )


def test_normalize_database_url_upgrades_postgres_driver():
    assert (
        normalize_database_url("postgres://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )
    assert normalize_database_url("sqlite:///local.db") == "sqlite:///local.db"
