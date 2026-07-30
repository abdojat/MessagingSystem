from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Defines the attachment reference API data contract; Pydantic uses it while validating or serializing API data.
class AttachmentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: UUID


# Defines the publish message request API data contract; Pydantic uses it while validating or serializing API data.
class PublishMessageRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None
    reply_to_message_id: UUID | None = None
    reply_to_seq_id: int | None = Field(default=None, ge=1)
    attachments: list[AttachmentReference] | None = Field(default=None, max_length=10)
    client_msg_id: UUID | None = None

    # Validates content; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_content(self) -> "PublishMessageRequest":
        has_text = self.content_text is not None
        has_json = self.content_json is not None
        has_attachments = bool(self.attachments)
        # Reject the operation when `has_text and has_json` to keep invalid state from progressing.
        if has_text and has_json:
            raise ValueError("provide at most one of content_text or content_json")
        # Reject the operation when `not has_text and (not has_json) and (not has_attachments)` to keep invalid state from progressing.
        if not has_text and not has_json and not has_attachments:
            raise ValueError("provide content_text, content_json, or at least one attachment")
        # Reject the operation when `has_text and (not self.content_text.strip())` to keep invalid state from progressing.
        if has_text and not self.content_text.strip():
            raise ValueError("content_text cannot be empty")
        # Run this conditional step only when `self.attachments` is true.
        if self.attachments:
            file_ids = [item.file_id for item in self.attachments]
            # Reject the operation when `len(file_ids) != len(set(file_ids))` to keep invalid state from progressing.
            if len(file_ids) != len(set(file_ids)):
                raise ValueError("attachments cannot contain duplicate file_id values")
        return self


# Defines the message response API data contract; Pydantic uses it while validating or serializing API data.
class MessageResponse(BaseModel):
    id: UUID
    channel_id: UUID
    sender_user_id: UUID
    sender_username: str | None = None
    sender_display_name: str | None = None
    sender_avatar_url: str | None = None
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
    reactions_summary: dict[str, Any] = Field(default_factory=lambda: {"counts": {}, "my_reaction": []})


# Defines the message patch request API data contract; Pydantic uses it while validating or serializing API data.
class MessagePatchRequest(BaseModel):
    content_text: str | None = None
    content_json: dict[str, Any] | None = None

    # Validates content; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_content(self) -> "MessagePatchRequest":
        has_text = self.content_text is not None
        has_json = self.content_json is not None
        # Reject the operation when `has_text == has_json` to keep invalid state from progressing.
        if has_text == has_json:
            raise ValueError("provide exactly one of content_text or content_json")
        # Reject the operation when `has_text and (not self.content_text.strip())` to keep invalid state from progressing.
        if has_text and not self.content_text.strip():
            raise ValueError("content_text cannot be empty")
        return self


# Defines the reaction request API data contract; Pydantic uses it while validating or serializing API data.
class ReactionRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=64)


# Defines the reaction summary response API data contract; Pydantic uses it while validating or serializing API data.
class ReactionSummaryResponse(BaseModel):
    counts: dict[str, int]
    my_reaction: list[str]


# Defines the pin list response API data contract; Pydantic uses it while validating or serializing API data.
class PinListResponse(BaseModel):
    items: list[MessageResponse]


# Defines the upload create request API data contract; Pydantic uses it while validating or serializing API data.
class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    checksum: str | None = Field(default=None, max_length=255)


# Defines the upload create response API data contract; Pydantic uses it while validating or serializing API data.
class UploadCreateResponse(BaseModel):
    file_id: UUID
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    public_url: str | None = None


# Defines the sync channel cursor API data contract; Pydantic uses it while validating or serializing API data.
class SyncChannelCursor(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = Field(default=None, ge=0)


# Defines the sync request API data contract; Pydantic uses it while validating or serializing API data.
class SyncRequest(BaseModel):
    channels: list[SyncChannelCursor] = Field(default_factory=list)
    since: datetime | None = None
    limit: int = Field(default=200, ge=1, le=500)


# Defines the sync membership update API data contract; Pydantic uses it while validating or serializing API data.
class SyncMembershipUpdate(BaseModel):
    channel_id: UUID
    user_id: UUID
    new_role: Literal["owner", "admin", "member", "pending", "none"]
    reason: str
    updated_at: datetime


# Defines the sync channel update API data contract; Pydantic uses it while validating or serializing API data.
class SyncChannelUpdate(BaseModel):
    channel_id: UUID
    patch: dict[str, Any]
    updated_at: datetime


# Defines the sync response API data contract; Pydantic uses it while validating or serializing API data.
class SyncResponse(BaseModel):
    server_time: datetime
    channel_updates: list[SyncChannelUpdate]
    membership_updates: list[SyncMembershipUpdate]
    messages: list[MessageResponse]


# Defines the message list response API data contract; Pydantic uses it while validating or serializing API data.
class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    next_before_seq_id: int | None
    next_after_seq_id: int | None
    has_more: bool
    order: Literal["asc", "desc"]


# Defines the seen request API data contract; Pydantic uses it while validating or serializing API data.
class SeenRequest(BaseModel):
    last_seen_message_id: UUID | None = None
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None

    # Validates required marker; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_required_marker(self) -> "SeenRequest":
        has_message = self.last_seen_message_id is not None
        has_seq = self.last_seen_seq_id is not None
        # Reject the operation when `has_message == has_seq` to keep invalid state from progressing.
        if has_message == has_seq:
            raise ValueError("provide exactly one of last_seen_message_id or last_seen_seq_id")
        return self


# Defines the seen response API data contract; Pydantic uses it while validating or serializing API data.
class SeenResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    last_seen_seq_id: int | None
    last_seen_message_id: UUID | None
    last_seen_at: datetime | None
    unread_count: int | None


# Defines the message around response API data contract; Pydantic uses it while validating or serializing API data.
class MessageAroundResponse(BaseModel):
    seq_id: int
    items: list[MessageResponse]
