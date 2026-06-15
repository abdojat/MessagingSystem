from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.identifiers import normalize_avatar_url


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

    @field_validator("display_name", "bio")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("avatar_url")
    @classmethod
    def normalize_optional_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
