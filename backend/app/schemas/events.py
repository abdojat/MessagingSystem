from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EventResponse(BaseModel):
    id: UUID
    channel_id: UUID | None
    actor_user_id: UUID | None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    previous_hash: str | None = None
    event_hash: str | None = None
    hash_algorithm: str | None = None
    integrity_version: int | None = None
    integrity_scope: str | None = None


class EventListResponse(BaseModel):
    items: list[EventResponse]
    next_cursor: str | None
    has_more: bool


class EventIntegrityResponse(BaseModel):
    scope: str
    valid: bool
    checked_events: int
    broken_event_id: UUID | None = None
    reason: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    previous_event_id: UUID | None = None
    last_valid_hash: str | None = None
    first_event_id: UUID | None = None
    last_event_id: UUID | None = None
    hash_algorithm: str
    integrity_version: int
