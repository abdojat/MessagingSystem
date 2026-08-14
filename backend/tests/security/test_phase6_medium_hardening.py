import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.api.routes.messages import _enforce_media, get_upload_content
from app.api.routes.users import update_me
from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import ChannelInvite, MembershipRole, Upload, User
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, InviteRequest
from app.schemas.users import UpdateMeRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.download_service import (
    DownloadConcurrencyLimiter,
    LeasedFileResponse,
    protected_download_limiter,
)


class _NoDirectAmqp:
    async def channel(self):
        raise AssertionError("invite acceptance must keep broker work in the outbox")


class _RateRedis:
    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        return [1, window_seconds]


class _FixedCountRateRedis:
    def __init__(self, count: int) -> None:
        self.count = count
        self.keys: list[str] = []

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        self.keys.append(key)
        return [self.count, window_seconds]


class _TrackingSession:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        await self._session.close()

    def __getattr__(self, name: str):
        return getattr(self._session, name)


def _request(client_ip: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/uploads/content",
            "raw_path": b"/v1/uploads/content",
            "query_string": b"",
            "headers": headers,
            "client": (client_ip, 1234),
            "server": ("test", 80),
            "extensions": {},
        }
    )


async def _receive_request() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _register(db: AsyncSession, username: str, email: str | None = None) -> User:
    return await AuthService.register(
        db,
        RegisterRequest(
            username=username,
            email=email if email is not None else f"{username}@example.com",
            password="Password123!",
        ),
    )


async def _invite_channel(db: AsyncSession, owner: User, name: str):
    return await ChannelService.create_channel(
        db,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode="invite_only"),
        _NoDirectAmqp(),
    )


def _session_maker(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


def _limits(*, user: int = 3, ip: int = 12, global_: int = 100) -> dict[str, int]:
    return {
        "per_user_limit": user,
        "per_ip_limit": ip,
        "global_limit": global_,
    }


# P5V-01 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_account_email_invite_resolves_to_immutable_user_id(db_session) -> None:
    owner = await _register(db_session, "phase6_resolution_owner")
    target = await _register(db_session, "phase6_resolution_target", "target@example.com")
    channel = await _invite_channel(db_session, owner, "Existing email resolution")

    invite, _ = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="  TARGET@Example.com "),
    )

    assert invite.invited_user_id == target.id
    assert invite.invited_email == "target@example.com"


@pytest.mark.asyncio
async def test_email_reassignment_cannot_transfer_existing_account_invite(db_session) -> None:
    owner = await _register(db_session, "phase6_reassign_owner")
    target = await _register(db_session, "phase6_reassign_target", "assigned@example.com")
    attacker = await _register(db_session, "phase6_reassign_attacker", "attacker@example.com")
    channel = await _invite_channel(db_session, owner, "Immutable invite target")
    target_id = target.id
    attacker_id = attacker.id
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="assigned@example.com"),
    )
    assert invite.invited_user_id == target_id

    await update_me(UpdateMeRequest(email="other@example.com"), db_session, target)
    await update_me(UpdateMeRequest(email="assigned@example.com"), db_session, attacker)

    with pytest.raises(AppError) as denied:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, attacker_id)
    assert denied.value.status_code == 403
    assert denied.value.code == "FORBIDDEN"
    await db_session.rollback()

    membership = await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, target_id)
    assert membership.user_id == target_id
    assert membership.role == MembershipRole.member


@pytest.mark.asyncio
async def test_email_change_clears_verification_without_affecting_same_value(db_session) -> None:
    user = await _register(db_session, "phase6_verified_change", "verified@example.com")
    user.email_verified_at = utcnow()
    await db_session.commit()
    verified_at = user.email_verified_at

    await update_me(UpdateMeRequest(email=" VERIFIED@EXAMPLE.COM "), db_session, user)
    assert user.email == "verified@example.com"
    assert user.email_verified_at == verified_at

    await update_me(UpdateMeRequest(email="new@example.com"), db_session, user)
    assert user.email == "new@example.com"
    assert user.email_verified_at is None


