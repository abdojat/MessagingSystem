import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.db.models import Event, User, UserSession
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest
from app.services.auth_service import AuthService


@pytest.mark.parametrize(
    "password",
    [
        "Aa1!short",
        "lowercase123!",
        "UPPERCASE123!",
        "NoNumbersHere!",
        "Password1234",
        "Password 123!",
        "Aa1!" + "x" * 253,
    ],
)
def test_new_password_policy_rejects_each_missing_requirement(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username="policy_user", email=None, password=password)
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="anything", new_password=password)


def test_new_password_policy_accepts_all_required_character_classes() -> None:
    password = "StrongPassword123!"

    assert RegisterRequest(username="policy_user", email=None, password=password).password == password
    assert ChangePasswordRequest(current_password="old", new_password=password).new_password == password


@pytest.mark.asyncio
async def test_password_change_rehashes_password_revokes_sessions_and_logs_event(db_session) -> None:
    old_password = "OldPassword123!"
    new_password = "NewPassword456!"
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="password_change", email=None, password=old_password),
    )
    first = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password=old_password),
        user_agent="first",
        ip="127.0.0.1",
        refresh_ttl_days=14,
    )
    second = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password=old_password),
        user_agent="second",
        ip="127.0.0.2",
        refresh_ttl_days=14,
    )

    result = await AuthService.change_password(
        db_session,
        user.id,
        ChangePasswordRequest(current_password=old_password, new_password=new_password),
    )

    await db_session.refresh(user)
    assert result.revoked_count == 2
    assert verify_password(new_password, user.password_hash)
    assert not verify_password(old_password, user.password_hash)
    sessions = (
        await db_session.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalars().all()
    assert len(sessions) == 2
    assert all(session.revoked_at is not None for session in sessions)
    event = (
        await db_session.execute(select(Event).where(Event.event_type == "user.password_changed"))
    ).scalar_one()
    assert event.actor_user_id == user.id
    assert event.payload == {"revoked_sessions": 2}
    for access_token in (first.access_token, second.access_token):
        with pytest.raises(AppError):
            await AuthService.get_access_context(db_session, access_token)

    with pytest.raises(AppError):
        await AuthService.login(
            db_session,
            LoginRequest(username_or_email=user.username, password=old_password),
            user_agent=None,
            ip=None,
            refresh_ttl_days=14,
        )
    assert (
        await AuthService.login(
            db_session,
            LoginRequest(username_or_email=user.username, password=new_password),
            user_agent=None,
            ip=None,
            refresh_ttl_days=14,
        )
    ).access_token


@pytest.mark.asyncio
async def test_incorrect_current_password_does_not_change_password_or_revoke_sessions(db_session) -> None:
    password = "OriginalPassword123!"
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="password_unchanged", email=None, password=password),
    )
    pair = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password=password),
        user_agent=None,
        ip=None,
        refresh_ttl_days=14,
    )
    original_hash = user.password_hash

    with pytest.raises(AppError) as error:
        await AuthService.change_password(
            db_session,
            user.id,
            ChangePasswordRequest(current_password="WrongPassword123!", new_password="AnotherPassword456!"),
        )

    assert error.value.code == "CURRENT_PASSWORD_INVALID"
    await db_session.refresh(user)
    assert user.password_hash == original_hash
    assert (await AuthService.get_access_context(db_session, pair.access_token)).user.id == user.id


@pytest.mark.asyncio
async def test_login_remains_compatible_with_legacy_weak_password(db_session) -> None:
    legacy_password = "legacy-password"
    user = User(username="legacy_password", password_hash=hash_password(legacy_password))
    db_session.add(user)
    await db_session.commit()

    pair = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password=legacy_password),
        user_agent=None,
        ip=None,
        refresh_ttl_days=14,
    )

    assert pair.access_token
