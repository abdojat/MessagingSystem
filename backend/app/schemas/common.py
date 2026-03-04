from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.messages import MessageResponse


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class WsHello(BaseModel):
    type: Literal["hello"]
    user_id: UUID
    server_time: datetime


class WsHistory(BaseModel):
    type: Literal["history"]
    channel_id: UUID
    items: list[MessageResponse]
    is_truncated: bool


class WsMessage(BaseModel):
    type: Literal["message"]
    channel_id: UUID
    message: MessageResponse


class WsMembershipUpdate(BaseModel):
    type: Literal["membership_update"]
    channel_id: UUID
    user_id: UUID
    new_role: Literal["owner", "admin", "member", "pending", "none"]
    reason: str


class WsChannelPatch(BaseModel):
    name: str | None = None
    visibility: Literal["public", "private"] | None = None
    join_mode: Literal["open", "invite_only", "approval_required"] | None = None


class WsChannelUpdated(BaseModel):
    type: Literal["channel_updated"]
    channel_id: UUID
    patch: WsChannelPatch


class WsSyncState(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None


class WsSync(BaseModel):
    type: Literal["sync"]
    states: list[WsSyncState]


class WsSeen(BaseModel):
    type: Literal["seen"]
    channel_id: UUID
    last_seen_seq_id: int
    last_seen_at: datetime | None = None
