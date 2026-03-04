from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.db.models import ChannelJoinMode, ChannelVisibility, MembershipRole


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode


class ChannelPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: ChannelVisibility | None = None
    join_mode: ChannelJoinMode | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> "ChannelPatchRequest":
        if self.name is None and self.visibility is None and self.join_mode is None:
            raise ValueError("provide at least one field to update")
        return self


class ChannelPermissions(BaseModel):
    can_publish: bool
    can_invite: bool
    can_approve: bool
    can_manage_members: bool
    can_edit_channel: bool
    can_delete_channel: bool


class ChannelResponse(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode
    created_at: datetime
    my_role: MembershipRole | str
    permissions: ChannelPermissions


class MembershipActionResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole


class JoinRequest(BaseModel):
    invite_token: str | None = None


class JoinOutcomeResponse(BaseModel):
    status: Literal["joined", "pending", "requires_invite", "already_member"]
    role: MembershipRole | Literal["none"]
    message: str
    channel: ChannelResponse | None = None


class InviteRequest(BaseModel):
    invited_user_id: UUID | None = None
    invited_email: EmailStr | None = None
    is_generic: bool = False
    expires_in_hours: int = Field(default=72, ge=1, le=720)

    @model_validator(mode="after")
    def validate_target_mode(self) -> "InviteRequest":
        has_user = self.invited_user_id is not None
        has_email = self.invited_email is not None
        if self.is_generic:
            if has_user or has_email:
                raise ValueError("generic invites cannot include invited_user_id or invited_email")
            return self
        if has_user == has_email:
            raise ValueError("provide exactly one of invited_user_id or invited_email")
        return self


class InviteResponse(BaseModel):
    id: UUID
    token: str
    channel_id: UUID
    expires_at: datetime


class InviteListItem(BaseModel):
    id: UUID
    channel_id: UUID
    invited_user_id: UUID | None
    invited_email: EmailStr | None
    is_generic: bool
    masked_token: str
    token_masked: str
    created_by_user_id: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InviteListResponse(BaseModel):
    items: list[InviteListItem]


class InvitePreviewChannel(BaseModel):
    id: UUID
    name: str
    visibility: ChannelVisibility


class InvitePreviewResponse(BaseModel):
    is_valid: bool
    reason: str | None = None
    channel: InvitePreviewChannel | None = None
    expires_at: datetime | None = None
    invited_email: EmailStr | None = None
    invited_user_id: UUID | None = None


class ChannelMembershipItem(BaseModel):
    user_id: UUID
    username: str
    email: EmailStr | None
    role: MembershipRole
    created_at: datetime
    approved_at: datetime | None


class ChannelMembershipListResponse(BaseModel):
    items: list[ChannelMembershipItem]
    next_cursor: str | None
    has_more: bool


class MyMembershipResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole | str
    created_at: datetime | None = None
    approved_at: datetime | None = None