@pytest.mark.asyncio
async def test_preregistration_email_invite_requires_then_accepts_verified_owner(db_session) -> None:
    owner = await _register(db_session, "phase6_prereg_owner")
    channel = await _invite_channel(db_session, owner, "Pre-registration invite")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="future@example.com"),
    )
    assert invite.invited_user_id is None
    future_user = await _register(db_session, "phase6_future_user", "FUTURE@example.com")
    future_user_id = future_user.id

    with pytest.raises(AppError) as unverified:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, future_user_id)
    assert unverified.value.code == "EMAIL_VERIFICATION_REQUIRED"
    await db_session.rollback()

    # The repository intentionally has no email-delivery provider. Tests model
    # the trusted completion boundary by setting the state an external verifier
    # would persist after proving mailbox possession.
    future_user = await db_session.get(User, future_user_id)
    assert future_user is not None
    future_user.email_verified_at = utcnow()
    await db_session.commit()
    membership = await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, future_user_id)
    assert membership.user_id == future_user_id


@pytest.mark.asyncio
async def test_token_plus_unverified_profile_email_is_not_ownership(db_session) -> None:
    owner = await _register(db_session, "phase6_token_owner")
    attacker = await _register(db_session, "phase6_token_attacker", "elsewhere@example.com")
    channel = await _invite_channel(db_session, owner, "Token is insufficient")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="unclaimed@example.com"),
    )
    assert invite.invited_user_id is None
    await update_me(UpdateMeRequest(email="unclaimed@example.com"), db_session, attacker)
    assert attacker.email_verified_at is None

    with pytest.raises(AppError) as denied:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, attacker.id)
    assert denied.value.code == "EMAIL_VERIFICATION_REQUIRED"


@pytest.mark.asyncio
async def test_explicit_user_id_target_remains_authoritative(db_session) -> None:
    owner = await _register(db_session, "phase6_id_owner")
    target = await _register(db_session, "phase6_id_target")
    attacker = await _register(db_session, "phase6_id_attacker")
    target_id = target.id
    attacker_id = attacker.id
    channel = await _invite_channel(db_session, owner, "Explicit user target")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target_id),
    )
    assert invite.invited_user_id == target_id and invite.invited_email is None

    with pytest.raises(AppError) as denied:
        await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, attacker_id)
    assert denied.value.code == "FORBIDDEN"
    await db_session.rollback()
    assert (await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, target_id)).user_id == target_id


@pytest.mark.asyncio
async def test_generic_invite_semantics_remain_reusable(db_session) -> None:
    owner = await _register(db_session, "phase6_generic_owner")
    first = await _register(db_session, "phase6_generic_first")
    second = await _register(db_session, "phase6_generic_second")
    channel = await _invite_channel(db_session, owner, "Generic remains reusable")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(is_generic=True),
    )

    assert invite.invited_user_id is None and invite.invited_email is None
    assert (await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, first.id)).user_id == first.id
    assert (await ChannelService.accept_invite(db_session, _NoDirectAmqp(), token, second.id)).user_id == second.id
    await db_session.refresh(invite)
    assert invite.accepted_at is None


@pytest.mark.asyncio
async def test_concurrent_email_reassignment_has_one_owner_and_cannot_transfer_invite(db_session) -> None:
    owner = await _register(db_session, "phase6_race_owner")
    target = await _register(db_session, "phase6_race_target", "race@example.com")
    first = await _register(db_session, "phase6_race_first", "first@example.com")
    second = await _register(db_session, "phase6_race_second", "second@example.com")
    channel = await _invite_channel(db_session, owner, "Concurrent email claim")
    invite, token = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_email="race@example.com"),
    )
    await update_me(UpdateMeRequest(email="moved@example.com"), db_session, target)
    target_id = target.id
    first_id = first.id
    second_id = second.id
    sessions = _session_maker(db_session)

    async with sessions() as first_db, sessions() as second_db:
        first_user = await first_db.get(User, first_id)
        second_user = await second_db.get(User, second_id)
        assert first_user is not None and second_user is not None
        outcomes = await asyncio.gather(
            update_me(UpdateMeRequest(email="RACE@example.com"), first_db, first_user),
            update_me(UpdateMeRequest(email="race@example.com"), second_db, second_user),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, BaseException) for result in outcomes) == 1
        assert sum(isinstance(result, HTTPException) and result.status_code == 409 for result in outcomes) == 1

    async with sessions() as verify_db:
        owners = list(
            (
                await verify_db.execute(
                    select(User.id).where(func.lower(func.btrim(User.email)) == "race@example.com")
                )
            ).scalars().all()
        )
        assert len(owners) == 1
        assert invite.invited_user_id == target_id
        with pytest.raises(AppError) as denied:
            await ChannelService.accept_invite(verify_db, _NoDirectAmqp(), token, owners[0])
        assert denied.value.code == "FORBIDDEN"


