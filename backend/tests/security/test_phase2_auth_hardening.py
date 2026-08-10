import json
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from time import time
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from jose import jwt
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select

from app import main as main_module
from app.services import auth_service as auth_service_module
from app.api.deps import get_current_auth
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_access_token, decode_token
from app.core.utils import sha256_hex, utcnow
from app.db.models import Event, User, UserSession
from app.realtime.auth_control import AuthControlEvent, auth_control_channel, dispatch_auth_control
from app.realtime.ws_manager import WSManager
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth_service import AccessContext, AuthService, RefreshTokenReplayError
from app.services.ws_ticket_service import WebSocketTicketService


class _MemoryRedis:
    def __init__(self) -> None:
        self.clock = 0.0
        self.records: dict[str, tuple[str, float]] = {}
        self.published: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.records and self.records[key][1] > self.clock:
            return False
        self.records[key] = (value, self.clock + ex)
        return True

    async def getdel(self, key: str) -> str | None:
        row = self.records.pop(key, None)
        if row is None or row[1] <= self.clock:
            return None
        return row[0]

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    def advance(self, seconds: float) -> None:
        self.clock += seconds


class _PublishFailRedis(_MemoryRedis):
    async def publish(self, channel: str, payload: str) -> int:
        raise RedisConnectionError("redis unavailable")


class _RecordingWebSocket:
    def __init__(self, query_params: dict[str, str] | None = None) -> None:
        self.query_params = query_params or {}
        self.headers: dict[str, str] = {}
        self.accepted = False
        self.sent: list[dict] = []
        self.closed: tuple[int, str] | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        self.closed = (code, reason)


class _RouteManager:
    def __init__(self) -> None:
        self.connected: tuple[UUID, UUID] | None = None
        self.ran = False
        self.disconnected = False

    async def connect(self, websocket, user_id: UUID, username: str, session_id: UUID) -> None:
        await websocket.accept()
        self.connected = (user_id, session_id)

    async def run_socket(self, websocket, user_id, username, session_id, authentication_expires_at) -> None:
        self.ran = True

    async def disconnect(self, websocket, username: str) -> None:
        self.disconnected = True


class _SharedDBContext(AbstractAsyncContextManager):
    def __init__(self, db) -> None:
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


async def _register_and_login(db, username: str):
    user = await AuthService.register(
        db,
        RegisterRequest(username=username, email=f"{username}@example.com", password="Password123!"),
    )
    pair = await AuthService.login(
        db,
        LoginRequest(username_or_email=username, password="Password123!"),
        user_agent="phase2-test",
        ip="127.0.0.1",
        refresh_ttl_days=14,
        absolute_ttl_days=30,
    )
    return user, pair


def _session_id(access_token: str) -> UUID:
    return UUID(decode_token(access_token)["sid"])


def _ticket_auth_context() -> AccessContext:
    now = utcnow()
    user = User(id=uuid4(), username="ticket_user", password_hash="unused", is_active=True)
    return AccessContext(
        user=user,
        session_id=uuid4(),
        token_expires_at=now + timedelta(minutes=5),
        authentication_expires_at=now + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_active_session_access_token_works(db_session):
    user, pair = await _register_and_login(db_session, "phase2_active")

    context = await AuthService.get_access_context(db_session, pair.access_token)

    assert context.user.id == user.id
    assert context.session_id == _session_id(pair.access_token)


@pytest.mark.asyncio
async def test_logout_invalidates_existing_access_token(db_session):
    _, pair = await _register_and_login(db_session, "phase2_logout")

    await AuthService.logout(db_session, pair.refresh_token)

    with pytest.raises(AppError) as error:
        await AuthService.get_access_context(db_session, pair.access_token)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_revoking_session_a_does_not_revoke_session_b(db_session):
    user, pair_a = await _register_and_login(db_session, "phase2_isolated")
    pair_b = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password="Password123!"),
        None,
        None,
        14,
        30,
    )

    await AuthService.revoke_session(db_session, user.id, _session_id(pair_a.access_token))

    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, pair_a.access_token)
    assert (await AuthService.get_access_context(db_session, pair_b.access_token)).user.id == user.id


