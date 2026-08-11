from functools import lru_cache
import base64
from ipaddress import ip_network
import json
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Development conveniences must be selected explicitly. Every other label is
# production-like so deployment aliases and typos fail safe.
DEVELOPMENT_ENVIRONMENTS = {"dev", "development", "local", "test"}
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
    environment: str

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
    ws_history_batch_limit: int = Field(default=100, ge=1, le=500)
    ws_max_inbound_message_bytes: int = Field(default=16 * 1024, ge=1024, le=1024 * 1024)
    ws_command_budget_capacity: int = Field(default=60, ge=10, le=10_000)
    ws_command_budget_refill_per_second: float = Field(default=1.0, gt=0, le=1_000)
    ws_history_budget_capacity: int = Field(default=300, ge=1, le=100_000)
    ws_history_budget_refill_per_second: float = Field(default=5.0, gt=0, le=10_000)

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
    rate_limit_local_max_keys: int = Field(default=10_000, ge=1, le=1_000_000)

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
    max_concurrent_downloads_per_user: int = Field(default=3, ge=1, le=100)
    max_concurrent_downloads_per_ip: int = Field(default=12, ge=1, le=10_000)
    max_concurrent_downloads_global: int = Field(default=100, ge=1, le=100_000)
    # Empty in direct-development mode. The hardened Compose network sets one
    # private CIDR and its proxy overwrites X-Forwarded-For with one client IP.
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    # Matching membership generations avoid a database lookup for each normal
    # realtime message. The short TTL bounds legacy/pre-removal queued events
    # that do not force an immediate generation refresh.
    ws_membership_auth_cache_ttl_seconds: float = Field(default=1.0, ge=0.0, le=5.0)

    rabbit_user_queue_expires_ms: int = Field(default=7 * 24 * 60 * 60 * 1000, ge=60_000)
    rabbit_user_queue_message_ttl_ms: int = Field(default=24 * 60 * 60 * 1000, ge=1_000)
    rabbit_user_queue_max_length: int = Field(default=10_000, ge=1)
    redis_fanout_max_attempts: int = Field(default=3, ge=1, le=10)
    redis_fanout_initial_retry_delay_seconds: float = Field(default=0.5, ge=0.05, le=60)
    redis_fanout_max_retry_delay_seconds: float = Field(default=5.0, ge=0.05, le=300)

    log_level: str = "INFO"
    # An empty production list is a safe same-origin policy. Development
    # Compose supplies its explicit localhost origins through .env.
    cors_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver"])
    # None means derive from the explicit environment: secure in every
    # production-like environment and insecure only for explicit local/test
    # labels. Production may never explicitly opt out of Secure cookies.
    auth_cookie_secure: bool | None = None
    auth_cookie_samesite: Literal["strict", "lax"] = "strict"
    # Development retains interactive docs. Production-like environments
    # disable them unless an operator deliberately enables them.
    enable_api_docs: bool | None = None
    upload_max_size_bytes: int = 25 * 1024 * 1024
    # Applied by streaming ASGI middleware to ordinary HTTP request bodies.
    # Upload-content PUTs are exempt because their separate streaming service
    # enforces UPLOAD_MAX_SIZE_BYTES without buffering the file.
    api_request_body_max_bytes: int = Field(default=128 * 1024, ge=1024, le=10 * 1024 * 1024)
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
        return []

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def _parse_trusted_hosts(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(item).strip().lower() for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    pass
            return [part.strip().lower() for part in raw.split(",") if part.strip()]
        raise ValueError("TRUSTED_HOSTS must be a JSON list or comma-separated hostnames")

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("ENVIRONMENT must not be empty")
        return normalized

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_trusted_proxy_cidrs(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            values = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("TRUSTED_PROXY_CIDRS must be a JSON list or comma-separated CIDRs")
                values = [str(item).strip() for item in parsed if str(item).strip()]
            else:
                values = [part.strip() for part in raw.split(",") if part.strip()]
        else:
            raise ValueError("TRUSTED_PROXY_CIDRS must be a list or string")
        for value_item in values:
            ip_network(value_item, strict=False)
        return values

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        if self.environment in DEVELOPMENT_ENVIRONMENTS:
            return self

        if self.auth_cookie_secure is False:
            raise ValueError("AUTH_COOKIE_SECURE cannot be disabled in production-like environments")

        for origin in self.cors_origins:
            if origin == "*":
                raise ValueError("credentialed wildcard CORS is forbidden in production-like environments")
            parsed_origin = urlsplit(origin)
            if (
                parsed_origin.scheme.lower() != "https"
                or not parsed_origin.netloc
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                raise ValueError("production CORS origins must be explicit HTTPS origins")

        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise ValueError("TRUSTED_HOSTS must be explicit in production-like environments")

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

    @property
    def is_development_like(self) -> bool:
        return self.environment in DEVELOPMENT_ENVIRONMENTS

    @property
    def is_production_like(self) -> bool:
        return not self.is_development_like

    @property
    def browser_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.is_production_like

    @property
    def browser_refresh_cookie_name(self) -> str:
        return "__Host-messaging_refresh" if self.browser_cookie_secure else "messaging_refresh"

    @property
    def browser_csrf_cookie_name(self) -> str:
        return "__Host-messaging_csrf" if self.browser_cookie_secure else "messaging_csrf"

    @property
    def api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return self.is_development_like


@lru_cache
def get_settings() -> Settings:
    return Settings()
