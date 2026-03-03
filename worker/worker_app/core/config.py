from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    redis_url: str = "redis://redis:6379/0"

    outbox_poll_interval: float = 1.0
    worker_online_scan_interval: float = 3.0
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
