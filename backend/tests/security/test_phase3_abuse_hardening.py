import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, select, update

sys.path.append(str(Path(__file__).resolve().parents[3] / "worker"))

from app.api.routes.messages import _to_message_responses_with_reactions
from app.core.config import get_settings
from app.core.encryption import encrypt_message
from app.core.errors import AppError
from app.db.models import (
    BrokerBindingState,
    ChannelMembership,
    ContentType,
    MembershipRole,
    Message,
    MessageAttachment,
    MessageReaction,
    Outbox,
    OutboxStatus,
)
from app.mq.publisher import ensure_user_queue, user_queue_arguments
from app.realtime.protocol import WSResumePayload, WSSubscribePayload, WSSyncPayload, WSUnsubscribePayload
from app.realtime.ws_manager import WSManager
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, InviteRequest, JoinRequest
from app.schemas.messages import (
    MessagePatchRequest,
    PublishMessageRequest,
    ReactionRequest,
    SeenRequest,
    SyncChannelCursor,
    SyncRequest,
    UploadCreateRequest,
)
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from app.services.rate_limit_service import RateLimitService, enforce_rate_limit
from worker_app.amqp_consumer_runner import publish_redis_with_backoff, redis_requeue_delay
from worker_app.core.config import Settings as WorkerSettings
from worker_app.mq.topology import user_queue_arguments as worker_user_queue_arguments
from worker_app.outbox_runner import _apply_broker_binding, process_outbox_batch


class _UnusedAmqp:
    async def channel(self):
        raise AssertionError("membership operations must not call RabbitMQ after commit")


class _MemoryRateRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = {}

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        if self.fail:
            raise ConnectionError("redis unavailable")
        assert numkeys == 1
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], window_seconds]

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        if self.fail:
            raise ConnectionError("redis unavailable")
        return True

    async def ttl(self, key: str) -> int:
        return 60


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _BrokerQueue:
    def __init__(self, *, fail_unbind: bool = False) -> None:
        self.bindings: list[str] = []
        self.unbindings: list[str] = []
        self.fail_unbind = fail_unbind

    async def bind(self, exchange, routing_key: str) -> None:
        self.bindings.append(routing_key)

    async def unbind(self, exchange, routing_key: str) -> None:
        self.unbindings.append(routing_key)
        if self.fail_unbind:
            raise ConnectionError("rabbitmq unavailable")


class _BrokerChannel:
    def __init__(self, queue: _BrokerQueue) -> None:
        self.queue = queue
        self.exchange = None
        self.declarations: list[dict] = []

    async def declare_exchange(self, *args, **kwargs):
        return self.exchange

    async def declare_queue(self, name: str, **kwargs):
        self.declarations.append({"name": name, **kwargs})
        return self.queue


class _BrokerExchange:
    def __init__(self, queue: _BrokerQueue | None = None, *, publish_error: Exception | None = None) -> None:
        self.queue = queue or _BrokerQueue()
        self.channel = _BrokerChannel(self.queue)
        self.channel.exchange = self
        self.publish_error = publish_error
        self.published: list[str] = []

    async def publish(self, message, routing_key: str) -> None:
        if self.publish_error:
            raise self.publish_error
        self.published.append(routing_key)


class _FailingPublishRedis:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, channel: str, data: str) -> int:
        self.calls += 1
        raise ConnectionError("redis unavailable")


async def _register(db, username: str):
    return await AuthService.register(
        db,
        RegisterRequest(username=username, email=f"{username}@example.com", password="Password123!"),
    )


async def _channel(db, owner, name: str = "Phase Three"):
    return await ChannelService.create_channel(
        db,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode="open"),
        _UnusedAmqp(),
    )


async def _outbox_count(db, *, outbox_type: str) -> int:
    rows = await db.execute(select(Outbox).where(Outbox.type == outbox_type))
    return len(rows.scalars().all())


@pytest.mark.asyncio
async def test_redis_backed_rate_limit_enforces_threshold() -> None:
    redis = _MemoryRateRedis()
    assert (await RateLimitService.hit(redis, "rl:test", 2, 60)).backend == "redis"
    assert (await RateLimitService.hit(redis, "rl:test", 2, 60)).retry_after_seconds is None
    result = await RateLimitService.hit(redis, "rl:test", 2, 60)
    assert result.retry_after_seconds == 60


