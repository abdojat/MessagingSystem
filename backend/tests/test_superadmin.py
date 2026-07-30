from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select

from app.api.deps import get_current_superadmin
from app.api.routes.admin import _prevent_sensitive_caching
from app.core.errors import AppError
from app.core.security import create_access_token
from app.core.utils import utcnow
from app.db.models import ContentType, Event, Message, Upload, UserSession
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.channels import ChannelCreateRequest
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.event_service import log_event
from app.services.superadmin_bootstrap_service import SuperadminBootstrapService
from app.realtime.ws_manager import WSManager


# Stores fake amqp channel state for the verification flow; pytest runs it as a regression check.
class _FakeAmqpChannel:
    # Closes; pytest runs it as a regression check.
    async def close(self) -> None:
        return None


# Stores fake amqp connection state for the verification flow; pytest runs it as a regression check.
class _FakeAmqpConnection:
    # Creates a mocked broker channel; pytest runs it as a regression check.
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


# Stores fake web socket state for the verification flow; pytest runs it as a regression check.
class _FakeWebSocket:
    # Initializes a fake web socket; pytest runs it as a regression check.
    def __init__(self):
        self.closed: tuple[int, str] | None = None

    # Closes; pytest runs it as a regression check.
    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


# Verifies superadmin console responses are not cacheable; pytest runs it as a regression check.
def test_superadmin_console_responses_are_not_cacheable():
    response = Response()

    _prevent_sensitive_caching(response)

    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"


# Verifies deactivation closes current backend websockets; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_deactivation_closes_current_backend_websockets():
    user_id = uuid4()
    socket = _FakeWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._connections = {user_id: {id(socket): socket}}

    closed = await manager.disconnect_user(user_id)

    assert closed == 1
    assert socket.closed == (1008, "account deactivated")


# Verifies superadmin bootstrap is explicit and idempotent; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_superadmin_bootstrap_is_explicit_and_idempotent(db_session):
    user, created = await SuperadminBootstrapService.ensure(
        db_session,
        username="root_admin",
        email="root@example.com",
        password="a-strong-bootstrap-password",
    )
    same_user, created_again = await SuperadminBootstrapService.ensure(
        db_session,
        username="root_admin",
        email="root@example.com",
        password="a-different-password-is-not-a-rotation",
    )

    assert created is True
    assert created_again is False
    assert same_user.id == user.id
    assert user.is_superadmin is True
    assert user.is_active is True
    events = (await db_session.execute(select(Event).where(Event.event_type == "superadmin.bootstrapped"))).scalars().all()
    assert len(events) == 1


# Verifies bootstrap refuses to promote existing normal user; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_bootstrap_refuses_to_promote_existing_normal_user(db_session):
    await AuthService.register(
        db_session,
        RegisterRequest(username="existing_user", email="existing@example.com", password="password123"),
    )
    # Keep `pytest.raises(RuntimeError, match...` active while this scoped operation is performed.
    with pytest.raises(RuntimeError, match="refusing to auto-promote"):
        await SuperadminBootstrapService.ensure(
            db_session,
            username="existing_user",
            email=None,
            password="a-strong-bootstrap-password",
        )


# Verifies superadmin can deactivate user and immediately revoke access; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_superadmin_can_deactivate_user_and_immediately_revoke_access(db_session):
    admin, _ = await SuperadminBootstrapService.ensure(
        db_session,
        username="platform_admin",
        password="a-strong-bootstrap-password",
    )
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="managed_user", email="managed@example.com", password="password123"),
    )
    session = UserSession(
        user_id=user.id,
        refresh_token_hash="unused",
        expires_at=utcnow() + timedelta(days=1),
    )
    db_session.add(session)
    await db_session.commit()

    revoked = await AdminService.set_user_active(db_session, admin, user.id, False)
    await db_session.refresh(user)
    await db_session.refresh(session)

    assert revoked == 1
    assert user.is_active is False
    assert session.revoked_at is not None
    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
    with pytest.raises(AppError) as login_error:
        await AuthService.login(
            db_session,
            LoginRequest(username_or_email="managed_user", password="password123"),
            None,
            None,
            14,
        )
    assert login_error.value.code == "ACCOUNT_DISABLED"
    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
    with pytest.raises(AppError) as token_error:
        await AuthService.get_user_from_access_token(db_session, create_access_token(user.id))
    assert token_error.value.code == "ACCOUNT_DISABLED"


# Verifies normal user is denied superadmin dependency and attempt is logged; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_normal_user_is_denied_superadmin_dependency_and_attempt_is_logged(db_session):
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="ordinary_user", email=None, password="password123"),
    )
    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
    with pytest.raises(HTTPException) as error:
        await get_current_superadmin(db_session, user)
    assert error.value.status_code == 403
    event = (
        await db_session.execute(select(Event).where(Event.event_type == "security.superadmin_access_denied"))
    ).scalar_one()
    assert event.actor_user_id == user.id


