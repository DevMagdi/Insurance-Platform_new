"""Application settings. All values come from env; nothing secret is committed."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Broker Hub"
    ENV: str = "dev"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # --- database ---
    DATABASE_URL: str = "postgresql+asyncpg://broker:broker@localhost:5432/broker_hub"
    DATABASE_URL_TEST: str = "sqlite+aiosqlite:///./dev_test.db"
    DB_ECHO: bool = False

    # --- auth ---
    JWT_SECRET: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 300

    # --- cors / security headers ---
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    TRUST_HOPS: int = 1

    # --- storage (recordings & attachments) ---
    STORAGE_BACKEND: str = "local"  # local | s3
    STORAGE_DIR: Path = Path("/tmp/broker-hub-objects")
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_BUCKET: str = "broker-hub"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    RECORDING_SIGNED_URL_TTL_SECONDS: int = 120
    RECORDING_RETENTION_DAYS: int = 180

    # --- integrations ---
    INTEGRATIONS_DRIVER: str = "sim"  # sim | live
    WHATSAPP_VERIFY_TOKEN: str = "dev-verify-token"
    WHATSAPP_APP_SECRET: str = "dev-app-secret"
    TELEPHONY_WEBHOOK_SECRET: str = "dev-telephony-secret"
    AI_ENABLED: bool = False

    # --- redis / celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = True

    # --- messaging ---
    # Prometheus scrape guard: /metrics is open in development, otherwise it needs this bearer token.
    METRICS_TOKEN: str = ""
    SMTP_URL: str = "smtp://localhost:1025"
    EMAIL_FROM: str = "no-reply@brokerhub.local"

    # --- SLA defaults (mirrored in DB table sla_policies; DB wins) ---
    WORKDAY_START: str = "09:00"
    WORKDAY_END: str = "18:00"
    WEEKEND_DAYS: list[int] = Field(default_factory=lambda: [4, 5])  # Fri, Sat (Egypt)
    TIMEZONE: str = "Africa/Cairo"
    REPLY_THREAD_WINDOW_MINUTES: int = 240

    @field_validator("JWT_SECRET")
    @classmethod
    def _reject_weak_secret(cls, v: str) -> str:
        if os.environ.get("ENV", "dev") == "prod" and (v == "dev-only-insecure-secret-change-me" or len(v) < 32):
            raise ValueError("JWT_SECRET must be a strong value (>=32 chars) when ENV=prod")
        return v

    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgres")


@lru_cache
def get_settings() -> Settings:
    return Settings()