@pytest.mark.asyncio
async def test_redis_failure_uses_bounded_local_fallback_for_sensitive_policy() -> None:
    redis = _MemoryRateRedis(fail=True)
    await enforce_rate_limit(redis, "rl:fallback", limit=1, window_seconds=60)
    with pytest.raises(HTTPException) as error:
        await enforce_rate_limit(redis, "rl:fallback", limit=1, window_seconds=60)
    assert error.value.status_code == 429


@pytest.mark.asyncio
async def test_low_risk_failure_policy_can_remain_available() -> None:
    result = await RateLimitService.hit(
        _MemoryRateRedis(fail=True),
        "rl:ordinary-read",
        1,
        60,
        failure_policy="allow",
    )
    assert result.backend == "bypassed"
    assert result.retry_after_seconds is None


def test_message_text_and_edit_limits_validate_utf8_bytes(monkeypatch) -> None:
    monkeypatch.setenv("MESSAGE_TEXT_MAX_BYTES", "1024")
    get_settings.cache_clear()
    assert PublishMessageRequest(content_text="a" * 1024).content_text == "a" * 1024
    assert MessagePatchRequest(content_text="ordinary").content_text == "ordinary"
    with pytest.raises(ValidationError, match="UTF-8 bytes"):
        PublishMessageRequest(content_text="a" * 1025)
    with pytest.raises(ValidationError, match="UTF-8 bytes"):
        MessagePatchRequest(content_text="🙂" * 257)


def test_structured_json_size_and_depth_are_bounded(monkeypatch) -> None:
    monkeypatch.setenv("MESSAGE_JSON_MAX_BYTES", "1024")
    monkeypatch.setenv("MESSAGE_JSON_MAX_DEPTH", "4")
    get_settings.cache_clear()
    assert PublishMessageRequest(content_json={"kind": "ordinary"}).content_json == {"kind": "ordinary"}
    with pytest.raises(ValidationError, match="serialized bytes"):
        PublishMessageRequest(content_json={"value": "x" * 1024})
    with pytest.raises(ValidationError, match="nesting depth"):
        PublishMessageRequest(content_json={"a": {"b": {"c": {"d": 1}}}})


