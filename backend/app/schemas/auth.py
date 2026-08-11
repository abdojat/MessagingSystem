from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.email_identity import normalize_email
from app.core.identifiers import validate_username as validate_username_value


AUTH_IDENTITY_MAX_LENGTH = 255
AUTH_PASSWORD_MAX_LENGTH = 256
# Current HS256 refresh JWTs are only a few hundred bytes. Two KiB leaves
# ample headroom for compatible claim growth without accepting arbitrary data.
AUTH_REFRESH_TOKEN_MAX_LENGTH = 2048


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def validate_username_no_spaces(cls, value: str) -> str:
        return validate_username_value(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_registration_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_email(value)
        return normalized or None


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=AUTH_IDENTITY_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=AUTH_PASSWORD_MAX_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=AUTH_REFRESH_TOKEN_MAX_LENGTH)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=AUTH_REFRESH_TOKEN_MAX_LENGTH)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class BrowserAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BrowserCsrfResponse(BaseModel):
    csrf_token: str


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class EmailVerificationRequestResponse(BaseModel):
    status: Literal["sent", "already_verified"]
    expires_at: datetime | None = None


class EmailVerificationConfirmResponse(BaseModel):
    status: Literal["verified"] = "verified"
    verified_at: datetime


class MeResponse(BaseModel):
    id: UUID
    username: str
    email: EmailStr | None
    email_verified_at: datetime | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    wallpaper_url: str | None = None
    bio: str | None = None
    is_superadmin: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None
    user_agent: str | None
    ip: str | None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]


class LogoutAllResponse(BaseModel):
    status: str = "ok"
    revoked_count: int
