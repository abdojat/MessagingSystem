from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.identifiers import validate_username as validate_username_value


# Defines the register request API data contract; Pydantic uses it while validating or serializing API data.
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=256)

    # Validates username no spaces; Pydantic uses it while validating or serializing API data.
    @field_validator("username")
    @classmethod
    def validate_username_no_spaces(cls, value: str) -> str:
        return validate_username_value(value)


# Defines the login request API data contract; Pydantic uses it while validating or serializing API data.
class LoginRequest(BaseModel):
    username_or_email: str
    password: str


# Defines the refresh request API data contract; Pydantic uses it while validating or serializing API data.
class RefreshRequest(BaseModel):
    refresh_token: str


# Defines the logout request API data contract; Pydantic uses it while validating or serializing API data.
class LogoutRequest(BaseModel):
    refresh_token: str


# Defines the token pair API data contract; Pydantic uses it while validating or serializing API data.
class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# Defines the me response API data contract; Pydantic uses it while validating or serializing API data.
class MeResponse(BaseModel):
    id: UUID
    username: str
    email: EmailStr | None
    display_name: str | None = None
    avatar_url: str | None = None
    wallpaper_url: str | None = None
    bio: str | None = None
    is_superadmin: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None


# Defines the session response API data contract; Pydantic uses it while validating or serializing API data.
class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    user_agent: str | None
    ip: str | None


# Defines the session list response API data contract; Pydantic uses it while validating or serializing API data.
class SessionListResponse(BaseModel):
    items: list[SessionResponse]


# Defines the logout all response API data contract; Pydantic uses it while validating or serializing API data.
class LogoutAllResponse(BaseModel):
    status: str = "ok"
    revoked_count: int
