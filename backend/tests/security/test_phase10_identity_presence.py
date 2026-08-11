import asyncio
import json
import os
from datetime import timedelta
from types import MethodType
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException, WebSocketDisconnect
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.auth import _enforce_email_verification_request_limits
from app.api.routes.users import update_me
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.utils import sha256_hex, utcnow
from app.db.models import (
    ChannelMembership,
    EmailVerificationChallenge,
    Event,
    MembershipRole,
    User,
)
from app.realtime.presence import PresenceService, PresenceTransition
from app.realtime.ws_manager import WSManager
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, InviteRequest
from app.schemas.users import UpdateMeRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.email_delivery_service import CaptureVerificationMailer
from app.services.email_verification_service import EmailVerificationService


TEST_DATA_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class _NoDirectAmqp:
    async def channel(self):
        raise AssertionError("Phase 10 invite paths must keep broker work in the outbox")


class _FailingMailer:
    async def send_verification(self, recipient: str, verification_url: str) -> None:
        raise ConnectionError("provider fixture unavailable")


class _FixedWindowRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        _ = script, numkeys, window_seconds
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], 900]


class _UnavailableRedis:
    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def _verification_token(mailer: CaptureVerificationMailer, index: int = -1) -> str:
    fragment = urlsplit(mailer.messages[index].verification_url).fragment
    return parse_qs(fragment)["token"][0]


async def _register(db: AsyncSession, username: str, email: str | None = None) -> User:
    return await AuthService.register(
        db,
        RegisterRequest(
            username=username,
            email=email if email is not None else f"{username}@example.com",
            password="Password123!",
        ),
    )


@pytest.fixture
def verification_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_VERIFICATION_ENABLED", "true")
    monkeypatch.setenv("EMAIL_DELIVERY_MODE", "capture")
    monkeypatch.setenv("EMAIL_VERIFICATION_PUBLIC_URL", "http://localhost:3000/en/verify-email")
    monkeypatch.setenv("EMAIL_VERIFICATION_TTL_MINUTES", "30")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_registration_starts_unverified(db_session: AsyncSession) -> None:
    user = await _register(db_session, "phase10_register")
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_request_delivers_raw_token_but_persists_only_sha256(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_hash")
    mailer = CaptureVerificationMailer()

    result = await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)
    challenge = await db_session.scalar(select(EmailVerificationChallenge))

    assert result.status == "sent"
    assert challenge is not None
    assert challenge.token_hash == sha256_hex(token)
    assert token not in challenge.token_hash
    assert challenge.email == "phase10_hash@example.com"


@pytest.mark.asyncio
async def test_valid_confirmation_verifies_exact_current_email_and_reuse_fails(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_confirm")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)

    result = await EmailVerificationService.confirm(db_session, user.id, token)
    await db_session.refresh(user)
    assert result.status == "verified"
    assert user.email_verified_at is not None

    with pytest.raises(AppError) as reused:
        await EmailVerificationService.confirm(db_session, user.id, token)
    assert reused.value.code == "EMAIL_VERIFICATION_USED"
    assert await db_session.scalar(
        select(func.count(Event.id)).where(Event.event_type == "email.verified")
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["expired", "revoked"])
async def test_expired_and_revoked_tokens_fail_closed(
    db_session: AsyncSession,
    verification_enabled: None,
    state: str,
) -> None:
    user = await _register(db_session, f"phase10_{state}")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)
    challenge = await db_session.scalar(select(EmailVerificationChallenge))
    assert challenge is not None
    if state == "expired":
        challenge.expires_at = utcnow() - timedelta(seconds=1)
    else:
        challenge.revoked_at = utcnow()
    await db_session.commit()

    with pytest.raises(AppError) as denied:
        await EmailVerificationService.confirm(db_session, user.id, token)
    assert denied.value.code in {"EMAIL_VERIFICATION_EXPIRED", "EMAIL_VERIFICATION_INVALID"}
    await db_session.refresh(user)
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_user_a_token_cannot_verify_user_b(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user_a = await _register(db_session, "phase10_user_a")
    user_b = await _register(db_session, "phase10_user_b")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user_a.id, mailer)

    with pytest.raises(AppError) as denied:
        await EmailVerificationService.confirm(db_session, user_b.id, _verification_token(mailer))
    assert denied.value.status_code == 403
    await db_session.refresh(user_b)
    assert user_b.email_verified_at is None


