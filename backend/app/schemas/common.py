from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.messages import MessageResponse


# Defines the error response API data contract; Pydantic uses it while validating or serializing API data.
class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


# Defines the ws hello API data contract; Pydantic uses it while validating or serializing API data.
class WsHello(BaseModel):
    type: Literal["hello"]
    user_id: UUID
    server_time: datetime


# Defines the ws history API data contract; Pydantic uses it while validating or serializing API data.
class WsHistory(BaseModel):
    type: Literal["history"]
    channel_id: UUID
    items: list[MessageResponse]
    is_truncated: bool


# Defines the ws message API data contract; Pydantic uses it while validating or serializing API data.
class WsMessage(BaseModel):
    type: Literal["message"]
    channel_id: UUID
    message: MessageResponse


# Defines the ws membership update API data contract; Pydantic uses it while validating or serializing API data.
class WsMembershipUpdate(BaseModel):
    type: Literal["membership_update"]
    channel_id: UUID
    user_id: UUID
    new_role: Literal["owner", "admin", "member", "pending", "none"]
    reason: str


# Defines the ws channel patch API data contract; Pydantic uses it while validating or serializing API data.
class WsChannelPatch(BaseModel):
    name: str | None = None
    visibility: Literal["public", "private"] | None = None
    join_mode: Literal["open", "invite_only", "approval_required"] | None = None


# Defines the ws channel updated API data contract; Pydantic uses it while validating or serializing API data.
class WsChannelUpdated(BaseModel):
    type: Literal["channel_updated"]
    channel_id: UUID
    patch: WsChannelPatch


# Defines the ws sync state API data contract; Pydantic uses it while validating or serializing API data.
class WsSyncState(BaseModel):
    channel_id: UUID
    last_seen_seq_id: int | None = None
    last_seen_at: datetime | None = None


# Defines the ws sync API data contract; Pydantic uses it while validating or serializing API data.
class WsSync(BaseModel):
    type: Literal["sync"]
    states: list[WsSyncState]


# Defines the ws seen API data contract; Pydantic uses it while validating or serializing API data.
class WsSeen(BaseModel):
    type: Literal["seen"]
    channel_id: UUID
    last_seen_seq_id: int
    last_seen_at: datetime | None = None
