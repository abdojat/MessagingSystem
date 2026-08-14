import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[3] / "worker"))

from app.api.routes.auth import _enforce_auth_rate_limits, login
from app.core.config import Settings
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.core.security import create_refresh_token
from app.core.utils import utcnow
from app.db.models import (
    BrokerBindingState,
    Channel,
    ChannelMembership,
    Event,
    MembershipRole,
    MessageAttachment,
    Outbox,
    OutboxStatus,
    Upload,
)
from app.schemas.auth import (
    AUTH_IDENTITY_MAX_LENGTH,
    AUTH_PASSWORD_MAX_LENGTH,
    AUTH_REFRESH_TOKEN_MAX_LENGTH,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.schemas.channels import ChannelCreateRequest, JoinRequest
from app.schemas.messages import PublishMessageRequest, UploadCreateRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from worker_app.core.config import Settings as WorkerSettings
from worker_app import outbox_runner


SECURE_JWT_SECRET = "phase7-secure-jwt-secret-with-enough-diversity-0123456789"
SECURE_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class _NoDirectAmqp:
    async def channel(self):
        raise AssertionError("topology work must remain in the durable outbox")


class _RateRedis:
    def __init__(self) -> None:
        self.keys: list[str] = []

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        self.keys.append(key)
        return [1, window_seconds]


class _BlockingFailQueue:
    def __init__(self) -> None:
        self.projection_locked = asyncio.Event()
        self.fail_now = asyncio.Event()

    async def bind(self, exchange, routing_key: str) -> None:
        self.projection_locked.set()
        await self.fail_now.wait()
        raise ConnectionError("rabbitmq unavailable")

    async def unbind(self, exchange, routing_key: str) -> None:
        self.projection_locked.set()
        await self.fail_now.wait()
        raise ConnectionError("rabbitmq unavailable")


class _BrokerChannel:
    def __init__(self, queue: _BlockingFailQueue) -> None:
        self.queue = queue
        self.exchange = None

    async def declare_exchange(self, *args, **kwargs):
        return self.exchange

    async def declare_queue(self, name: str, **kwargs):
        return self.queue


class _BrokerExchange:
    def __init__(self, queue: _BlockingFailQueue) -> None:
        self.channel = _BrokerChannel(queue)
        self.channel.exchange = self


class _DeadLetterExchange:
    async def publish(self, message, routing_key: str) -> None:
        return None


def _worker_settings() -> WorkerSettings:
    return WorkerSettings(
        outbox_max_attempts=5,
        outbox_initial_retry_delay_seconds=1,
        outbox_retry_backoff_multiplier=2,
        outbox_max_retry_delay_seconds=10,
    )


def _session_maker(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


def _request(path: str = "/v1/auth/login") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "extensions": {},
        }
    )


async def _register(db: AsyncSession, username: str, password: str = "Password123!"):
    return await AuthService.register(
        db,
        RegisterRequest(username=username, email=f"{username}@example.com", password=password),
    )


async def _channel(db: AsyncSession, owner, name: str):
    return await ChannelService.create_channel(
        db,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode="open"),
        _NoDirectAmqp(),
    )


# P5V-04 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_login_and_maximum_registered_password_remain_accepted(db_session) -> None:
    password = "Aa1!" + "P" * (AUTH_PASSWORD_MAX_LENGTH - 4)
    user = await _register(db_session, "phase7_login_user", password)
    pair = await AuthService.login(
        db_session,
        LoginRequest(username_or_email=user.username, password=password),
        user_agent="phase7-test",
        ip="127.0.0.1",
        refresh_ttl_days=14,
    )
    assert pair.access_token
    assert RefreshRequest(refresh_token=pair.refresh_token).refresh_token == pair.refresh_token
    assert len(pair.refresh_token) < AUTH_REFRESH_TOKEN_MAX_LENGTH


def test_authentication_fields_reject_oversized_values() -> None:
    LoginRequest(username_or_email="a" * AUTH_IDENTITY_MAX_LENGTH, password="p" * AUTH_PASSWORD_MAX_LENGTH)
    with pytest.raises(ValidationError):
        LoginRequest(username_or_email="a" * (AUTH_IDENTITY_MAX_LENGTH + 1), password="password")
    with pytest.raises(ValidationError):
        LoginRequest(username_or_email="valid", password="p" * (AUTH_PASSWORD_MAX_LENGTH + 1))
    with pytest.raises(ValidationError):
        RefreshRequest(refresh_token="r" * (AUTH_REFRESH_TOKEN_MAX_LENGTH + 1))
    with pytest.raises(ValidationError):
        LogoutRequest(refresh_token="r" * (AUTH_REFRESH_TOKEN_MAX_LENGTH + 1))


