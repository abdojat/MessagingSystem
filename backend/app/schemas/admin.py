from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminOverviewResponse(BaseModel):
    total_users: int
    active_users: int
    total_channels: int
    active_channels: int
    total_messages: int
    total_events: int
    delivery_failures: int


class AdminUserItem(BaseModel):
    id: UUID
    username: str
    email: str | None
    display_name: str | None
    is_superadmin: bool
    is_active: bool
    active_session_count: int
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None
    deactivated_by_user_id: UUID | None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminChannelItem(BaseModel):
    id: UUID
    name: str
    channel_slug: str
    owner_user_id: UUID
    owner_username: str
    visibility: str
    join_mode: str
    member_count: int
    message_count: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class AdminChannelListResponse(BaseModel):
    items: list[AdminChannelItem]
    total: int


class AdminEventItem(BaseModel):
    id: UUID
    channel_id: UUID | None
    channel_name: str | None
    channel_slug: str | None
    actor_user_id: UUID | None
    actor_username: str | None
    event_type: str
    details: dict[str, str | int | bool | None]
    created_at: datetime
    event_hash: str | None
    integrity_scope: str | None


class AdminEventListResponse(BaseModel):
    items: list[AdminEventItem]
    total: int


class AdminActionResponse(BaseModel):
    status: str = "ok"
    affected_sessions: int = 0
