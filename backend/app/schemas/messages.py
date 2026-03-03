from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


class PublishMessageRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "PublishMessageRequest":
        if bool(self.content_text) == bool(self.content_json):
            raise ValueError("provide exactly one of content_text or content_json")
        return self


class MessageResponse(BaseModel):
    id: UUID
    channel_id: UUID
    sender_user_id: UUID
    seq_id: int
    content_type: str
    content_text: str | None
    content_json: dict[str, Any] | None
    created_at: datetime


class SeenRequest(BaseModel):
    last_seen_message_id: UUID | None = None
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None


class SeenResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    last_seen_seq_id: int | None
    unread_count: int
