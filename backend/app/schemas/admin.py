from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# Defines the admin overview response API data contract; Pydantic uses it while validating or serializing API data.
class AdminOverviewResponse(BaseModel):
    total_users: int
    active_users: int
    total_channels: int
    active_channels: int
    total_messages: int
    total_events: int
    delivery_failures: int


# Defines the admin user item API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the admin user list response API data contract; Pydantic uses it while validating or serializing API data.
class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int


# Defines the admin user status update API data contract; Pydantic uses it while validating or serializing API data.
class AdminUserStatusUpdate(BaseModel):
    is_active: bool


# Defines the admin channel item API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the admin channel list response API data contract; Pydantic uses it while validating or serializing API data.
class AdminChannelListResponse(BaseModel):
    items: list[AdminChannelItem]
    total: int


# Defines the admin event item API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the admin event list response API data contract; Pydantic uses it while validating or serializing API data.
class AdminEventListResponse(BaseModel):
    items: list[AdminEventItem]
    total: int


# Defines the admin action response API data contract; Pydantic uses it while validating or serializing API data.
class AdminActionResponse(BaseModel):
    status: str = "ok"
    affected_sessions: int = 0
