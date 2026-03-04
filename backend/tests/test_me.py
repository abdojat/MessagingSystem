import pytest

from app.api.routes.users import me
from app.schemas.auth import RegisterRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_me_returns_current_user(db_session):
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="u_me", email="u_me@example.com", password="password123"),
    )
    response = await me(user)
    assert response.id == user.id
    assert response.username == "u_me"
    assert response.email == "u_me@example.com"