@pytest.mark.asyncio
async def test_email_change_revokes_old_challenges_and_old_token_cannot_verify(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_change", "old10@example.com")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)

    updated = await update_me(UpdateMeRequest(email="new10@example.com"), db_session, user)
    challenge = await db_session.scalar(select(EmailVerificationChallenge))
    assert updated.email == "new10@example.com"
    assert updated.email_verified_at is None
    assert challenge is not None and challenge.revoked_at is not None

    with pytest.raises(AppError):
        await EmailVerificationService.confirm(db_session, user.id, token)
    await db_session.refresh(user)
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_email_change_clears_existing_proof_and_revokes_active_history(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_invalidate", "verified10@example.com")
    now = utcnow()
    user.email_verified_at = now
    challenge = EmailVerificationChallenge(
        user_id=user.id,
        email="verified10@example.com",
        token_hash=sha256_hex("historical-active-token"),
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    db_session.add(challenge)
    await db_session.commit()

    response = await update_me(UpdateMeRequest(email="replacement10@example.com"), db_session, user)
    await db_session.refresh(challenge)
    assert response.email_verified_at is None
    assert challenge.revoked_at is not None


@pytest.mark.asyncio
async def test_new_request_supersedes_previous_active_challenge(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_supersede")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    first_token = _verification_token(mailer)
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    second_token = _verification_token(mailer)

    challenges = list(
        (
            await db_session.execute(
                select(EmailVerificationChallenge).order_by(EmailVerificationChallenge.created_at.asc())
            )
        ).scalars()
    )
    assert len(challenges) == 2
    assert challenges[0].revoked_at is not None
    assert challenges[1].revoked_at is None
    with pytest.raises(AppError):
        await EmailVerificationService.confirm(db_session, user.id, first_token)
    assert (await EmailVerificationService.confirm(db_session, user.id, second_token)).status == "verified"


@pytest.mark.asyncio
async def test_concurrent_confirmation_has_exactly_one_effective_success(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_concurrent")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)
    sessions = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)

    async def attempt() -> str:
        async with sessions() as session:
            try:
                await EmailVerificationService.confirm(session, user.id, token)
                return "verified"
            except AppError as exc:
                return exc.code

    outcomes = await asyncio.gather(attempt(), attempt())
    assert outcomes.count("verified") == 1
    assert outcomes.count("EMAIL_VERIFICATION_USED") == 1
    db_session.expire_all()
    assert await db_session.scalar(
        select(func.count(Event.id)).where(Event.event_type == "email.verified")
    ) == 1


@pytest.mark.asyncio
async def test_delivery_failure_revokes_challenge_without_verifying_user(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    user = await _register(db_session, "phase10_smtp_failure")
    with pytest.raises(AppError) as failed:
        await EmailVerificationService.request_verification(db_session, user.id, _FailingMailer())
    assert failed.value.code == "EMAIL_DELIVERY_FAILED"
    await db_session.refresh(user)
    challenge = await db_session.scalar(select(EmailVerificationChallenge))
    assert user.email_verified_at is None
    assert challenge is not None and challenge.revoked_at is not None


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "jwt_secret": "phase10-production-jwt-secret-with-enough-entropy-123456",
        "data_encryption_active_key_id": "phase10-key",
        "data_encryption_keys": {"phase10-key": TEST_DATA_KEY},
        "trusted_hosts": ["chat.example.com"],
        "cors_origins": ["https://chat.example.com"],
        "email_verification_enabled": True,
        "email_verification_public_url": "https://chat.example.com/en/verify-email",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_rejects_console_or_capture_delivery() -> None:
    for mode in ("console", "capture"):
        with pytest.raises(ValueError, match="EMAIL_DELIVERY_MODE=smtp"):
            _production_settings(email_delivery_mode=mode)


def test_production_rejects_plaintext_smtp() -> None:
    with pytest.raises(ValueError, match="implicit TLS or STARTTLS"):
        _production_settings(
            email_delivery_mode="smtp",
            smtp_host="smtp.example.com",
            smtp_from_email="no-reply@example.com",
            smtp_use_tls=False,
            smtp_use_starttls=False,
        )


@pytest.mark.asyncio
async def test_verification_request_rate_limits_prevent_flooding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_EMAIL_VERIFICATION_USER_PER_15_MINUTES", "2")
    monkeypatch.setenv("RATE_LIMIT_EMAIL_VERIFICATION_IP_PER_15_MINUTES", "10")
    get_settings.cache_clear()
    redis = _FixedWindowRedis()
    user_id = uuid4()
    await _enforce_email_verification_request_limits(redis, user_id, "192.0.2.10")
    await _enforce_email_verification_request_limits(redis, user_id, "192.0.2.10")
    with pytest.raises(HTTPException) as limited:
        await _enforce_email_verification_request_limits(redis, user_id, "192.0.2.10")
    assert limited.value.status_code == 429


@pytest.mark.asyncio
async def test_raw_verification_token_never_enters_audit_payload_or_logs(
    db_session: AsyncSession,
    verification_enabled: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = await _register(db_session, "phase10_no_token_log")
    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, user.id, mailer)
    token = _verification_token(mailer)
    await EmailVerificationService.confirm(db_session, user.id, token)

    payloads = list((await db_session.execute(select(Event.payload))).scalars())
    assert token not in json.dumps(payloads)
    assert token not in caplog.text


@pytest.mark.asyncio
async def test_real_verification_unlocks_pre_registration_invite(
    db_session: AsyncSession,
    verification_enabled: None,
) -> None:
    owner = await _register(db_session, "phase10_invite_owner")
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Phase 10 Invite",
            channel_slug="phase10_invite",
            visibility="private",
            join_mode="invite_only",
        ),
        _NoDirectAmqp(),
    )
    invite, invite_token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="future10@example.com"),
    )
    assert invite.invited_user_id is None
    future = await _register(db_session, "phase10_future", "future10@example.com")
    future_id = future.id
    channel_id = channel.id

    with pytest.raises(AppError) as before:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), invite_token, future_id)
    assert before.value.code == "EMAIL_VERIFICATION_REQUIRED"
    await db_session.rollback()

    mailer = CaptureVerificationMailer()
    await EmailVerificationService.request_verification(db_session, future_id, mailer)
    await EmailVerificationService.confirm(db_session, future_id, _verification_token(mailer))
    membership = await ChannelService.accept_invite(db_session, _NoDirectAmqp(), invite_token, future_id)
    assert membership.role == MembershipRole.member
    assert await db_session.scalar(
        select(func.count(ChannelMembership.user_id)).where(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == future_id,
        )
    ) == 1


