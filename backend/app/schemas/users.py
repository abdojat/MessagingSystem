from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
    query: str = Field(min_length=1, max_length=255)
