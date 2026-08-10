from functools import lru_cache
import base64
import json
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PRODUCTION_ENVIRONMENTS = {"prod", "production", "staging"}
INSECURE_JWT_SECRETS = {
    "change-me",
    "change-this-jwt-secret",
    "dev-only-change-this-jwt-secret",
    "changeme",
    "jwt-secret",
    "secret",
    "your-jwt-secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "channels-backend"
    environment: str = "dev"

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = "change-me"
    jwt_access_ttl_min: int = Field(default=30, gt=0)
    jwt_refresh_ttl_days: int = Field(default=14, gt=0)
    session_absolute_ttl_days: int = Field(default=30, gt=0)
    ws_ticket_ttl_seconds: int = Field(default=30, ge=5, le=120)

    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 5
    outbox_initial_retry_delay_seconds: int = 5
    outbox_retry_backoff_multiplier: float = 2.0
    outbox_max_retry_delay_seconds: int = 300
    worker_online_scan_interval: float = 3.0
    ws_history_batch_limit: int = 100

    # Phase 3 abuse-control groups. Sensitive operations use an in-process
    # emergency limiter when Redis is unavailable; ordinary reads remain
    # available and are bounded by pagination instead.
    rate_limit_auth_ip_per_minute: int = Field(default=30, gt=0)
    rate_limit_auth_identity_per_minute: int = Field(default=20, gt=0)
    rate_limit_search_per_minute: int = Field(default=60, gt=0)
    rate_limit_message_write_per_10_seconds: int = Field(default=200, gt=0)
    rate_limit_message_write_burst_per_second: int = Field(default=40, gt=0)
    rate_limit_media_per_minute: int = Field(default=60, gt=0)
    rate_limit_channel_management_per_minute: int = Field(default=30, gt=0)
    rate_limit_websocket_per_minute: int = Field(default=30, gt=0)
    rate_limit_sync_per_minute: int = Field(default=60, gt=0)
    rate_limit_admin_per_minute: int = Field(default=60, gt=0)

    message_text_max_bytes: int = Field(default=64 * 1024, ge=1024)
    message_json_max_bytes: int = Field(default=64 * 1024, ge=1024)
    message_json_max_depth: int = Field(default=20, ge=2, le=100)
    max_distinct_reactions_per_message: int = Field(default=20, ge=1, le=100)

    max_channels_owned_per_user: int = Field(default=50, ge=1)
    max_active_invites_per_user: int = Field(default=100, ge=1)
    max_uploads_per_user_per_day: int = Field(default=100, ge=1)
    max_pending_uploads_per_user: int = Field(default=10, ge=1)
    max_stored_upload_bytes_per_user: int = Field(default=1024 * 1024 * 1024, ge=1)
    max_websocket_connections_per_user: int = Field(default=5, ge=1, le=100)

    rabbit_user_queue_expires_ms: int = Field(default=7 * 24 * 60 * 60 * 1000, ge=60_000)
    rabbit_user_queue_message_ttl_ms: int = Field(default=24 * 60 * 60 * 1000, ge=1_000)
    rabbit_user_queue_max_length: int = Field(default=10_000, ge=1)
    redis_fanout_max_attempts: int = Field(default=3, ge=1, le=10)
    redis_fanout_initial_retry_delay_seconds: float = Field(default=0.5, ge=0.05, le=60)
    redis_fanout_max_retry_delay_seconds: float = Field(default=5.0, ge=0.05, le=300)

    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    upload_max_size_bytes: int = 25 * 1024 * 1024
    uploads_base_dir: str = "/data/uploads"
    api_v1_prefix: str = "/v1"
    message_encryption_enabled: bool = True
    message_encryption_key: str = ""
    superadmin_username: str = ""
    superadmin_email: str = ""
    superadmin_password: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> list[str]:
        # Operators may provide CORS origins as JSON, comma-separated text, or a
        # native list depending on whether they run Docker, tests, or local dev.
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [part.strip() for part in raw.split(",") if part.strip()]
        return ["http://localhost:3000", "http://localhost:5173"]

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        environment = self.environment.strip().lower()
        if environment not in PRODUCTION_ENVIRONMENTS:
            return self

        jwt_secret = self.jwt_secret.strip()
        if not jwt_secret:
            raise ValueError("JWT_SECRET is required in production-like environments")
        if jwt_secret.lower() in INSECURE_JWT_SECRETS:
            raise ValueError("JWT_SECRET cannot use a known development placeholder in production-like environments")
        # HS256 accepts arbitrary strings, so enforce a conservative minimum
        # length and basic diversity to reject short or obviously predictable
        # deployment secrets before the application starts.
        if len(jwt_secret) < 32 or len(set(jwt_secret)) < 8:
            raise ValueError("JWT_SECRET must be at least 32 characters with reasonable entropy")

        if self.message_encryption_enabled:
            encryption_key = self.message_encryption_key.strip()
            if not encryption_key:
                raise ValueError("MESSAGE_ENCRYPTION_KEY is required when encryption is enabled")
            try:
                decoded_key = base64.b64decode(encryption_key.encode("ascii"), altchars=b"-_", validate=True)
            except (ValueError, UnicodeEncodeError) as exc:
                raise ValueError("MESSAGE_ENCRYPTION_KEY must be a valid Fernet key") from exc
            if len(decoded_key) != 32:
                raise ValueError("MESSAGE_ENCRYPTION_KEY must be a valid Fernet key")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
