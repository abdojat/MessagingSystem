from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    redis_url: str = "redis://redis:6379/0"

    outbox_poll_interval: float = 1.0
    outbox_max_attempts: int = 5
    outbox_initial_retry_delay_seconds: int = 5
    outbox_retry_backoff_multiplier: float = 2.0
    outbox_max_retry_delay_seconds: int = 300
    worker_online_scan_interval: float = 3.0
    log_level: str = "INFO"
    rabbit_user_queue_expires_ms: int = Field(default=7 * 24 * 60 * 60 * 1000, ge=60_000)
    rabbit_user_queue_message_ttl_ms: int = Field(default=24 * 60 * 60 * 1000, ge=1_000)
    rabbit_user_queue_max_length: int = Field(default=10_000, ge=1)
    redis_fanout_max_attempts: int = Field(default=3, ge=1, le=10)
    redis_fanout_initial_retry_delay_seconds: float = Field(default=0.5, ge=0.05, le=60)
    redis_fanout_max_retry_delay_seconds: float = Field(default=5.0, ge=0.05, le=300)


@lru_cache
def get_settings() -> Settings:
    return Settings()