@pytest_asyncio.fixture
async def live_presence() -> tuple[PresenceService, Redis, str]:
    redis_url = os.environ.get("PHASE10_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    redis = Redis.from_url(redis_url, decode_responses=False)
    try:
        await redis.ping()
    except Exception as exc:
        await redis.aclose()
        pytest.skip(f"Phase 10 disposable Redis is unavailable at {redis_url!r}: {exc}")
    namespace = f"phase10:presence:{uuid4().hex}"
    online_key = f"{namespace}:online"
    service = PresenceService(
        redis,
        namespace=namespace,
        online_key=online_key,
        lease_seconds=2,
        reaper_batch_size=50,
    )
    try:
        yield service, redis, online_key
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{namespace}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


@pytest.mark.asyncio
async def test_first_and_second_socket_then_local_disconnect_transitions(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    assert await service.register(user_id, "presence_user10", "socket-a", now_epoch=100) == PresenceTransition.online
    assert await service.register(user_id, "presence_user10", "socket-b", now_epoch=100) == PresenceTransition.none
    assert await service.disconnect(user_id, "presence_user10", "socket-a", now_epoch=101) == PresenceTransition.none
    assert await redis.sismember(online_key, "presence_user10")
    assert await service.disconnect(user_id, "presence_user10", "socket-b", now_epoch=101) == PresenceTransition.offline
    assert not await redis.sismember(online_key, "presence_user10")


@pytest.mark.asyncio
async def test_two_backend_instances_share_aggregate_presence(live_presence) -> None:
    service_a, redis, online_key = live_presence
    service_b = PresenceService(
        redis,
        namespace=service_a._namespace,
        online_key=online_key,
        lease_seconds=2,
        reaper_batch_size=50,
    )
    user_id = uuid4()
    await service_a.register(user_id, "distributed10", "backend-a", now_epoch=200)
    await service_b.register(user_id, "distributed10", "backend-b", now_epoch=200)
    assert await service_a.disconnect(user_id, "distributed10", "backend-a", now_epoch=201) == PresenceTransition.none
    assert await redis.sismember(online_key, "distributed10")
    assert await service_b.disconnect(user_id, "distributed10", "backend-b", now_epoch=201) == PresenceTransition.offline


@pytest.mark.asyncio
async def test_heartbeat_extends_lease_and_reaper_expires_dead_socket(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    await service.register(user_id, "heartbeat10", "socket-a", now_epoch=300)
    await service.refresh(user_id, "heartbeat10", "socket-a", now_epoch=301.5)
    assert (await service.reap_expired(now_epoch=302.1)).offline_usernames == ()
    assert await redis.sismember(online_key, "heartbeat10")
    reaped = await service.reap_expired(now_epoch=304)
    assert reaped.offline_usernames == ("heartbeat10",)
    assert not await redis.sismember(online_key, "heartbeat10")


@pytest.mark.asyncio
async def test_stale_a_expires_while_live_b_refreshes_without_offline(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    await service.register(user_id, "mixedlease10", "socket-a", now_epoch=400)
    await service.register(user_id, "mixedlease10", "socket-b", now_epoch=400)
    await service.refresh(user_id, "mixedlease10", "socket-b", now_epoch=401.5)
    assert (await service.reap_expired(now_epoch=402.5)).offline_usernames == ()
    assert await redis.sismember(online_key, "mixedlease10")
    assert await redis.zcard(service.user_key(user_id)) == 1


@pytest.mark.asyncio
async def test_duplicate_reapers_emit_one_effective_offline(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    await service.register(user_id, "duereaper10", "socket-a", now_epoch=500)
    first, second = await asyncio.gather(
        service.reap_expired(now_epoch=503),
        service.reap_expired(now_epoch=503),
    )
    emitted = first.offline_usernames + second.offline_usernames
    assert emitted == ("duereaper10",)
    assert not await redis.sismember(online_key, "duereaper10")


@pytest.mark.asyncio
async def test_rapid_reconnect_cannot_leave_false_offline(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    await service.register(user_id, "reconnect10", "socket-a", now_epoch=600)
    await asyncio.gather(
        service.disconnect(user_id, "reconnect10", "socket-a", now_epoch=601),
        service.register(user_id, "reconnect10", "socket-b", now_epoch=601),
    )
    assert await redis.sismember(online_key, "reconnect10")
    assert await redis.zcard(service.user_key(user_id)) == 1


@pytest.mark.asyncio
async def test_session_specific_and_logout_all_presence_semantics(live_presence) -> None:
    service, redis, online_key = live_presence
    user_id = uuid4()
    await service.register(user_id, "sessions10", "session-one", now_epoch=700)
    await service.register(user_id, "sessions10", "session-two", now_epoch=700)
    assert await service.disconnect(user_id, "sessions10", "session-one", now_epoch=701) == PresenceTransition.none
    assert await redis.sismember(online_key, "sessions10")
    assert await service.disconnect(user_id, "sessions10", "session-two", now_epoch=701) == PresenceTransition.offline


@pytest.mark.asyncio
async def test_presence_redis_failure_is_unknown_not_false_offline() -> None:
    service = PresenceService(_UnavailableRedis(), lease_seconds=20)
    user_id = uuid4()
    assert await service.register(user_id, "failure10", "socket-a") == PresenceTransition.unknown
    assert await service.disconnect(user_id, "failure10", "socket-a") == PresenceTransition.unknown
    assert not (await service.reap_expired()).available


@pytest.mark.asyncio
async def test_socket_heartbeat_task_is_cancelled_when_socket_loop_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESENCE_REFRESH_SECONDS", "5")
    monkeypatch.setenv("PRESENCE_LEASE_SECONDS", "15")
    get_settings.cache_clear()
    manager = WSManager(None, None, None)
    socket = _RecordingWebSocket()
    user_id = uuid4()
    manager._presence_connection_ids[id(socket)] = "connection-task"

    async def wait_forever(self, *args):
        await asyncio.Event().wait()

    async def finish_inbound(self, *args):
        return None

    manager._redis_forward_loop = MethodType(wait_forever, manager)
    manager._inbound_loop = MethodType(finish_inbound, manager)
    await manager.run_socket(
        socket,
        user_id,
        "taskcleanup10",
        uuid4(),
        utcnow() + timedelta(minutes=5),
    )
    assert id(socket) not in manager._presence_heartbeat_tasks