def test_current_refresh_jwt_has_documented_headroom() -> None:
    token = create_refresh_token(uuid4(), uuid4(), utcnow() + timedelta(days=14))
    assert len(token) < AUTH_REFRESH_TOKEN_MAX_LENGTH
    assert RefreshRequest(refresh_token=token).refresh_token == token
    assert LogoutRequest(refresh_token=token).refresh_token == token


@pytest.mark.asyncio
async def test_failed_login_audit_and_rate_limit_identity_are_bounded(db_session) -> None:
    identity = "A" * AUTH_IDENTITY_MAX_LENGTH
    redis = _RateRedis()
    with pytest.raises(HTTPException) as error:
        await login(
            LoginRequest(username_or_email=identity, password="not-the-password"),
            db_session,
            _request(),
            redis,
        )
    assert error.value.status_code == 401

    event = (
        await db_session.execute(select(Event).where(Event.event_type == "security.login_failed"))
    ).scalar_one()
    assert "identity" not in event.payload
    assert len(event.payload["identity_prefix"]) <= 32
    assert len(event.payload["identity_sha256"]) == 64
    identity_keys = [key for key in redis.keys if ":identity:" in key]
    assert len(identity_keys) == 1
    assert len(identity_keys[0]) < 128
    assert identity.lower() not in identity_keys[0]


@pytest.mark.asyncio
async def test_auth_rate_limit_key_is_fixed_size_at_schema_boundary() -> None:
    redis = _RateRedis()
    await _enforce_auth_rate_limits(redis, "login", "127.0.0.1", "Z" * AUTH_IDENTITY_MAX_LENGTH)
    identity_key = next(key for key in redis.keys if ":identity:" in key)
    assert len(identity_key.rsplit(":", 1)[-1]) == 64


async def _run_body_limit(path: str, chunks: list[bytes], *, declared_length: int | None = None):
    received_chunks: list[bytes] = []
    sent: list[dict] = []
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def inner(scope, receive_inner, send_inner):
        while True:
            message = await receive_inner()
            if message["type"] != "http.request":
                break
            received_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send_inner({"type": "http.response.start", "status": 204, "headers": []})
        await send_inner({"type": "http.response.body", "body": b"", "more_body": False})

    headers = [] if declared_length is None else [(b"content-length", str(declared_length).encode("ascii"))]
    scope = {
        "type": "http",
        "method": "PUT" if "/uploads/" in path else "POST",
        "path": path,
        "headers": headers,
    }
    await RequestBodyLimitMiddleware(inner, max_body_bytes=24)(scope, receive, send)
    return received_chunks, sent


@pytest.mark.asyncio
async def test_oversized_raw_json_is_rejected_by_declared_and_streamed_boundaries() -> None:
    received, sent = await _run_body_limit("/v1/auth/login", [b"{}"], declared_length=25)
    assert received == []
    assert sent[0]["status"] == 413

    received, sent = await _run_body_limit("/v1/auth/login", [b"a" * 16, b"b" * 16])
    assert received == [b"a" * 16]
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
async def test_streaming_upload_path_is_exempt_and_not_prebuffered() -> None:
    file_id = uuid4()
    chunks = [b"first", b"second", b"third"]
    received, sent = await _run_body_limit(
        f"/v1/uploads/{file_id}/content",
        chunks,
        declared_length=sum(map(len, chunks)),
    )
    assert received == chunks
    assert sent[0]["status"] == 204


# AV-10 ---------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["dev", "development", "local", "test"])
def test_explicit_development_environments_allow_placeholders(environment: str) -> None:
    settings = Settings(
        _env_file=None,
        environment=f"  {environment.upper()}  ",
        jwt_secret="change-me",
        message_encryption_enabled=True,
        message_encryption_key="",
    )
    assert settings.environment == environment


@pytest.mark.parametrize("environment", ["production", "staging", "live", "release", "prod-eu", "foo"])
def test_production_and_unknown_environments_reject_placeholders(environment: str) -> None:
    with pytest.raises(ValidationError, match="known development placeholder"):
        Settings(
            _env_file=None,
            environment=environment,
            jwt_secret="change-me",
            message_encryption_enabled=False,
        )


