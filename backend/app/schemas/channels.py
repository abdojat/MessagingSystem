from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import ChannelJoinMode, ChannelVisibility, MembershipRole


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode


class ChannelResponse(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode
    created_at: datetime


class MembershipActionResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole


class JoinRequest(BaseModel):
    invite_token: str | None = None


class InviteRequest(BaseModel):
    invited_user_id: UUID | None = None
    invited_email: str | None = None
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class InviteResponse(BaseModel):
    token: str
    channel_id: UUID
    expires_at: datetime
