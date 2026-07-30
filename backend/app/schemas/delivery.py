from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DeliveryStatsResponse(BaseModel):
    pending: int = 0
    publishing: int = 0
    published: int = 0
    retry_scheduled: int = 0
    failed: int = 0
    dead_lettered: int = 0


class DeliveryItemResponse(BaseModel):
    id: UUID
    channel_id: UUID
    channel_slug: str | None = None
    message_id: UUID | None = None
    event_type: str | None = None
    payload_type: str | None = None
    routing_key: str
    status: str
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    published_at: datetime | None = None
    dead_lettered_at: datetime | None = None


class DeliveryListResponse(BaseModel):
    items: list[DeliveryItemResponse]


class DeliveryRetryResponse(BaseModel):
    status: str = "ok"
    retried_count: int
    items: list[DeliveryItemResponse]