# P5V-02 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_reads_have_a_separate_higher_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_MEDIA_PER_MINUTE", "60")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD_READ_PER_MINUTE", "600")
    get_settings.cache_clear()
    user_id = uuid4()

    read_redis = _FixedCountRateRedis(61)
    await _enforce_media(read_redis, user_id, "get")
    assert read_redis.keys == [f"rl:upload-read:{user_id}"]

    write_redis = _FixedCountRateRedis(61)
    with pytest.raises(HTTPException) as exc_info:
        await _enforce_media(write_redis, user_id, "put")
    assert exc_info.value.status_code == 429
    assert write_redis.keys == [f"rl:media-write:{user_id}"]


def test_protected_download_defaults_allow_attachment_heavy_views() -> None:
    fields = type(get_settings()).model_fields
    assert fields["max_concurrent_downloads_per_user"].default == 20
    assert fields["max_concurrent_downloads_per_ip"].default == 100
    assert fields["max_concurrent_downloads_global"].default == 1_000


@pytest.mark.asyncio
async def test_download_user_boundary_allows_limit_and_rejects_one_above() -> None:
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()
    leases = [
        await limiter.try_acquire(user_id, "198.51.100.1", **_limits(user=3))
        for _ in range(4)
    ]
    assert all(lease is not None for lease in leases[:3])
    assert leases[3] is None
    assert await limiter.active_for(user_id) == 3
    for lease in leases[:3]:
        await lease.release()


@pytest.mark.asyncio
async def test_download_ip_boundary_spans_many_accounts() -> None:
    limiter = DownloadConcurrencyLimiter()
    ip = "198.51.100.2"
    leases = [
        await limiter.try_acquire(uuid4(), ip, **_limits(user=3, ip=4, global_=20))
        for _ in range(5)
    ]
    assert all(lease is not None for lease in leases[:4])
    assert leases[4] is None
    assert await limiter.active_for_ip(ip) == 4
    assert await limiter.active_global() == 4
    for lease in leases[:4]:
        await lease.release()


@pytest.mark.asyncio
async def test_download_global_boundary_spans_users_and_ips() -> None:
    limiter = DownloadConcurrencyLimiter()
    leases = [
        await limiter.try_acquire(uuid4(), f"198.51.100.{index}", **_limits(global_=3))
        for index in range(1, 5)
    ]
    assert all(lease is not None for lease in leases[:3])
    assert leases[3] is None
    assert await limiter.active_global() == 3
    assert await limiter.state_sizes() == (3, 3)
    for lease in leases[:3]:
        await lease.release()


@pytest.mark.asyncio
async def test_download_atomic_admission_does_not_oversubscribe_boundary() -> None:
    limiter = DownloadConcurrencyLimiter()
    attempts = await asyncio.gather(
        *[
            limiter.try_acquire(
                uuid4(),
                f"203.0.113.{index}",
                **_limits(user=10, ip=10, global_=5),
            )
            for index in range(1, 41)
        ]
    )
    admitted = [lease for lease in attempts if lease is not None]
    assert len(admitted) == 5
    assert await limiter.active_global() == 5
    assert await limiter.state_sizes() == (5, 5)
    await asyncio.gather(*(lease.release() for lease in admitted))
    assert await limiter.active_global() == 0
    assert await limiter.state_sizes() == (0, 0)


@pytest.mark.asyncio
async def test_failed_download_admission_consumes_no_partial_capacity() -> None:
    limiter = DownloadConcurrencyLimiter()
    first_user = uuid4()
    rejected_user = uuid4()
    ip = "203.0.113.80"
    first = await limiter.try_acquire(first_user, ip, **_limits(user=3, ip=1, global_=10))
    rejected = await limiter.try_acquire(rejected_user, ip, **_limits(user=3, ip=1, global_=10))
    assert first is not None and rejected is None
    assert await limiter.active_for(rejected_user) == 0
    assert await limiter.active_for_ip(ip) == 1
    assert await limiter.active_global() == 1
    assert await limiter.state_sizes() == (1, 1)
    await first.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [asyncio.CancelledError(), RuntimeError("send failed")])
