import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import UserSession
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_sessions_list_and_revoke_blocks_refresh(db_session):
    settings = get_settings()
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="sess_user", email="sess_user@example.com", password="password123"),
    )
    tokens = await AuthService.login(
        db_session,
        LoginRequest(username_or_email="sess_user", password="password123"),
        user_agent="pytest-agent",
        ip="127.0.0.1",
        refresh_ttl_days=settings.jwt_refresh_ttl_days,
    )

    sessions = await AuthService.list_sessions(db_session, user.id)
    assert len(sessions) == 1
    assert sessions[0].user_agent == "pytest-agent"

    session_row = await db_session.execute(select(UserSession).where(UserSession.user_id == user.id))
    sid = session_row.scalar_one().id
    await AuthService.revoke_session(db_session, user.id, sid)

    with pytest.raises(AppError):
        await AuthService.refresh(
            db_session,
            tokens.refresh_token,
            user_agent="pytest-agent",
            ip="127.0.0.1",
            refresh_ttl_days=settings.jwt_refresh_ttl_days,
        )
