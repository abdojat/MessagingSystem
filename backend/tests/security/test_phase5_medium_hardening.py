import asyncio
import json
import math
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.messages import get_upload_content
from app.core.config import get_settings
from app.core.encryption import encrypt_message
from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    ChannelInvite,
    ChannelMembership,
    ContentType,
    Event,
    MembershipRole,
    Message,
    MessageAttachment,
    Upload,
)
from app.realtime.ws_manager import WSManager
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, InviteRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from app.services.rate_limit_service import RateLimitService


class _NoDirectAmqp:
    async def channel(self):
        raise AssertionError("Phase 5 paths must keep broker work in the outbox")


class _RecordingWebSocket:
    def __init__(self, frames: list[str] | None = None) -> None:
        self.frames = list(frames or [])
        self.sent: list[dict[str, Any]] = []
        self.closed: tuple[int, str] | None = None

    async def receive_text(self) -> str:
        if self.frames:
            return self.frames.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


class _EmptySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _PresenceRedis:
    async def srem(self, key: str, value: str) -> int:
        return 1


class _LuaRateRedis:
    """Small deterministic harness for the fixed-window Lua contract."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.now = 0.0
        self.counts: dict[str, int] = {}
        self.expires_at: dict[str, float] = {}
        self.eval_calls = 0
        self.scripts: list[str] = []

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        self.eval_calls += 1
        self.scripts.append(script)
        if self.fail:
            raise ConnectionError("redis unavailable")
        assert numkeys == 1
        if self.expires_at.get(key, -1) <= self.now:
            self.counts.pop(key, None)
            self.expires_at.pop(key, None)
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        ttl = math.ceil(self.expires_at.get(key, -1) - self.now)
        if count == 1 or ttl < 0:
            self.expires_at[key] = self.now + int(window_seconds)
            ttl = int(window_seconds)
        return [count, ttl]


class _SignallingSession:
    """Signals immediately before an independent session attempts a row lock."""

    def __init__(self, session: AsyncSession, started: asyncio.Event) -> None:
        self._session = session
        self._started = started

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).upper()
        if "FOR UPDATE" in sql:
            self._started.set()
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _client_frame(message_type: str, payload: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "type": message_type,
            "payload": payload or {},
            "ts": utcnow().isoformat(),
        }
    )


async def _register(db: AsyncSession, username: str):
    return await AuthService.register(
        db,
        RegisterRequest(
            username=username,
            email=f"{username}@example.com",
            password="Password123!",
        ),
    )


async def _channel(db: AsyncSession, owner, name: str, *, join_mode: str = "open"):
    return await ChannelService.create_channel(
        db,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode=join_mode),
        _NoDirectAmqp(),
    )


def _session_maker(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _prelock_invite(db: AsyncSession, channel_id: UUID, invite_id: UUID) -> None:
    await ChannelService._get_channel_for_update(db, channel_id)
    await db.execute(select(ChannelInvite).where(ChannelInvite.id == invite_id).with_for_update())


# AV-04 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_normal_command_rate_works_and_flood_is_throttled(monkeypatch) -> None:
    monkeypatch.setenv("WS_COMMAND_BUDGET_CAPACITY", "10")
    monkeypatch.setenv("WS_COMMAND_BUDGET_REFILL_PER_SECOND", "0.001")
    get_settings.cache_clear()
    socket = _RecordingWebSocket([_client_frame("ping") for _ in range(11)])
    manager = WSManager(None, None, None)

    with pytest.raises(WebSocketDisconnect):
        await manager._inbound_loop(socket, uuid4(), uuid4())

    assert [item["type"] for item in socket.sent[:10]] == ["pong"] * 10
    assert socket.sent[10]["payload"]["code"] == "RATE_LIMITED"
    assert socket.sent[10]["payload"]["details"]["budget"] == "commands"


@pytest.mark.asyncio
async def test_repeated_expensive_resume_is_bounded_by_history_budget(monkeypatch) -> None:
    monkeypatch.setenv("WS_HISTORY_BUDGET_CAPACITY", "100")
    monkeypatch.setenv("WS_HISTORY_BUDGET_REFILL_PER_SECOND", "0.001")
    monkeypatch.setenv("WS_HISTORY_BATCH_LIMIT", "100")
    get_settings.cache_clear()
    socket = _RecordingWebSocket()
    manager = WSManager(lambda: _EmptySession(), None, None)

    async def no_channels(user_id: UUID) -> list[str]:
        return []

    manager._member_channel_ids = no_channels
    payload = {"channels": [], "limit": 100}
    await manager._handle_resume(socket, uuid4(), payload, uuid4())
    await manager._handle_resume(socket, uuid4(), payload, uuid4())

    assert socket.sent[0]["type"] == "sync"
    assert socket.sent[1]["payload"]["code"] == "RATE_LIMITED"
    assert socket.sent[1]["payload"]["details"]["budget"] == "history_rows"


@pytest.mark.asyncio
async def test_one_websocket_history_command_has_one_total_row_cap(db_session) -> None:
    owner = await _register(db_session, "ws_history_owner5")
    first = await _channel(db_session, owner, "WS History First")
    second = await _channel(db_session, owner, "WS History Second")
    encrypted = encrypt_message("bounded websocket history")
    for channel in (first, second):
        db_session.add_all(
            [
                Message(
                    channel_id=channel.id,
                    sender_user_id=owner.id,
                    seq_id=seq_id,
                    content_type=ContentType.text,
                    content_text=encrypted,
                )
                for seq_id in range(1, 81)
            ]
        )
    await db_session.commit()

    socket = _RecordingWebSocket()
    manager = WSManager(_session_maker(db_session), None, None)
    count = await manager._send_history(socket, owner.id, [str(first.id), str(second.id)])

    messages = socket.sent[-1]["payload"]["messages"]
    assert count == get_settings().ws_history_batch_limit == 100
    assert len(messages) == 100
    assert sum(message["channel_id"] == str(first.id) for message in messages) == 80
    assert sum(message["channel_id"] == str(second.id) for message in messages) == 20


@pytest.mark.asyncio
async def test_identical_subscribe_does_not_repeat_history_work() -> None:
    channel_id = uuid4()
    socket = _RecordingWebSocket()
    manager = WSManager(None, None, None)
    membership_queries = 0
    history_calls = 0

    async def channel_states(user_id: UUID) -> dict[str, int]:
        nonlocal membership_queries
        membership_queries += 1
        return {str(channel_id): 1}

    async def send_history(*args, **kwargs) -> int:
        nonlocal history_calls
        history_calls += 1
        await socket.send_json({"type": "sync", "payload": {"messages": ["history"]}})
        return 1

    manager._member_channel_states = channel_states
    manager._send_history = send_history
    payload = {"channel_ids": [str(channel_id)], "from_seq_id": 0}

    await manager._handle_subscribe(socket, uuid4(), payload, uuid4())
    await manager._handle_subscribe(socket, uuid4(), payload, uuid4())

    assert membership_queries == 1
    assert history_calls == 1
    assert socket.sent[-1]["payload"]["messages"] == []


@pytest.mark.asyncio
async def test_oversized_websocket_frame_fails_safely_before_json_parse(monkeypatch) -> None:
    monkeypatch.setenv("WS_MAX_INBOUND_MESSAGE_BYTES", "1024")
    get_settings.cache_clear()
    socket = _RecordingWebSocket(["x" * 1025])
    manager = WSManager(None, None, None)

    await manager._inbound_loop(socket, uuid4(), uuid4())

    assert socket.sent[0]["payload"]["code"] == "MESSAGE_TOO_LARGE"
    assert socket.closed is not None and socket.closed[0] == 1009


def test_abusive_socket_budget_does_not_consume_another_socket_budget(monkeypatch) -> None:
    monkeypatch.setenv("WS_COMMAND_BUDGET_CAPACITY", "10")
    monkeypatch.setenv("WS_COMMAND_BUDGET_REFILL_PER_SECOND", "0.001")
    get_settings.cache_clear()
    manager = WSManager(None, None, None)
    abusive = _RecordingWebSocket()
    legitimate = _RecordingWebSocket()
    abusive_budget, _ = manager._socket_controls(abusive)
    legitimate_budget, _ = manager._socket_controls(legitimate)

    assert abusive_budget.charge_command("subscribe") is None
    assert abusive_budget.charge_command("subscribe") is not None
    assert legitimate_budget.charge_command("subscribe") is None


def test_five_abusive_sockets_each_have_a_finite_expensive_command_budget(monkeypatch) -> None:
    monkeypatch.setenv("WS_COMMAND_BUDGET_CAPACITY", "10")
    monkeypatch.setenv("WS_COMMAND_BUDGET_REFILL_PER_SECOND", "0.001")
    get_settings.cache_clear()
    manager = WSManager(None, None, None)
    sockets = [_RecordingWebSocket() for _ in range(5)]

    for socket in sockets:
        budget, _ = manager._socket_controls(socket)
        assert budget.charge_command("resume") is None
        assert budget.charge_command("resume") is not None

    assert len(manager._socket_work_budgets) == 5


@pytest.mark.asyncio
async def test_websocket_limiter_state_is_cleaned_after_disconnect() -> None:
    socket = _RecordingWebSocket()
    manager = WSManager(None, _PresenceRedis(), None)
    manager._socket_controls(socket)
    manager._last_subscribe_history_requests[id(socket)] = ((str(uuid4()),), 0)

    await manager.disconnect(socket, "socket_cleanup5")

    assert id(socket) not in manager._socket_work_budgets
    assert id(socket) not in manager._command_locks
    assert id(socket) not in manager._last_subscribe_history_requests


# AV-05 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attachment_access_follows_active_channel_lifecycle_and_explicit_owner_policy(
    db_session,
) -> None:
    channel_owner = await _register(db_session, "attachment_channel_owner5")
    upload_owner = await _register(db_session, "attachment_upload_owner5")
    admin = await _register(db_session, "attachment_admin5")
    member = await _register(db_session, "attachment_member5")
    pending = await _register(db_session, "attachment_pending5")
    removed = await _register(db_session, "attachment_removed5")
    outsider = await _register(db_session, "attachment_outsider5")
    superadmin = await _register(db_session, "attachment_superadmin5")
    superadmin.is_superadmin = True
    channel = await _channel(db_session, channel_owner, "Attachment Lifecycle")
    for user, role in (
        (upload_owner, MembershipRole.member),
        (admin, MembershipRole.admin),
        (member, MembershipRole.member),
        (pending, MembershipRole.pending),
    ):
        db_session.add(
            ChannelMembership(
                channel_id=channel.id,
                user_id=user.id,
                role=role,
                approved_at=utcnow() if role != MembershipRole.pending else None,
                created_by_user_id=channel_owner.id,
            )
        )
    upload = Upload(
        owner_user_id=upload_owner.id,
        filename="protected.txt",
        content_type="text/plain",
        size_bytes=9,
        checksum=None,
        storage_path="phase5/protected.txt",
        public_url="/v1/uploads/pending/content",
    )
    message = Message(
        channel_id=channel.id,
        sender_user_id=upload_owner.id,
        seq_id=1,
        content_type=ContentType.text,
        content_text=encrypt_message("attachment"),
    )
    db_session.add_all([upload, message])
    await db_session.flush()
    upload.public_url = f"/v1/uploads/{upload.id}/content"
    db_session.add(
        MessageAttachment(
            message_id=message.id,
            upload_id=upload.id,
            channel_id=channel.id,
        )
    )
    await db_session.commit()

    assert await MessageService.can_access_upload(db_session, upload_owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, channel_owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, admin.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, pending.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, removed.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, outsider.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, superadmin.id, upload.id) is False

    channel.deleted_at = utcnow()
    await db_session.commit()
    assert await MessageService.can_access_upload(db_session, upload_owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, channel_owner.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, admin.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is False
    with pytest.raises(HTTPException) as denied:
        await get_upload_content(upload.id, db_session, member, _LuaRateRedis())
    assert denied.value.status_code == 403

    channel.deleted_at = None
    await db_session.commit()
    assert await MessageService.can_access_upload(db_session, channel_owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, removed.id, upload.id) is False

    message.deleted_at = utcnow()
    await db_session.commit()
    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is False
    assert await MessageService.can_access_upload(db_session, upload_owner.id, upload.id) is True


# AV-06 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_targeted_invite_accepts_once_and_expired_or_deleted_channel_invites_fail(db_session) -> None:
    owner = await _register(db_session, "invite_target_owner5")
    target = await _register(db_session, "invite_target_user5")
    expired_target = await _register(db_session, "invite_expired_user5")
    deleted_target = await _register(db_session, "invite_deleted_user5")
    channel = await _channel(db_session, owner, "Targeted Invite", join_mode="invite_only")
    channel_id = channel.id
    owner_id = owner.id
    target_id = target.id
    expired_target_id = expired_target.id
    deleted_target_id = deleted_target.id

    invite, token = await ChannelService.create_invite(
        db_session,
        channel_id,
        owner_id,
        InviteRequest(invited_user_id=target_id),
    )
    membership = await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, target_id)
    assert membership.role == MembershipRole.member
    with pytest.raises(AppError) as second:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, target_id)
    assert second.value.code == "INVITE_ALREADY_ACCEPTED"
    await db_session.rollback()

    expired, expired_token = await ChannelService.create_invite(
        db_session,
        channel_id,
        owner_id,
        InviteRequest(invited_user_id=expired_target_id),
    )
    expired.expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(AppError) as expired_error:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), expired_token, expired_target_id)
    assert expired_error.value.code == "INVITE_EXPIRED"
    await db_session.rollback()

    deleted, deleted_token = await ChannelService.create_invite(
        db_session,
        channel_id,
        owner_id,
        InviteRequest(invited_user_id=deleted_target_id),
    )
    assert deleted.id is not None
    channel = await db_session.get(type(channel), channel_id)
    assert channel is not None
    channel.deleted_at = utcnow()
    await db_session.commit()
    with pytest.raises(AppError) as deleted_error:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), deleted_token, deleted_target_id)
    assert deleted_error.value.code == "CHANNEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_generic_invite_is_reusable_and_each_effective_acceptance_is_audited(db_session) -> None:
    owner = await _register(db_session, "invite_generic_owner5")
    first_user = await _register(db_session, "invite_generic_first5")
    second_user = await _register(db_session, "invite_generic_second5")
    channel = await _channel(db_session, owner, "Reusable Generic Invite", join_mode="invite_only")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(is_generic=True),
    )

    await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, first_user.id)
    assert (await ChannelService.get_invite_preview(db_session, token))["is_valid"] is True
    await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, second_user.id)
    await db_session.refresh(invite)
    assert invite.accepted_at is None
    rows = await db_session.execute(
        select(Event).where(Event.channel_id == channel.id, Event.event_type == "invite.accepted")
    )
    accepted_users = {event.payload["user_id"] for event in rows.scalars().all()}
    assert accepted_users == {str(first_user.id), str(second_user.id)}


@pytest.mark.asyncio
async def test_targeted_revoke_winning_race_prevents_membership(db_session) -> None:
    owner = await _register(db_session, "invite_revoke_owner5")
    target = await _register(db_session, "invite_revoke_target5")
    channel = await _channel(db_session, owner, "Revoke Wins", join_mode="invite_only")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target.id),
    )
    sessions = _session_maker(db_session)

    async with sessions() as revoke_db, sessions() as accept_db:
        await _prelock_invite(revoke_db, channel.id, invite.id)
        accept_started = asyncio.Event()
        accept_task = asyncio.create_task(
            ChannelService.accept_invite(
                _SignallingSession(accept_db, accept_started),
                _NoDirectAmqp(),
                token,
                target.id,
            )
        )
        await asyncio.wait_for(accept_started.wait(), timeout=2)
        await ChannelService.revoke_invite(revoke_db, channel.id, invite.id, owner.id)
        with pytest.raises(AppError) as accept_error:
            await accept_task
        assert accept_error.value.code == "INVITE_REVOKED"

    async with sessions() as verify_db:
        assert await ChannelService.get_membership(verify_db, channel.id, target.id) is None
        stored = await verify_db.get(ChannelInvite, invite.id)
        assert stored is not None and stored.revoked_at is not None and stored.accepted_at is None


@pytest.mark.asyncio
async def test_two_concurrent_targeted_accepts_create_at_most_one_membership(db_session) -> None:
    owner = await _register(db_session, "invite_double_owner5")
    target = await _register(db_session, "invite_double_target5")
    channel = await _channel(db_session, owner, "Double Accept", join_mode="invite_only")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target.id),
    )
    sessions = _session_maker(db_session)

    async with sessions() as first_db, sessions() as second_db:
        await _prelock_invite(first_db, channel.id, invite.id)
        second_started = asyncio.Event()
        second_task = asyncio.create_task(
            ChannelService.accept_invite(
                _SignallingSession(second_db, second_started),
                _NoDirectAmqp(),
                token,
                target.id,
            )
        )
        await asyncio.wait_for(second_started.wait(), timeout=2)
        first = await ChannelService.accept_invite(first_db, _NoDirectAmqp(), token, target.id)
        assert first.role == MembershipRole.member
        with pytest.raises(AppError) as second:
            await second_task
        assert second.value.code == "INVITE_ALREADY_ACCEPTED"

    async with sessions() as verify_db:
        membership = await ChannelService.get_membership(verify_db, channel.id, target.id)
        stored = await verify_db.get(ChannelInvite, invite.id)
        assert membership is not None
        assert stored is not None and stored.accepted_at is not None and stored.revoked_at is None


@pytest.mark.asyncio
async def test_targeted_accept_winning_race_has_consistent_state(db_session) -> None:
    owner = await _register(db_session, "invite_accept_owner5")
    target = await _register(db_session, "invite_accept_target5")
    channel = await _channel(db_session, owner, "Accept Wins", join_mode="invite_only")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target.id),
    )
    sessions = _session_maker(db_session)

    async with sessions() as accept_db, sessions() as revoke_db:
        await _prelock_invite(accept_db, channel.id, invite.id)
        revoke_started = asyncio.Event()
        revoke_task = asyncio.create_task(
            ChannelService.revoke_invite(
                _SignallingSession(revoke_db, revoke_started),
                channel.id,
                invite.id,
                owner.id,
            )
        )
        await asyncio.wait_for(revoke_started.wait(), timeout=2)
        accepted = await ChannelService.accept_invite(
            accept_db,
            _NoDirectAmqp(),
            token,
            target.id,
        )
        assert accepted.role == MembershipRole.member
        with pytest.raises(AppError) as revoke_error:
            await revoke_task
        assert revoke_error.value.code == "INVITE_ALREADY_ACCEPTED"

    async with sessions() as verify_db:
        assert await ChannelService.get_membership(verify_db, channel.id, target.id) is not None
        stored = await verify_db.get(ChannelInvite, invite.id)
        assert stored is not None and stored.accepted_at is not None and stored.revoked_at is None


@pytest.mark.asyncio
async def test_concurrent_generic_accepts_both_succeed_then_revoke_blocks_later_use(db_session) -> None:
    owner = await _register(db_session, "invite_concurrent_owner5")
    first_user = await _register(db_session, "invite_concurrent_first5")
    second_user = await _register(db_session, "invite_concurrent_second5")
    later_user = await _register(db_session, "invite_concurrent_later5")
    channel = await _channel(db_session, owner, "Concurrent Generic", join_mode="invite_only")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(is_generic=True),
    )
    sessions = _session_maker(db_session)

    async with sessions() as first_db, sessions() as second_db:
        await _prelock_invite(first_db, channel.id, invite.id)
        second_started = asyncio.Event()
        second_task = asyncio.create_task(
            ChannelService.accept_invite(
                _SignallingSession(second_db, second_started),
                _NoDirectAmqp(),
                token,
                second_user.id,
            )
        )
        await asyncio.wait_for(second_started.wait(), timeout=2)
        first_membership = await ChannelService.accept_invite(
            first_db,
            _NoDirectAmqp(),
            token,
            first_user.id,
        )
        second_membership = await second_task
        assert first_membership.role == second_membership.role == MembershipRole.member

    async with sessions() as revoke_db:
        await ChannelService.revoke_invite(revoke_db, channel.id, invite.id, owner.id)
    async with sessions() as later_db:
        with pytest.raises(AppError) as revoked:
            await ChannelService.accept_invite(later_db, _NoDirectAmqp(), token, later_user.id)
        assert revoked.value.code == "INVITE_REVOKED"
        await later_db.rollback()
        assert await ChannelService.get_membership(later_db, channel.id, later_user.id) is None


# AV-07 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_fixed_window_is_one_atomic_eval_and_ttl_is_not_extended() -> None:
    redis = _LuaRateRedis()
    first = await RateLimitService.hit(redis, "rl:atomic", limit=2, window_seconds=60)
    original_expiry = redis.expires_at["rl:atomic"]
    redis.now = 10
    second = await RateLimitService.hit(redis, "rl:atomic", limit=2, window_seconds=60)
    third = await RateLimitService.hit(redis, "rl:atomic", limit=2, window_seconds=60)

    assert first.backend == second.backend == third.backend == "redis"
    assert first.retry_after_seconds is None and second.retry_after_seconds is None
    assert third.retry_after_seconds == 50
    assert redis.expires_at["rl:atomic"] == original_expiry
    assert redis.eval_calls == 3
    assert all("INCR" in script and "EXPIRE" in script and "TTL" in script for script in redis.scripts)


@pytest.mark.asyncio
async def test_fallback_key_churn_cannot_reset_blocked_identity_and_memory_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_LOCAL_MAX_KEYS", "100")
    get_settings.cache_clear()
    redis = _LuaRateRedis(fail=True)
    assert (await RateLimitService.hit(redis, "rl:blocked", 1, 60)).retry_after_seconds is None
    assert (await RateLimitService.hit(redis, "rl:blocked", 1, 60)).retry_after_seconds is not None

    results = [
        await RateLimitService.hit(redis, f"rl:churn:{index}", 1, 60)
        for index in range(150)
    ]

    assert len(RateLimitService._local_windows) == 100
    assert len(RateLimitService._local_expiries) == 100
    assert any(result.retry_after_seconds is not None for result in results)
    assert (await RateLimitService.hit(redis, "rl:blocked", 1, 60)).retry_after_seconds is not None
    assert (await RateLimitService.hit(redis, "rl:new-sensitive", 1, 60)).retry_after_seconds is not None
    available_read = await RateLimitService.hit(
        redis,
        "rl:ordinary-read",
        1,
        60,
        failure_policy="allow",
    )
    assert available_read.backend == "bypassed" and available_read.retry_after_seconds is None


@pytest.mark.asyncio
async def test_redis_outage_fallback_and_recovery_resume_distributed_limiting() -> None:
    redis = _LuaRateRedis(fail=True)
    local = await RateLimitService.hit(redis, "rl:recovery", 1, 60)
    assert local.backend == "local" and local.retry_after_seconds is None

    redis.fail = False
    recovered_first = await RateLimitService.hit(redis, "rl:recovery", 1, 60)
    recovered_second = await RateLimitService.hit(redis, "rl:recovery", 1, 60)
    assert recovered_first.backend == recovered_second.backend == "redis"
    assert recovered_first.retry_after_seconds is None
    assert recovered_second.retry_after_seconds == 60
