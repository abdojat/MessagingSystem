from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def validate_username_no_spaces(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("username is required")
        if any(ch.isspace() for ch in normalized):
            raise ValueError("username must not contain spaces")
        return normalized


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: UUID
    username: str
    email: EmailStr | None
    display_name: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    user_agent: str | None
    ip: str | None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]


class LogoutAllResponse(BaseModel):
    status: str = "ok"
    revoked_count: int