# Verifies global event list includes system and cross channel events; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_global_event_list_includes_system_and_cross_channel_events(db_session, monkeypatch):
    # Provides a no-op test double; pytest runs it as a regression check.
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop)
    admin, _ = await SuperadminBootstrapService.ensure(
        db_session,
        username="audit_admin",
        password="a-strong-bootstrap-password",
    )
    owner = await AuthService.register(
        db_session,
        RegisterRequest(username="audit_owner", email=None, password="password123"),
    )
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Audit channel", visibility="private", join_mode="invite_only"),
        _FakeAmqpConnection(),
    )
    upload = Upload(
        owner_user_id=owner.id,
        filename="audit-proof.png",
        content_type="image/png",
        size_bytes=128,
        storage_path=f"{owner.id}/audit-proof.png",
        public_url=None,
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(
        Message(
            channel_id=channel.id,
            sender_user_id=owner.id,
            seq_id=1,
            content_type=ContentType.text,
            content_text="encrypted-placeholder",
            attachments=[{"file_id": str(upload.id), "filename": upload.filename}],
        )
    )
    await db_session.flush()
    await log_event(
        db_session,
        "upload.accessed",
        {"upload_id": str(upload.id), "filename": upload.filename},
        actor_user_id=owner.id,
    )
    await log_event(db_session, "system.test_event", {"proof": True}, actor_user_id=admin.id)
    await db_session.commit()

    events, total = await AdminService.list_events(
        db_session,
        q=None,
        event_type=None,
        category=None,
        channel_id=None,
        actor_user_id=None,
        offset=0,
        limit=100,
    )

    assert total >= 3
    created_event = next(event for event in events if event.event_type == "channel.created")
    assert created_event.channel_id == channel.id
    assert created_event.channel_name == channel.name
    assert created_event.channel_slug == channel.channel_slug
    assert created_event.actor_user_id == owner.id
    assert created_event.actor_username == owner.username
    upload_event = next(event for event in events if event.event_type == "upload.accessed")
    assert upload_event.channel_id == channel.id
    assert upload_event.channel_name == channel.name
    assert upload_event.channel_slug == channel.channel_slug
    assert any(event.event_type == "system.test_event" and event.channel_id is None for event in events)

    channel_events, channel_total = await AdminService.list_events(
        db_session,
        q="@audit_owner",
        event_type=None,
        category="channels",
        channel_id=None,
        actor_user_id=None,
        offset=0,
        limit=10,
    )
    assert channel_total == 1
    assert channel_events[0].event_type == "channel.created"

    escaped_events, escaped_total = await AdminService.list_events(
        db_session,
        q="%",
        event_type=None,
        category=None,
        channel_id=None,
        actor_user_id=None,
        offset=0,
        limit=10,
    )
    assert escaped_events == []
    assert escaped_total == 0

    matching_users, matching_user_total = await AdminService.list_users(
        db_session,
        q="@audit_owner",
        is_active=True,
        offset=0,
        limit=10,
    )
    assert matching_user_total == 1
    assert matching_users[0].id == owner.id

    matching_channels, matching_channel_total = await AdminService.list_channels(
        db_session,
        q=f"#{channel.channel_slug}",
        include_deleted=True,
        state="active",
        visibility="private",
        offset=0,
        limit=10,
    )
    assert matching_channel_total == 1
    assert matching_channels[0].id == channel.id


# Verifies admin event projection excludes raw and nested payload data; pytest runs it as a regression check.
def test_admin_event_projection_excludes_raw_and_nested_payload_data():
    details = AdminService._safe_event_details(
        "message.published",
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "content_text": "encrypted-but-sensitive-value",
            "content_json": {"secret": "encrypted-value"},
            "attachments": [{"storage_path": "private/path"}],
            "sender_avatar_url": "https://private.example/avatar",
            "seq_id": 42,
            "content_type": "text",
        },
    )

    assert details == {
        "attachment_count": 1,
        "content_type": "text",
        "message_id": "11111111-1111-1111-1111-111111111111",
        "seq_id": 42,
    }


# Verifies superadmin can suspend and restore channel without membership; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_superadmin_can_suspend_and_restore_channel_without_membership(db_session, monkeypatch):
    # Provides a no-op test double; pytest runs it as a regression check.
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop)
    monkeypatch.setattr("app.services.channel_service.unbind_user_channel", _noop)
    monkeypatch.setattr("app.services.admin_service.bind_user_channel", _noop)
    admin, _ = await SuperadminBootstrapService.ensure(
        db_session,
        username="channel_admin",
        password="a-strong-bootstrap-password",
    )
    owner = await AuthService.register(
        db_session,
        RegisterRequest(username="channel_owner", email=None, password="password123"),
    )
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Managed channel", visibility="public", join_mode="open"),
        _FakeAmqpConnection(),
    )

    await ChannelService.delete_channel(db_session, channel.id, admin.id, _FakeAmqpConnection())
    await db_session.refresh(channel)
    assert channel.deleted_at is not None

    await AdminService.restore_channel(db_session, _FakeAmqpConnection(), admin, channel.id)
    await db_session.refresh(channel)
    assert channel.deleted_at is None
    event_types = set((await db_session.execute(select(Event.event_type))).scalars().all())
    assert "channel.deleted" in event_types
    assert "superadmin.channel_restored" in event_types
