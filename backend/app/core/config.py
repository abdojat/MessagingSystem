from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    worker_online_scan_interval: float = 3.0
    ws_history_batch_limit: int = 100

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
