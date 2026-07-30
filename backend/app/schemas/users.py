from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.identifiers import normalize_avatar_url, normalize_wallpaper_url


# Defines the user public profile API data contract; Pydantic uses it while validating or serializing API data.
class UserPublicProfile(BaseModel):
    id: UUID
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    created_at: datetime
    updated_at: datetime


# Defines the user search item API data contract; Pydantic uses it while validating or serializing API data.
class UserSearchItem(BaseModel):
    id: UUID
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


# Defines the user search response API data contract; Pydantic uses it while validating or serializing API data.
class UserSearchResponse(BaseModel):
    items: list[UserSearchItem]
    next_cursor: str | None
    has_more: bool


# Defines the user search query API data contract; Pydantic uses it while validating or serializing API data.
class UserSearchQuery(BaseModel):
    q: str = Field(min_length=1, max_length=255)


# Defines the update me request API data contract; Pydantic uses it while validating or serializing API data.
class UpdateMeRequest(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=128)
    avatar_url: str | None = Field(default=None, max_length=2048)
    wallpaper_url: str | None = Field(default=None, max_length=2048)
    bio: str | None = Field(default=None, max_length=2000)

    # Normalizes optional text; Pydantic uses it while validating or serializing API data.
    @field_validator("display_name", "bio")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        # Return early when `value is None` because the remaining work is not applicable.
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    # Normalizes optional avatar url; Pydantic uses it while validating or serializing API data.
    @field_validator("avatar_url")
    @classmethod
    def normalize_optional_avatar_url(cls, value: str | None) -> str | None:
        return normalize_avatar_url(value)

    # Normalizes optional wallpaper url; Pydantic uses it while validating or serializing API data.
    @field_validator("wallpaper_url")
    @classmethod
    def normalize_optional_wallpaper_url(cls, value: str | None) -> str | None:
        return normalize_wallpaper_url(value)

    # Normalizes optional email; Pydantic uses it while validating or serializing API data.
    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: str | None) -> str | None:
        # Return early when `value is None` because the remaining work is not applicable.
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