def test_rest_and_websocket_channel_arrays_accept_boundary_and_reject_oversize() -> None:
    ids = [uuid4() for _ in range(101)]
    assert len(SyncRequest(channels=[SyncChannelCursor(channel_id=value) for value in ids[:100]]).channels) == 100
    assert len(WSSubscribePayload(channel_ids=ids[:100]).channel_ids) == 100
    assert len(WSUnsubscribePayload(channel_ids=ids[:100]).channel_ids) == 100
    assert len(WSResumePayload(channels=[{"channel_id": value} for value in ids[:100]]).channels) == 100
    assert len(WSSyncPayload(states=[{"channel_id": value} for value in ids[:100]]).states) == 100
    for model, payload in (
        (SyncRequest, {"channels": [{"channel_id": value} for value in ids]}),
        (WSSubscribePayload, {"channel_ids": ids}),
        (WSUnsubscribePayload, {"channel_ids": ids}),
        (WSResumePayload, {"channels": [{"channel_id": value} for value in ids]}),
        (WSSyncPayload, {"states": [{"channel_id": value} for value in ids]}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.asyncio
async def test_websocket_oversized_subscribe_is_rejected_before_database_work() -> None:
    manager = WSManager(None, None, None)
    websocket = _RecordingWebSocket()
    await manager._handle_subscribe(
        websocket,
        uuid4(),
        {"channel_ids": [str(uuid4()) for _ in range(101)]},
        uuid4(),
    )
    assert websocket.sent[-1]["payload"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_seen_advances_once_and_identical_or_lower_markers_do_not_amplify(db_session) -> None:
    owner = await _register(db_session, "seen_phase3")
    channel = await _channel(db_session, owner, "Seen Idempotency")
    first = await MessageService.publish_message(db_session, channel.id, owner.id, PublishMessageRequest(content_text="one"))
    second = await MessageService.publish_message(db_session, channel.id, owner.id, PublishMessageRequest(content_text="two"))

    state = await MessageService.mark_seen(db_session, channel.id, owner.id, SeenRequest(last_seen_seq_id=first.seq_id))
    assert state.last_seen_seq_id == first.seq_id
    assert await _outbox_count(db_session, outbox_type="seen") == 1

    await MessageService.mark_seen(db_session, channel.id, owner.id, SeenRequest(last_seen_seq_id=first.seq_id))
    await MessageService.mark_seen(db_session, channel.id, owner.id, SeenRequest(last_seen_seq_id=0))
    assert await _outbox_count(db_session, outbox_type="seen") == 1

    state = await MessageService.mark_seen(db_session, channel.id, owner.id, SeenRequest(last_seen_seq_id=second.seq_id))
    assert state.last_seen_seq_id == second.seq_id
    assert await _outbox_count(db_session, outbox_type="seen") == 2


@pytest.mark.asyncio
async def test_reaction_add_remove_are_idempotent_and_validate_values(db_session) -> None:
    owner = await _register(db_session, "react_phase3")
    channel = await _channel(db_session, owner, "Reaction Idempotency")
    message = await MessageService.publish_message(db_session, channel.id, owner.id, PublishMessageRequest(content_text="react"))

    assert ReactionRequest(emoji="👍").emoji == "👍"
    with pytest.raises(ValidationError):
        ReactionRequest(emoji="arbitrary-reaction-string")

    await MessageService.add_reaction(db_session, channel.id, message.id, owner.id, "👍")
    await MessageService.add_reaction(db_session, channel.id, message.id, owner.id, "👍")
    assert await _outbox_count(db_session, outbox_type="reaction_updated") == 1

    await MessageService.remove_reaction(db_session, channel.id, message.id, owner.id, "👍")
    await MessageService.remove_reaction(db_session, channel.id, message.id, owner.id, "👍")
    assert await _outbox_count(db_session, outbox_type="reaction_updated") == 2


@pytest.mark.asyncio
async def test_message_response_reaction_queries_are_constant(db_session) -> None:
    owner = await _register(db_session, "query_phase3")
    channel = await _channel(db_session, owner, "Reaction Query Batch")
    messages = []
    for seq_id in range(1, 26):
        message = Message(
            channel_id=channel.id,
            sender_user_id=owner.id,
            seq_id=seq_id,
            content_type=ContentType.text,
            content_text=encrypt_message(f"message {seq_id}"),
        )
        db_session.add(message)
        messages.append(message)
    await db_session.flush()
    for message in messages:
        db_session.add(
            MessageReaction(channel_id=channel.id, message_id=message.id, user_id=owner.id, emoji="👍")
        )
    await db_session.commit()

    statements: list[str] = []

    def record_query(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    sync_engine = db_session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", record_query)
    try:
        responses = await _to_message_responses_with_reactions(db_session, owner.id, messages)
    finally:
        event.remove(sync_engine, "before_cursor_execute", record_query)

    assert len(responses) == 25
    reaction_queries = [statement for statement in statements if "message_reactions" in statement.lower()]
    assert len(reaction_queries) == 2
    assert len(statements) == 3  # one sender query plus two reaction queries


@pytest.mark.asyncio
async def test_attachment_access_uses_normalized_relation_for_member_and_blocks_outsider(db_session) -> None:
    owner = await _register(db_session, "upload_owner3")
    member = await _register(db_session, "upload_member3")
    outsider = await _register(db_session, "upload_outsider3")
    channel = await _channel(db_session, owner, "Indexed Attachments")
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=member.id,
            role=MembershipRole.member,
            approved_at=channel.created_at,
            created_by_user_id=owner.id,
        )
    )
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="proof.txt", content_type="text/plain", size_bytes=5),
    )
    upload.public_url = f"/v1/uploads/{upload.id}/content"
    await db_session.commit()
    message = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="attached", attachments=[{"file_id": upload.id}]),
    )

    relation = await db_session.get(MessageAttachment, {"message_id": message.id, "upload_id": upload.id})
    assert relation is not None
    assert await MessageService.can_access_upload(db_session, owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, outsider.id, upload.id) is False


