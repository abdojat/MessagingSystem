from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.identifiers import normalize_avatar_url, validate_channel_slug as validate_channel_slug_value
from app.db.models import ChannelJoinMode, ChannelVisibility, MembershipRole
from app.schemas.messages import MessageResponse


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel_slug: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode

    @field_validator("channel_slug")
    @classmethod
    def validate_channel_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_channel_slug_value(value)

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)


class ChannelPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    channel_slug: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    visibility: ChannelVisibility | None = None
    join_mode: ChannelJoinMode | None = None

    @field_validator("channel_slug")
    @classmethod
    def validate_channel_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_channel_slug_value(value)

    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)

    @model_validator(mode="after")
    def validate_non_empty(self) -> "ChannelPatchRequest":
        # Empty PATCH requests would create audit noise without changing channel state.
        if len(self.model_fields_set) == 0:
            raise ValueError("provide at least one field to update")
        return self


class ChannelPermissions(BaseModel):
    can_publish: bool
    can_invite: bool
    can_approve: bool
    can_manage_members: bool
    can_edit_channel: bool
    can_delete_channel: bool


class AdminPermissions(BaseModel):
    can_publish: bool
    can_invite: bool
    can_approve: bool
    can_manage_members: bool
    can_edit_channel: bool


class ChannelBasePayload(BaseModel):
    id: UUID
    owner_user_id: UUID
    name: str
    channel_slug: str
    description: str | None = None
    avatar_url: str | None = None
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    member_count: int = 0
    pending_count: int = 0
    last_message: MessageResponse | None = None
    last_message_at: datetime | None = None
    my_last_seen_seq_id: int | None = None
    unread_count: int = 0
    my_role: MembershipRole | str
    permissions: ChannelPermissions


class ChannelListItem(ChannelBasePayload):
    pass


class ChannelResponse(ChannelBasePayload):
    pass


class ChannelListResponse(BaseModel):
    items: list[ChannelListItem]
    next_cursor: str | None
    has_more: bool


class ChannelStatsResponse(BaseModel):
    channel_id: UUID
    member_count: int
    pending_count: int
    message_count: int
    last_message_at: datetime | None


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
        # An invite is either reusable/generic or targeted at one user/email;
        # mixing those modes would make later acceptance checks ambiguous.
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
    token_masked: str | None = Field(default=None, deprecated=True)
    created_by_user_id: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InviteListResponse(BaseModel):
    items: list[InviteListItem]
    next_cursor: str | None = None
    has_more: bool = False


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
    display_name: str | None = None
    avatar_url: str | None = None
    email: EmailStr | None
    role: MembershipRole
    created_at: datetime
    approved_at: datetime | None
    updated_at: datetime | None = None
    invited_by_user_id: UUID | None = None
    admin_permissions: AdminPermissions | None = None


class AdminPermissionsUpdateRequest(BaseModel):
    can_publish: bool | None = None
    can_invite: bool | None = None
    can_approve: bool | None = None
    can_manage_members: bool | None = None
    can_edit_channel: bool | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> "AdminPermissionsUpdateRequest":
        # Permission updates should represent an intentional role change.
        if len(self.model_fields_set) == 0:
            raise ValueError("provide at least one permission field")
        return self


class AdminPermissionsUpdateResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole
    admin_permissions: AdminPermissions


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
