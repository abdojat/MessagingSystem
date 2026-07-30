from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.identifiers import normalize_avatar_url, validate_channel_slug as validate_channel_slug_value
from app.db.models import ChannelJoinMode, ChannelVisibility, MembershipRole
from app.schemas.messages import MessageResponse


# Defines the channel create request API data contract; Pydantic uses it while validating or serializing API data.
class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    channel_slug: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    visibility: ChannelVisibility
    join_mode: ChannelJoinMode

    # Validates channel slug; Pydantic uses it while validating or serializing API data.
    @field_validator("channel_slug")
    @classmethod
    def validate_channel_slug(cls, value: str | None) -> str | None:
        # Return early when `value is None` because the remaining work is not applicable.
        if value is None:
            return None
        return validate_channel_slug_value(value)

    # Validates avatar url; Pydantic uses it while validating or serializing API data.
    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)


# Defines the channel patch request API data contract; Pydantic uses it while validating or serializing API data.
class ChannelPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    channel_slug: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=2048)
    visibility: ChannelVisibility | None = None
    join_mode: ChannelJoinMode | None = None

    # Validates channel slug; Pydantic uses it while validating or serializing API data.
    @field_validator("channel_slug")
    @classmethod
    def validate_channel_slug(cls, value: str | None) -> str | None:
        # Return early when `value is None` because the remaining work is not applicable.
        if value is None:
            return None
        return validate_channel_slug_value(value)

    # Validates avatar url; Pydantic uses it while validating or serializing API data.
    @field_validator("avatar_url")
    @classmethod
    def validate_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)

    # Validates non empty; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_non_empty(self) -> "ChannelPatchRequest":
        # Reject the operation when `len(self.model_fields_set) == 0` to keep invalid state from progressing.
        if len(self.model_fields_set) == 0:
            raise ValueError("provide at least one field to update")
        return self


# Defines the channel permissions API data contract; Pydantic uses it while validating or serializing API data.
class ChannelPermissions(BaseModel):
    can_publish: bool
    can_invite: bool
    can_approve: bool
    can_manage_members: bool
    can_edit_channel: bool
    can_delete_channel: bool


# Defines the admin permissions API data contract; Pydantic uses it while validating or serializing API data.
class AdminPermissions(BaseModel):
    can_publish: bool
    can_invite: bool
    can_approve: bool
    can_manage_members: bool
    can_edit_channel: bool


# Defines the channel base payload API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the channel list item API data contract; Pydantic uses it while validating or serializing API data.
class ChannelListItem(ChannelBasePayload):
    pass


# Defines the channel response API data contract; Pydantic uses it while validating or serializing API data.
class ChannelResponse(ChannelBasePayload):
    pass


# Defines the channel list response API data contract; Pydantic uses it while validating or serializing API data.
class ChannelListResponse(BaseModel):
    items: list[ChannelListItem]
    next_cursor: str | None
    has_more: bool


# Defines the channel stats response API data contract; Pydantic uses it while validating or serializing API data.
class ChannelStatsResponse(BaseModel):
    channel_id: UUID
    member_count: int
    pending_count: int
    message_count: int
    last_message_at: datetime | None


# Defines the membership action response API data contract; Pydantic uses it while validating or serializing API data.
class MembershipActionResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole


# Defines the join request API data contract; Pydantic uses it while validating or serializing API data.
class JoinRequest(BaseModel):
    invite_token: str | None = None


# Defines the join outcome response API data contract; Pydantic uses it while validating or serializing API data.
class JoinOutcomeResponse(BaseModel):
    status: Literal["joined", "pending", "requires_invite", "already_member"]
    role: MembershipRole | Literal["none"]
    message: str
    channel: ChannelResponse | None = None


# Defines the invite request API data contract; Pydantic uses it while validating or serializing API data.
class InviteRequest(BaseModel):
    invited_user_id: UUID | None = None
    invited_email: EmailStr | None = None
    is_generic: bool = False
    expires_in_hours: int = Field(default=72, ge=1, le=720)

    # Validates target mode; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_target_mode(self) -> "InviteRequest":
        has_user = self.invited_user_id is not None
        has_email = self.invited_email is not None
        # Run this conditional step only when `self.is_generic` is true.
        if self.is_generic:
            # Reject the operation when `has_user or has_email` to keep invalid state from progressing.
            if has_user or has_email:
                raise ValueError("generic invites cannot include invited_user_id or invited_email")
            return self
        # Reject the operation when `has_user == has_email` to keep invalid state from progressing.
        if has_user == has_email:
            raise ValueError("provide exactly one of invited_user_id or invited_email")
        return self


# Defines the invite response API data contract; Pydantic uses it while validating or serializing API data.
class InviteResponse(BaseModel):
    id: UUID
    token: str
    channel_id: UUID
    expires_at: datetime


# Defines the invite list item API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the invite list response API data contract; Pydantic uses it while validating or serializing API data.
class InviteListResponse(BaseModel):
    items: list[InviteListItem]
    next_cursor: str | None = None
    has_more: bool = False


# Defines the invite preview channel API data contract; Pydantic uses it while validating or serializing API data.
class InvitePreviewChannel(BaseModel):
    id: UUID
    name: str
    visibility: ChannelVisibility


# Defines the invite preview response API data contract; Pydantic uses it while validating or serializing API data.
class InvitePreviewResponse(BaseModel):
    is_valid: bool
    reason: str | None = None
    channel: InvitePreviewChannel | None = None
    expires_at: datetime | None = None
    invited_email: EmailStr | None = None
    invited_user_id: UUID | None = None


# Defines the channel membership item API data contract; Pydantic uses it while validating or serializing API data.
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


# Defines the admin permissions update request API data contract; Pydantic uses it while validating or serializing API data.
class AdminPermissionsUpdateRequest(BaseModel):
    can_publish: bool | None = None
    can_invite: bool | None = None
    can_approve: bool | None = None
    can_manage_members: bool | None = None
    can_edit_channel: bool | None = None

    # Validates non empty; Pydantic uses it while validating or serializing API data.
    @model_validator(mode="after")
    def validate_non_empty(self) -> "AdminPermissionsUpdateRequest":
        # Reject the operation when `len(self.model_fields_set) == 0` to keep invalid state from progressing.
        if len(self.model_fields_set) == 0:
            raise ValueError("provide at least one permission field")
        return self


# Defines the admin permissions update response API data contract; Pydantic uses it while validating or serializing API data.
class AdminPermissionsUpdateResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole
    admin_permissions: AdminPermissions


# Defines the channel membership list response API data contract; Pydantic uses it while validating or serializing API data.
class ChannelMembershipListResponse(BaseModel):
    items: list[ChannelMembershipItem]
    next_cursor: str | None
    has_more: bool


# Defines the my membership response API data contract; Pydantic uses it while validating or serializing API data.
class MyMembershipResponse(BaseModel):
    channel_id: UUID
    user_id: UUID
    role: MembershipRole | str
    created_at: datetime | None = None
    approved_at: datetime | None = None