@pytest.mark.asyncio
async def test_attachment_lookup_does_not_scan_message_attachment_json(db_session) -> None:
    owner = await _register(db_session, "lookup_owner3")
    member = await _register(db_session, "lookup_member3")
    channel = await _channel(db_session, owner, "Lookup Plan")
    db_session.add(
        ChannelMembership(channel_id=channel.id, user_id=member.id, role=MembershipRole.member, approved_at=channel.created_at)
    )
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="lookup.txt", content_type="text/plain", size_bytes=1),
    )
    upload.public_url = f"/v1/uploads/{upload.id}/content"
    await db_session.commit()
    await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="lookup", attachments=[{"file_id": upload.id}]),
    )

    statements: list[str] = []

    def record_query(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    sync_engine = db_session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", record_query)
    try:
        assert await MessageService.can_access_upload(db_session, member.id, upload.id) is True
    finally:
        event.remove(sync_engine, "before_cursor_execute", record_query)
    assert any("message_attachments" in statement for statement in statements)
    assert not any("messages.attachments is not null" in statement for statement in statements)


@pytest.mark.asyncio
async def test_channel_invite_and_upload_quota_boundaries(db_session, monkeypatch) -> None:
    monkeypatch.setenv("MAX_CHANNELS_OWNED_PER_USER", "1")
    monkeypatch.setenv("MAX_ACTIVE_INVITES_PER_USER", "1")
    monkeypatch.setenv("MAX_UPLOADS_PER_USER_PER_DAY", "1")
    get_settings.cache_clear()
    owner = await _register(db_session, "quota_phase3")
    channel = await _channel(db_session, owner, "Only Channel")
    with pytest.raises(AppError, match="owned channel quota"):
        await _channel(db_session, owner, "One Too Many")

    await ChannelService.create_invite(db_session, channel.id, owner.id, InviteRequest(is_generic=True))
    with pytest.raises(AppError, match="active invite quota"):
        await ChannelService.create_invite(db_session, channel.id, owner.id, InviteRequest(is_generic=True))

    await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="one.txt", content_type="text/plain", size_bytes=1),
    )
    with pytest.raises(AppError, match="daily upload quota"):
        await MessageService.create_upload(
            db_session,
            owner.id,
            UploadCreateRequest(filename="two.txt", content_type="text/plain", size_bytes=1),
        )


@pytest.mark.asyncio
async def test_websocket_concurrency_quota_rejects_one_over_boundary(monkeypatch) -> None:
    monkeypatch.setenv("MAX_WEBSOCKET_CONNECTIONS_PER_USER", "1")
    get_settings.cache_clear()
    user_id = uuid4()
    manager = WSManager(None, None, None)
    manager._connections[user_id] = {1: object()}
    with pytest.raises(AppError) as error:
        await manager.connect(object(), user_id, "quota_socket", uuid4())
    assert error.value.code == "WEBSOCKET_QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_user_queue_declaration_is_bounded_and_worker_matches_backend() -> None:
    queue = _BrokerQueue()
    channel = _BrokerChannel(queue)
    exchange = _BrokerExchange(queue)
    channel.exchange = exchange
    await ensure_user_queue(channel, "queue_user")
    declaration = channel.declarations[-1]
    assert declaration["durable"] is True
    assert declaration["auto_delete"] is False
    assert declaration["arguments"] == user_queue_arguments()
    assert declaration["arguments"]["x-expires"] > 0
    assert declaration["arguments"]["x-message-ttl"] > 0
    assert declaration["arguments"]["x-max-length"] > 0
    assert worker_user_queue_arguments(WorkerSettings()) == declaration["arguments"]


