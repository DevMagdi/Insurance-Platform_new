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

    # --- secrets at rest (ADR-016) ---
    # A Fernet key (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`)
    # or any passphrase >=16 chars. Unset in development ⇒ derived from JWT_SECRET; required in prod.
    SECRETS_ENCRYPTION_KEY: str = ""
    # Set only while rotating the key above: blobs written under the retired key stay readable, every new
    # write uses the current one. Clear it once the values have been re-saved — the window is not permanent.
    SECRETS_ENCRYPTION_KEY_OLD: str = ""

    # --- integrations ---
    # `INTEGRATIONS_DRIVER` is the *fallback*: a saved row in `integration_configs` wins over it (ADR-016),
    # so the settings screen — not a file on the server — is the normal way to go live.
    INTEGRATIONS_DRIVER: str = "sim"  # sim | live
    # WhatsApp Business Cloud API
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_APP_SECRET: str = "dev-app-secret"
    WHATSAPP_VERIFY_TOKEN: str = "dev-verify-token"
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    # Telephony / cloud PBX
    TELEPHONY_PROVIDER: str = "generic"  # generic | sim
    TELEPHONY_WEBHOOK_SECRET: str = "dev-telephony-secret"
    TELEPHONY_API_KEY: str = ""
    TELEPHONY_WEBHOOK_URL: str = ""
    AI_ENABLED: bool = False

    # --- redis / celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = True

    # --- messaging ---
    # Prometheus scrape guard: /metrics is open in development, otherwise it needs this bearer token.
    METRICS_TOKEN: str = ""
    # `SMTP_URL` is what the mailer connects to. `SMTP_HOST`/`SMTP_PORT` are the override the settings
    # screen edits (and, when set, they win over the URL) — empty means "whatever the URL says", so the
    # screen never shows a host that is not in use.
    SMTP_URL: str = "smtp://localhost:1025"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 0
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_ENCRYPTION: str = "none"  # none | starttls | ssl
    SMTP_FROM_NAME: str = "Broker Hub"
    EMAIL_FROM: str = "no-reply@brokerhub.local"
    SMTP_REPLY_TO: str = ""

    # --- SLA defaults (mirrored in DB table sla_policies; DB wins) ---
    WORKDAY_START: str = "09:00"
    WORKDAY_END: str = "18:00"
    WEEKEND_DAYS: list[int] = Field(default_factory=lambda: [4, 5])  # Fri, Sat (Egypt)
    TIMEZONE: str = "Africa/Cairo"
    REPLY_THREAD_WINDOW_MINUTES: int = 240

    @field_validator("SMTP_ENCRYPTION")
    @classmethod
    def _smtp_encryption(cls, v: str) -> str:
        if v not in {"none", "starttls", "ssl"}:
            raise ValueError("SMTP_ENCRYPTION must be none | starttls | ssl")
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def _reject_weak_secret(cls, v: str) -> str:
        if os.environ.get("ENV", "dev") == "prod" and (v == "dev-only-insecure-secret-change-me" or len(v) < 32):
            raise ValueError("JWT_SECRET must be a strong value (>=32 chars) when ENV=prod")
        return v

    # --- deployment ---
    # Absolute origin used to render webhook URLs for copy-paste (Meta asks for a public callback URL).
    PUBLIC_BASE_URL: str = "http://localhost:5173"

    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgres")

    @property
    def smtp_endpoint(self) -> tuple[str, int]:
        """The host/port actually used to send: the discrete override if set, else the parsed URL."""
        if self.SMTP_HOST.strip():
            return self.SMTP_HOST.strip(), self.SMTP_PORT or 1025
        rest = self.SMTP_URL.strip().replace("smtp://", "").replace("smtp+tls://", "").split("@")[-1]
        host, _, port = rest.partition(":")
        return host or "localhost", int(port or 1025)

    @property
    def smtp_url(self) -> str:
        """One place assembles the DSN, so no driver parses two shapes."""
        host, port = self.smtp_endpoint
        auth = f"{self.SMTP_USERNAME}@" if self.SMTP_USERNAME else ""
        return f"smtp://{auth}{host}:{port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