@pytest.mark.asyncio
async def test_logout_all_invalidates_access_tokens_from_all_sessions(db_session):
    user, pair_a = await _register_and_login(db_session, "phase2_logout_all")
    pair_b = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password="Password123!"),
        None,
        None,
        14,
        30,
    )

    result = await AuthService.logout_all(db_session, user.id)

    assert result.revoked_count == 2
    for token in (pair_a.access_token, pair_b.access_token):
        with pytest.raises(AppError):
            await AuthService.get_access_context(db_session, token)


@pytest.mark.asyncio
async def test_nonexistent_and_legacy_access_session_claims_are_rejected(db_session):
    user, pair = await _register_and_login(db_session, "phase2_claims")
    forged = create_access_token(user.id, uuid4(), utcnow() + timedelta(minutes=5))
    settings = get_settings()
    now = int(time())
    legacy = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": now, "exp": now + 300},
        settings.jwt_secret,
        algorithm="HS256",
    )
    malformed = jwt.encode(
        {"sub": str(user.id), "sid": "not-a-uuid", "type": "access", "iat": now, "exp": now + 300},
        settings.jwt_secret,
        algorithm="HS256",
    )

    for token in (forged, legacy, malformed):
        with pytest.raises(AppError) as error:
            await AuthService.get_access_context(db_session, token)
        assert error.value.status_code == 401
    assert await AuthService.get_user_from_access_token(db_session, pair.access_token) == user


@pytest.mark.asyncio
async def test_refresh_rotation_replay_revokes_only_compromised_family(db_session):
    user, pair_a1 = await _register_and_login(db_session, "phase2_replay")
    pair_b1 = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password="Password123!"),
        None,
        None,
        14,
        30,
    )
    pair_a2 = await AuthService.refresh(db_session, pair_a1.refresh_token, None, None, 14)
    assert pair_a2.refresh_token != pair_a1.refresh_token

    with pytest.raises(RefreshTokenReplayError):
        await AuthService.refresh(db_session, pair_a1.refresh_token, None, None, 14)

    compromised = await db_session.get(UserSession, _session_id(pair_a2.access_token))
    assert compromised is not None
    assert compromised.revoked_at is not None
    assert compromised.replay_detected_at is not None
    replay_event = (
        await db_session.execute(select(Event).where(Event.event_type == "security.refresh_replay_detected"))
    ).scalar_one()
    assert replay_event.payload["session_id"] == str(compromised.id)
    with pytest.raises(AppError):
        await AuthService.refresh(db_session, pair_a2.refresh_token, None, None, 14)
    assert (await AuthService.refresh(db_session, pair_b1.refresh_token, None, None, 14)).access_token


