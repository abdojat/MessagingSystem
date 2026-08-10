from functools import lru_cache
import base64
import json
from typing import Any

from pydantic import field_validator, model_validator
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
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 14

    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 5
    outbox_initial_retry_delay_seconds: int = 5
    outbox_retry_backoff_multiplier: float = 2.0
    outbox_max_retry_delay_seconds: int = 300
    worker_online_scan_interval: float = 3.0
    ws_history_batch_limit: int = 100

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