def test_secure_unknown_environment_is_treated_as_production_like() -> None:
    settings = Settings(
        _env_file=None,
        environment=" release ",
        jwt_secret=SECURE_JWT_SECRET,
        message_encryption_enabled=True,
        message_encryption_key=SECURE_FERNET_KEY,
    )
    assert settings.environment == "release"


# AV-09 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attachment_composite_fk_allows_valid_publish_and_rejects_false_channel(db_session) -> None:
    owner = await _register(db_session, "phase7_attachment_owner")
    member = await _register(db_session, "phase7_attachment_member")
    outsider = await _register(db_session, "phase7_attachment_outsider")
    channel_a = await _channel(db_session, owner, "Phase 7 Attachment A")
    channel_b = await _channel(db_session, owner, "Phase 7 Attachment B")
    owner_id = owner.id
    member_id = member.id
    outsider_id = outsider.id
    channel_a_id = channel_a.id
    channel_b_id = channel_b.id
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel_a.id, member.id, JoinRequest())

    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="valid.txt", content_type="text/plain", size_bytes=1),
    )
    upload.public_url = f"/v1/uploads/{upload.id}/content"
    second_upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="invalid.txt", content_type="text/plain", size_bytes=1),
    )
    second_upload.public_url = f"/v1/uploads/{second_upload.id}/content"
    await db_session.commit()
    upload_id = upload.id
    second_upload_id = second_upload.id
    message = await MessageService.publish_message(
        db_session,
        channel_a.id,
        owner.id,
        PublishMessageRequest(content_text="attachment integrity", attachments=[{"file_id": upload.id}]),
    )

    relation = await db_session.get(MessageAttachment, {"message_id": message.id, "upload_id": upload_id})
    assert relation is not None and relation.channel_id == channel_a.id
    assert await MessageService.can_access_upload(db_session, member_id, upload_id) is True
    assert await MessageService.can_access_upload(db_session, outsider_id, upload_id) is False

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO message_attachments (message_id, upload_id, channel_id) "
                "VALUES (:message_id, :upload_id, :channel_id)"
            ),
            {"message_id": message.id, "upload_id": second_upload_id, "channel_id": channel_b_id},
        )
        await db_session.commit()
    await db_session.rollback()

    await ChannelService.delete_channel(db_session, channel_a_id, owner_id, _NoDirectAmqp())
    assert await MessageService.can_access_upload(db_session, member_id, upload_id) is False


# P5V-03 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_historical_advisory_binding_cycle_completes_without_deadlock(db_session) -> None:
    owner = await _register(db_session, "phase7_cycle_owner")
    channel = await _channel(db_session, owner, "Phase 7 Historical Cycle")
    owner_id = owner.id
    channel_id = channel.id
    state = await db_session.get(BrokerBindingState, {"channel_id": channel_id, "user_id": owner_id})
    assert state is not None
    outbox = (
        await db_session.execute(
            select(Outbox).where(
                Outbox.channel_id == channel_id,
                Outbox.aggregate_type == "broker_binding",
                Outbox.status == OutboxStatus.pending,
            )
        )
    ).scalar_one()

    sessions = _session_maker(db_session)
    queue = _BlockingFailQueue()
    async with sessions() as event_tx, sessions() as worker_tx:
        await event_tx.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
            {"scope": f"channel:{channel_id}"},
        )
        worker_task = asyncio.create_task(
            outbox_runner.process_outbox_batch(
                worker_tx,
                _BrokerExchange(queue),
                _DeadLetterExchange(),
                _worker_settings(),
                limit=1,
            )
        )
        await asyncio.wait_for(queue.projection_locked.wait(), timeout=3)

        async def wait_for_projection_then_release_advisory() -> None:
            await event_tx.execute(
                select(BrokerBindingState)
                .where(BrokerBindingState.channel_id == channel_id, BrokerBindingState.user_id == owner_id)
                .with_for_update()
            )
            await event_tx.commit()

        application_task = asyncio.create_task(wait_for_projection_then_release_advisory())
        await asyncio.sleep(0.05)
        queue.fail_now.set()
        await asyncio.wait_for(application_task, timeout=5)
        await asyncio.wait_for(worker_task, timeout=5)

    await db_session.refresh(outbox)
    await db_session.refresh(state)
    assert outbox.status == OutboxStatus.retry_scheduled
    assert state.desired_bound is True
    assert state.reconciled_generation == 0
    diagnostic_count = await db_session.scalar(
        select(func.count(Event.id)).where(Event.event_type == "broker.retry_scheduled", Event.channel_id == channel_id)
    )
    assert diagnostic_count == 1


