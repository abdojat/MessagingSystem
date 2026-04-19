from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserPublicProfile(BaseModel):
    id: UUID
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    created_at: datetime
    updated_at: datetime


class UserSearchItem(BaseModel):
    id: UUID
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class UserSearchResponse(BaseModel):
    items: list[UserSearchItem]
    next_cursor: str | None
    has_more: bool


class UserSearchQuery(BaseModel):
    q: str = Field(min_length=1, max_length=255)


class UpdateMeRequest(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=128)
    avatar_url: str | None = Field(default=None, max_length=2048)
    bio: str | None = Field(default=None, max_length=2000)

    @field_validator("display_name", "avatar_url", "bio")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
