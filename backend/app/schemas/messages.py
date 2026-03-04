from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PublishMessageRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    reply_to_message_id: UUID | None = None
    reply_to_seq_id: int | None = Field(default=None, ge=1)
    attachments: list[dict[str, Any]] | None = None
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
    content_type: Literal["text", "json"]
    content_text: str | None
    content_json: dict[str, Any] | None
    reply_to_message_id: UUID | None = None
    reply_to_seq_id: int | None = None
    attachments: list[dict[str, Any]] | None = None
    is_pinned: bool = False
    client_msg_id: UUID | None
    created_at: datetime
    updated_at: datetime | None = None
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    reactions_summary: dict[str, Any] | None = None


class MessagePatchRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "MessagePatchRequest":
        has_text = self.content_text is not None
        has_json = self.content_json is not None
        if has_text == has_json:
            raise ValueError("provide exactly one of content_text or content_json")
        if has_text and not self.content_text.strip():
            raise ValueError("content_text cannot be empty")
        return self


class ReactionRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=64)


class ReactionSummaryResponse(BaseModel):
    counts: dict[str, int]
    my_reaction: list[str]


class PinListResponse(BaseModel):
    items: list[MessageResponse]


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    checksum: str | None = Field(default=None, max_length=255)


class UploadCreateResponse(BaseModel):
    file_id: UUID
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    public_url: str | None = None


class SyncChannelCursor(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = Field(default=None, ge=0)


class SyncRequest(BaseModel):
    channels: list[SyncChannelCursor] = Field(default_factory=list)
    since: datetime | None = None
    limit: int = Field(default=500, ge=1, le=2000)


class SyncMembershipUpdate(BaseModel):
    channel_id: UUID
    user_id: UUID
    new_role: Literal["owner", "admin", "member", "pending", "none"]
    reason: str
    updated_at: datetime


class SyncChannelUpdate(BaseModel):
    channel_id: UUID
    patch: dict[str, Any]
    updated_at: datetime


class SyncResponse(BaseModel):
    server_time: datetime
    channel_updates: list[SyncChannelUpdate]
    membership_updates: list[SyncMembershipUpdate]
    messages: list[MessageResponse]


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    next_before_seq_id: int | None
    next_after_seq_id: int | None
    has_more: bool
    order: Literal["asc", "desc"]


class SeenRequest(BaseModel):
    last_seen_message_id: UUID | None = None
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None

    @model_validator(mode="after")
    def validate_required_marker(self) -> "SeenRequest":
        has_message = self.last_seen_message_id is not None
        has_seq = self.last_seen_seq_id is not None
        if has_message == has_seq:
            raise ValueError("provide exactly one of last_seen_message_id or last_seen_seq_id")
        return self


class SeenResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    last_seen_seq_id: int | None
    last_seen_message_id: UUID | None
    last_seen_at: datetime | None
    unread_count: int | None


class MessageAroundResponse(BaseModel):
    seq_id: int
    items: list[MessageResponse]