@pytest.mark.asyncio
async def test_channel_delete_and_member_mutation_serialize_without_deadlock(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase7_concurrency_owner")
    member = await _register(db_session, "phase7_concurrency_member")
    channel = await _channel(db_session, owner, "Phase 7 Channel Member Concurrency")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    owner_id = owner.id
    member_id = member.id
    channel_id = channel.id

    from app.services import channel_service as channel_service_module

    real_log_event = channel_service_module.log_event
    delete_has_all_locks = asyncio.Event()
    allow_delete_commit = asyncio.Event()

    async def pausing_log_event(db, event_type, payload, **kwargs):
        if event_type == "channel.deleted":
            delete_has_all_locks.set()
            await allow_delete_commit.wait()
        return await real_log_event(db, event_type, payload, **kwargs)

    monkeypatch.setattr(channel_service_module, "log_event", pausing_log_event)
    sessions = _session_maker(db_session)
    async with sessions() as delete_db, sessions() as member_db:
        delete_task = asyncio.create_task(
                ChannelService.delete_channel(delete_db, channel_id, owner_id, _NoDirectAmqp())
        )
        await asyncio.wait_for(delete_has_all_locks.wait(), timeout=3)

        async def remove_after_delete():
            try:
                await ChannelService.remove_member(
                    member_db,
                    _NoDirectAmqp(),
                    channel_id,
                    owner_id,
                    member_id,
                )
                return "removed"
            except Exception as exc:
                await member_db.rollback()
                return getattr(exc, "code", type(exc).__name__)

        member_task = asyncio.create_task(remove_after_delete())
        await asyncio.sleep(0.05)
        allow_delete_commit.set()
        delete_result, member_result = await asyncio.wait_for(
            asyncio.gather(delete_task, member_task),
            timeout=5,
        )
        assert delete_result is None
        assert member_result == "CHANNEL_NOT_FOUND"

    db_session.expire_all()
    deleted_channel = await db_session.get(Channel, channel_id)
    assert deleted_channel is not None and deleted_channel.deleted_at is not None


@pytest.mark.asyncio
async def test_worker_audit_failure_does_not_undo_retry_state(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase7_worker_audit_owner")
    channel = await _channel(db_session, owner, "Phase 7 Worker Audit Failure")
    outbox = (
        await db_session.execute(
            select(Outbox).where(
                Outbox.channel_id == channel.id,
                Outbox.aggregate_type == "broker_binding",
                Outbox.status == OutboxStatus.pending,
            )
        )
    ).scalar_one()

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(outbox_runner, "_insert_delivery_event", fail_audit)
    queue = _BlockingFailQueue()
    queue.fail_now.set()
    processed = await outbox_runner.process_outbox_batch(
        db_session,
        _BrokerExchange(queue),
        _DeadLetterExchange(),
        _worker_settings(),
        limit=1,
    )
    await db_session.refresh(outbox)
    assert processed == 1
    assert outbox.status == OutboxStatus.retry_scheduled
    assert outbox.attempts == 1


@pytest.mark.asyncio
async def test_membership_event_failure_rolls_back_projection_and_authorization(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase7_rollback_owner")
    member = await _register(db_session, "phase7_rollback_member")
    channel = await _channel(db_session, owner, "Phase 7 Rollback Safety")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    owner_id = owner.id
    member_id = member.id
    channel_id = channel.id
    state = await db_session.get(BrokerBindingState, {"channel_id": channel_id, "user_id": member_id})
    assert state is not None
    original_generation = int(state.generation)
    original_outbox_count = int(await db_session.scalar(select(func.count(Outbox.id))) or 0)

    async def fail_event(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr("app.services.channel_service.log_event", fail_event)
    with pytest.raises(RuntimeError, match="event write failed"):
        await ChannelService.remove_member(
            db_session,
            _NoDirectAmqp(),
            channel_id,
            owner_id,
            member_id,
        )
    await db_session.rollback()

    membership = await db_session.get(ChannelMembership, {"channel_id": channel_id, "user_id": member_id})
    await db_session.refresh(state)
    assert membership is not None and membership.role == MembershipRole.member
    assert state.desired_bound is True
    assert int(state.generation) == original_generation
    assert int(await db_session.scalar(select(func.count(Outbox.id))) or 0) == original_outbox_count