async def test_stream_failure_releases_user_ip_and_global_once(tmp_path: Path, failure: BaseException) -> None:
    path = tmp_path / "failure.bin"
    path.write_bytes(b"x" * 200_000)
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()
    ip = "203.0.113.81"
    lease = await limiter.try_acquire(user_id, ip, **_limits(user=1, ip=1, global_=1))
    assert lease is not None
    response = LeasedFileResponse(path, lease, media_type="application/octet-stream")

    async def fail_send(message: dict) -> None:
        if message["type"] == "http.response.body":
            raise failure

    with pytest.raises(type(failure)):
        await response(_request(ip).scope, _receive_request, fail_send)
    await lease.release()
    assert await limiter.active_for(user_id) == 0
    assert await limiter.active_for_ip(ip) == 0
    assert await limiter.active_global() == 0
    assert await limiter.state_sizes() == (0, 0)


@pytest.mark.asyncio
async def test_file_stat_failure_releases_all_download_capacity(tmp_path: Path) -> None:
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()
    ip = "203.0.113.82"
    lease = await limiter.try_acquire(user_id, ip, **_limits(user=1, ip=1, global_=1))
    assert lease is not None
    response = LeasedFileResponse(tmp_path / "missing.bin", lease, media_type="application/octet-stream")

    async def send(_: dict) -> None:
        return None

    with pytest.raises(RuntimeError):
        await response(_request(ip).scope, _receive_request, send)
    assert await limiter.active_global() == 0
    assert await limiter.state_sizes() == (0, 0)


@pytest.mark.asyncio
async def test_download_route_closes_database_before_streaming(db_session, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "phase6_db_lifetime_owner")
    content = b"database-session-released" * 10_000
    upload = Upload(
        owner_user_id=owner.id,
        filename="db-lifetime.bin",
        content_type="application/octet-stream",
        size_bytes=len(content),
        storage_path=f"{owner.id}/db-lifetime.bin",
        public_url="stored",
    )
    db_session.add(upload)
    await db_session.commit()
    path = tmp_path / upload.storage_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    tracked_db = _TrackingSession(db_session)

    response = await get_upload_content(
        upload.id,
        _request("198.51.100.50"),
        tracked_db,
        owner,
        _RateRedis(),
    )
    assert tracked_db.closed is True
    assert await protected_download_limiter.active_global() == 1
    sent: list[dict] = []

    async def send(message: dict) -> None:
        assert tracked_db.closed is True
        sent.append(message)

    await response(_request("198.51.100.50").scope, _receive_request, send)
    assert b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body") == content
    assert await protected_download_limiter.active_global() == 0


@pytest.mark.asyncio
async def test_response_construction_failure_releases_all_route_capacity(
    db_session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "phase6_response_failure_owner")
    upload = Upload(
        owner_user_id=owner.id,
        filename="response-failure.bin",
        content_type="application/octet-stream",
        size_bytes=1,
        storage_path=f"{owner.id}/response-failure.bin",
        public_url="stored",
    )
    db_session.add(upload)
    await db_session.commit()
    path = tmp_path / upload.storage_path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")

    def fail_response(*args, **kwargs):
        raise RuntimeError("response construction failed")

    monkeypatch.setattr("app.api.routes.messages.LeasedFileResponse", fail_response)
    with pytest.raises(RuntimeError, match="response construction failed"):
        await get_upload_content(
            upload.id,
            _request("198.51.100.51"),
            db_session,
            owner,
            _RateRedis(),
        )
    assert await protected_download_limiter.active_for(owner.id) == 0
    assert await protected_download_limiter.active_for_ip("198.51.100.51") == 0
    assert await protected_download_limiter.active_global() == 0


def test_client_ip_ignores_untrusted_forwarding_and_accepts_configured_proxy(monkeypatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "[]")
    get_settings.cache_clear()
    assert get_client_ip(_request("198.51.100.20", "203.0.113.9")) == "198.51.100.20"

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", '["172.31.240.10/32"]')
    get_settings.cache_clear()
    assert get_client_ip(_request("172.31.240.10", "203.0.113.9")) == "203.0.113.9"
    assert get_client_ip(_request("172.31.240.11", "203.0.113.10")) == "172.31.240.11"
