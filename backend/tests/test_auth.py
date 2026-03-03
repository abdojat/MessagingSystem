import pytest

from app.core.config import get_settings
from app.db.models import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_auth_login_refresh_happy_path(db_session):
    settings = get_settings()
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="user1", email="u1@example.com", password="password123"),
    )
    assert isinstance(user, User)

    tokens = await AuthService.login(
        db_session,
        LoginRequest(username_or_email="user1", password="password123"),
        user_agent="pytest",
        ip="127.0.0.1",
        refresh_ttl_days=settings.jwt_refresh_ttl_days,
    )
    assert tokens.access_token
    assert tokens.refresh_token

    rotated = await AuthService.refresh(
        db_session,
        tokens.refresh_token,
        user_agent="pytest",
        ip="127.0.0.1",
        refresh_ttl_days=settings.jwt_refresh_ttl_days,
    )
    assert rotated.refresh_token != tokens.refresh_token
    assert rotated.access_token