@pytest.mark.asyncio
async def test_membership_changes_generate_durable_bind_and_unbind_commands(db_session) -> None:
    owner = await _register(db_session, "binding_owner3")
    member = await _register(db_session, "binding_member3")
    channel = await _channel(db_session, owner, "Durable Bindings")
    status, membership, _ = await ChannelService.join_channel(
        db_session,
        _UnusedAmqp(),
        channel.id,
        member.id,
        JoinRequest(),
    )
    assert status == "joined"
    bind_rows = await db_session.execute(
        select(Outbox).where(
            Outbox.aggregate_type == "broker_binding",
            Outbox.aggregate_id == member.id,
            Outbox.type == "broker_binding.reconcile",
        )
    )
    assert bind_rows.scalar_one_or_none() is not None
    state = await db_session.get(BrokerBindingState, {"channel_id": channel.id, "user_id": member.id})
    assert state is not None and state.desired_bound is True

    await ChannelService.remove_member(db_session, _UnusedAmqp(), channel.id, owner.id, member.id)
    unbind_rows = await db_session.execute(
        select(Outbox).where(
            Outbox.aggregate_type == "broker_binding",
            Outbox.aggregate_id == member.id,
            Outbox.type == "broker_binding.reconcile",
        )
    )
    assert len(unbind_rows.scalars().all()) == 2
    await db_session.refresh(state)
    assert state.desired_bound is False
    assert await ChannelService.get_membership(db_session, channel.id, member.id) is None


@pytest.mark.asyncio
async def test_failed_broker_unbind_is_retryable_without_undoing_membership(db_session) -> None:
    owner = await _register(db_session, "retry_owner3")
    member = await _register(db_session, "retry_member3")
    channel = await _channel(db_session, owner, "Retry Binding")
    await ChannelService.join_channel(db_session, _UnusedAmqp(), channel.id, member.id, JoinRequest())
    await db_session.execute(update(Outbox).values(status=OutboxStatus.published))
    await db_session.commit()

    await ChannelService.remove_member(db_session, _UnusedAmqp(), channel.id, owner.id, member.id)
    binding_rows = (
        await db_session.execute(
            select(Outbox).where(Outbox.aggregate_id == member.id, Outbox.type == "broker_binding.reconcile")
        )
    ).scalars().all()
    unbind = max(binding_rows, key=lambda row: int(row.payload["generation"]))
    await db_session.execute(
        update(Outbox)
        .where(Outbox.id != unbind.id, Outbox.status == OutboxStatus.pending)
        .values(status=OutboxStatus.published)
    )
    await db_session.commit()

    exchange = _BrokerExchange(_BrokerQueue(fail_unbind=True))
    dead_letter = _BrokerExchange()
    settings = WorkerSettings(outbox_initial_retry_delay_seconds=1)
    assert await process_outbox_batch(db_session, exchange, dead_letter, settings) == 1
    await db_session.refresh(unbind)
    assert unbind.status == OutboxStatus.retry_scheduled
    assert unbind.attempts == 1
    assert await ChannelService.get_membership(db_session, channel.id, member.id) is None


@pytest.mark.asyncio
async def test_duplicate_broker_binding_processing_is_safe(db_session) -> None:
    owner = await _register(db_session, "duplicate_user")
    channel = await _channel(db_session, owner, "Duplicate Channel")
    row = (
        await db_session.execute(
            select(Outbox).where(
                Outbox.aggregate_id == owner.id,
                Outbox.type == "broker_binding.reconcile",
            )
        )
    ).scalar_one()
    exchange = _BrokerExchange()
    settings = WorkerSettings()
    await _apply_broker_binding(db_session, exchange, row.payload, settings)
    await db_session.commit()
    await _apply_broker_binding(db_session, exchange, row.payload, settings)
    await db_session.commit()
    assert exchange.queue.bindings.count(f"channel.{channel.channel_slug}") == 2


@pytest.mark.asyncio
async def test_redis_fanout_failure_has_bounded_attempts_and_backoff(monkeypatch) -> None:
    redis = _FailingPublishRedis()
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    settings = WorkerSettings(
        redis_fanout_max_attempts=3,
        redis_fanout_initial_retry_delay_seconds=0.1,
        redis_fanout_max_retry_delay_seconds=1.0,
    )
    with pytest.raises(ConnectionError):
        await publish_redis_with_backoff(redis, "rt.user.phase3", "payload", settings)
    assert redis.calls == 3
    assert delays == [0.1, 0.2]
    assert redis_requeue_delay(10, settings) == 1.0