@pytest.mark.asyncio
async def test_current_legacy_refresh_without_jti_rotates_into_hardened_format(db_session):
    user = await AuthService.register(
        db_session,
        RegisterRequest(username="phase2_legacy_refresh", email=None, password="Password123!"),
    )
    now = utcnow()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash="pending",
        expires_at=now + timedelta(days=14),
        absolute_expires_at=now + timedelta(days=30),
    )
    db_session.add(session)
    await db_session.flush()
    legacy_refresh = jwt.encode(
        {
            "sub": str(user.id),
            "sid": str(session.id),
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(session.expires_at.timestamp()),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    session.refresh_token_hash = sha256_hex(legacy_refresh)
    await db_session.commit()

    rotated = await AuthService.refresh(db_session, legacy_refresh, None, None, 14)

    assert decode_token(rotated.refresh_token).get("jti")


@pytest.mark.asyncio
async def test_refresh_replay_revocation_survives_audit_failure(db_session, monkeypatch):
    _, pair_1 = await _register_and_login(db_session, "phase2_replay_audit")
    pair_2 = await AuthService.refresh(db_session, pair_1.refresh_token, None, None, 14)

    async def _audit_failure(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(auth_service_module, "log_event", _audit_failure)
    with pytest.raises(RefreshTokenReplayError):
        await AuthService.refresh(db_session, pair_1.refresh_token, None, None, 14)

    session = await db_session.get(UserSession, _session_id(pair_2.access_token))
    assert session is not None and session.revoked_at is not None
    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, pair_2.access_token)


@pytest.mark.asyncio
async def test_refresh_extends_idle_lifetime_but_not_absolute_lifetime(db_session):
    _, pair = await _register_and_login(db_session, "phase2_lifetime")
    session = await db_session.get(UserSession, _session_id(pair.access_token))
    assert session is not None
    previous_idle_expiry = utcnow() + timedelta(minutes=1)
    absolute_expiry = utcnow() + timedelta(hours=1)
    session.expires_at = previous_idle_expiry
    session.absolute_expires_at = absolute_expiry
    await db_session.commit()

    await AuthService.refresh(db_session, pair.refresh_token, None, None, 14)
    await db_session.refresh(session)

    assert session.expires_at > previous_idle_expiry
    assert session.expires_at == absolute_expiry


@pytest.mark.asyncio
async def test_absolute_expired_session_cannot_refresh_or_authenticate_access(db_session):
    _, pair = await _register_and_login(db_session, "phase2_absolute")
    session = await db_session.get(UserSession, _session_id(pair.access_token))
    assert session is not None
    session.absolute_expires_at = utcnow() - timedelta(seconds=1)
    session.expires_at = utcnow() + timedelta(days=1)
    await db_session.commit()

    with pytest.raises(AppError):
        await AuthService.refresh(db_session, pair.refresh_token, None, None, 14)
    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, pair.access_token)


@pytest.mark.asyncio
async def test_authenticated_ticket_is_opaque_bound_and_single_use():
    redis = _MemoryRedis()
    auth = _ticket_auth_context()

    issued = await WebSocketTicketService.issue(redis, auth)
    stored_key = next(iter(redis.records))
    claims = await WebSocketTicketService.consume(redis, issued.value)

    assert issued.value not in stored_key
    assert claims.user_id == auth.user.id
    assert claims.session_id == auth.session_id
    with pytest.raises(AppError):
        await WebSocketTicketService.consume(redis, issued.value)


@pytest.mark.asyncio
async def test_websocket_ticket_expires_before_use():
    redis = _MemoryRedis()
    issued = await WebSocketTicketService.issue(redis, _ticket_auth_context())
    redis.advance(get_settings().ws_ticket_ttl_seconds + 1)

    with pytest.raises(AppError) as error:
        await WebSocketTicketService.consume(redis, issued.value)
    assert error.value.code == "WS_TICKET_INVALID"


@pytest.mark.asyncio
async def test_anonymous_and_expired_access_cannot_create_websocket_ticket(db_session):
    user, pair = await _register_and_login(db_session, "phase2_ticket_denied")
    with pytest.raises(HTTPException) as anonymous:
        await get_current_auth(db_session, None)
    assert anonymous.value.status_code == 401

    sid = _session_id(pair.access_token)
    settings = get_settings()
    now = int(time())
    expired = jwt.encode(
        {"sub": str(user.id), "sid": str(sid), "type": "access", "iat": now - 60, "exp": now - 1},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as expired_error:
        await get_current_auth(db_session, f"Bearer {expired}")
    assert expired_error.value.status_code == 401


@pytest.mark.asyncio
async def test_ticket_cannot_be_rebound_to_another_session(db_session):
    user_a, pair_a = await _register_and_login(db_session, "phase2_ticket_a")
    _, pair_b = await _register_and_login(db_session, "phase2_ticket_b")
    auth_a = await AuthService.get_access_context(db_session, pair_a.access_token)
    redis = _MemoryRedis()
    issued = await WebSocketTicketService.issue(redis, auth_a)
    key = WebSocketTicketService._key(issued.value)
    raw, deadline = redis.records[key]
    payload = json.loads(raw)
    payload["session_id"] = str(_session_id(pair_b.access_token))
    redis.records[key] = (json.dumps(payload), deadline)

    claims = await WebSocketTicketService.consume(redis, issued.value)
    with pytest.raises(AppError):
        await AuthService.get_session_access_context(
            db_session,
            user_a.id,
            claims.session_id,
            claims.authentication_expires_at,
        )


@pytest.mark.asyncio
async def test_valid_ticket_connects_correct_user_and_revoked_session_cannot_reconnect(db_session, monkeypatch):
    user, pair = await _register_and_login(db_session, "phase2_ws_connect")
    auth = await AuthService.get_access_context(db_session, pair.access_token)
    redis = _MemoryRedis()
    manager = _RouteManager()
    monkeypatch.setattr(main_module, "SessionLocal", lambda: _SharedDBContext(db_session))
    monkeypatch.setattr(main_module.app.state, "redis", redis, raising=False)
    monkeypatch.setattr(main_module.app.state, "ws_manager", manager, raising=False)

    first_ticket = await WebSocketTicketService.issue(redis, auth)
    valid_socket = _RecordingWebSocket({"ticket": first_ticket.value})
    await main_module._run_websocket(valid_socket)
    assert manager.connected == (user.id, auth.session_id)
    assert manager.ran is True
    assert manager.disconnected is True

    second_ticket = await WebSocketTicketService.issue(redis, auth)
    await AuthService.revoke_session(db_session, user.id, auth.session_id)
    denied_manager = _RouteManager()
    monkeypatch.setattr(main_module.app.state, "ws_manager", denied_manager, raising=False)
    revoked_socket = _RecordingWebSocket({"ticket": second_ticket.value})
    await main_module._run_websocket(revoked_socket)
    assert denied_manager.connected is None
    assert revoked_socket.closed is not None and revoked_socket.closed[0] == 1008


@pytest.mark.asyncio
async def test_raw_access_jwt_query_parameter_is_rejected():
    socket = _RecordingWebSocket({"token": "raw-access-jwt"})

    await main_module._run_websocket(socket)

    assert socket.accepted is True
    assert socket.closed is not None and socket.closed[0] == 1008
    assert socket.sent[0]["payload"]["code"] == "WS_TICKET_INVALID"


@pytest.mark.asyncio
async def test_socket_closes_when_authentication_lifetime_expires():
    manager = WSManager.__new__(WSManager)
    socket = _RecordingWebSocket()

    await manager._close_when_auth_expires(socket, utcnow() - timedelta(milliseconds=1))

    assert socket.closed == (4001, "authentication expired")


@pytest.mark.asyncio
async def test_local_and_redis_revocation_close_open_session_idempotently_without_tokens():
    user_id = uuid4()
    session_id = uuid4()
    socket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._connections = {user_id: {id(socket): socket}}
    manager._session_connections = {session_id: {id(socket): socket}}
    manager._closing_sockets = set()
    redis = _MemoryRedis()
    event = AuthControlEvent(user_id=user_id, session_id=session_id, reason="logout")

    published = await dispatch_auth_control(redis, manager, event)
    duplicate_closed = await manager.handle_auth_control_event(AuthControlEvent.from_json(event.to_json()))

    assert published is True
    assert socket.closed == (4003, "logout")
    assert duplicate_closed == 0
    assert redis.published[0][0] == auth_control_channel()
    assert "token" not in redis.published[0][1].lower()


@pytest.mark.asyncio
async def test_redis_outage_does_not_undo_durable_logout(db_session):
    user, pair = await _register_and_login(db_session, "phase2_redis_outage")
    session_id = _session_id(pair.access_token)
    revocation = await AuthService.logout(db_session, pair.refresh_token)
    socket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._connections = {user.id: {id(socket): socket}}
    manager._session_connections = {session_id: {id(socket): socket}}
    manager._closing_sockets = set()

    published = await dispatch_auth_control(
        _PublishFailRedis(),
        manager,
        AuthControlEvent.for_session(revocation),
    )

    assert published is False
    assert socket.closed == (4003, "logout")
    with pytest.raises(AppError):
        await AuthService.get_access_context(db_session, pair.access_token)
