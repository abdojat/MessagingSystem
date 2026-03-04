from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PublishMessageRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    client_msg_id: UUID | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "PublishMessageRequest":
        has_text = self.content_text is not None
        has_json = self.content_json is not None
        if has_text == has_json:
            raise ValueError("provide exactly one of content_text or content_json")
        if has_text and not self.content_text.strip():
            raise ValueError("content_text cannot be empty")
        return self


class MessageResponse(BaseModel):
    id: UUID
    channel_id: UUID
    sender_user_id: UUID
    seq_id: int
    content_type: str
    content_text: str | None
    content_json: dict[str, Any] | None
    client_msg_id: UUID | None
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    next_before_seq_id: int | None
    next_after_seq_id: int | None
    has_more: bool


class SeenRequest(BaseModel):
    last_seen_message_id: UUID | None = None
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None

    @model_validator(mode="after")
    def validate_required_marker(self) -> "SeenRequest":
        if self.last_seen_message_id is None and self.last_seen_seq_id is None:
            raise ValueError("provide at least one of last_seen_message_id or last_seen_seq_id")
        return self


class SeenResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    last_seen_seq_id: int | None
    last_seen_message_id: UUID | None
    last_seen_at: datetime | None
    unread_count: int


class MessageAroundResponse(BaseModel):
    seq_id: int
    items: list[MessageResponse]
