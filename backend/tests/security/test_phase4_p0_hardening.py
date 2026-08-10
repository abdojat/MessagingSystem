import asyncio
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[3] / "worker"))

from app.api.routes.messages import get_upload_content
from app.core.encryption import encrypt_message
from app.core.utils import utcnow
from app.db.models import (
    BrokerBindingState,
    Channel,
    ChannelJoinMode,
    ChannelMembership,
    ChannelVisibility,
    ContentType,
    MembershipRole,
    Message,
    MessageAttachment,
    Outbox,
    Upload,
)
from app.realtime.ws_manager import WSManager
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest, JoinRequest
from app.schemas.messages import SyncChannelCursor, SyncRequest
from app.services.admin_service import AdminService
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.download_service import DownloadConcurrencyLimiter, LeasedFileResponse, protected_download_limiter
from app.services.message_service import MessageService
from worker_app.core.config import Settings as WorkerSettings
from worker_app.outbox_runner import _apply_broker_binding


class _NoDirectAmqp:
    async def channel(self):
        raise AssertionError("topology changes must be handled by versioned desired-state outbox rows")


class _BrokerQueue:
    def __init__(self) -> None:
        self.effective_bindings: set[str] = set()
        self.bind_calls: list[str] = []
        self.unbind_calls: list[str] = []

    async def bind(self, exchange, routing_key: str) -> None:
        self.bind_calls.append(routing_key)
        self.effective_bindings.add(routing_key)

    async def unbind(self, exchange, routing_key: str) -> None:
        self.unbind_calls.append(routing_key)
        self.effective_bindings.discard(routing_key)

    @property
    def channel_bindings(self) -> set[str]:
        return {routing_key for routing_key in self.effective_bindings if routing_key.startswith("channel.")}


class _BrokerChannel:
    def __init__(self, queue: _BrokerQueue) -> None:
        self.queue = queue
        self.exchange = None

    async def declare_exchange(self, *args, **kwargs):
        return self.exchange

    async def declare_queue(self, name: str, **kwargs):
        return self.queue


class _BrokerExchange:
    def __init__(self) -> None:
        self.queue = _BrokerQueue()
        self.channel = _BrokerChannel(self.queue)
        self.channel.exchange = self


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _RateRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 60


async def _register(db: AsyncSession, username: str):
    return await AuthService.register(
        db,
        RegisterRequest(username=username, email=f"{username}@example.com", password="Password123!"),
    )


async def _channel(db: AsyncSession, owner, name: str):
    return await ChannelService.create_channel(
        db,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode="open"),
        _NoDirectAmqp(),
    )


async def _binding_payloads(db: AsyncSession, channel_id: UUID, user_id: UUID) -> list[dict]:
    rows = await db.execute(
        select(Outbox.payload).where(
            Outbox.channel_id == channel_id,
            Outbox.aggregate_id == user_id,
            Outbox.type == "broker_binding.reconcile",
        )
    )
    return sorted(rows.scalars().all(), key=lambda payload: int(payload["generation"]))


async def _insert_messages(db: AsyncSession, channel_id: UUID, sender_id: UUID, count: int) -> None:
    encrypted = encrypt_message("bounded sync payload")
    await db.execute(
        text(
            """
            INSERT INTO messages (
                id, channel_id, sender_user_id, seq_id, content_type,
                content_text, is_pinned, created_at, updated_at
            )
            SELECT gen_random_uuid(),
                   :channel_id,
                   :sender_id,
                   seq_id,
                   'text'::content_type,
                   :content_text,
                   false,
                   now() + (seq_id * interval '1 microsecond'),
                   now() + (seq_id * interval '1 microsecond')
            FROM generate_series(1, :count) AS seq_id
            """
        ),
        {
            "channel_id": channel_id,
            "sender_id": sender_id,
            "content_text": encrypted,
            "count": count,
        },
    )
    channel = await db.get(Channel, channel_id)
    assert channel is not None
    channel.last_seq_id = count
    await db.commit()


def _http_scope() -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "http",
        "method": "GET",
        "path": "/v1/uploads/content",
        "raw_path": b"/v1/uploads/content",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "extensions": {},
    }


async def _receive_request() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_old_bind_generation_cannot_beat_newer_unbind(db_session) -> None:
    owner = await _register(db_session, "phase4_bind_owner")
    member = await _register(db_session, "phase4_bind_member")
    channel = await _channel(db_session, owner, "Phase4 stale bind")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    old_bind = (await _binding_payloads(db_session, channel.id, member.id))[-1]

    await ChannelService.remove_member(db_session, _NoDirectAmqp(), channel.id, owner.id, member.id)
    newer_unbind = (await _binding_payloads(db_session, channel.id, member.id))[-1]
    assert int(newer_unbind["generation"]) > int(old_bind["generation"])

    exchange = _BrokerExchange()
    assert await _apply_broker_binding(db_session, exchange, newer_unbind, WorkerSettings()) == "applied_unbound"
    await db_session.commit()
    assert await _apply_broker_binding(db_session, exchange, old_bind, WorkerSettings()) == "stale_generation"
    await db_session.commit()
    assert exchange.queue.channel_bindings == set()


@pytest.mark.asyncio
async def test_old_unbind_generation_cannot_beat_newer_rejoin(db_session) -> None:
    owner = await _register(db_session, "phase4_rejoin_owner")
    member = await _register(db_session, "phase4_rejoin_member")
    channel = await _channel(db_session, owner, "Phase4 stale unbind")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    await ChannelService.remove_member(db_session, _NoDirectAmqp(), channel.id, owner.id, member.id)
    old_unbind = (await _binding_payloads(db_session, channel.id, member.id))[-1]

    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    newer_bind = (await _binding_payloads(db_session, channel.id, member.id))[-1]
    assert int(newer_bind["generation"]) > int(old_unbind["generation"])

    exchange = _BrokerExchange()
    assert await _apply_broker_binding(db_session, exchange, newer_bind, WorkerSettings()) == "applied_bound"
    await db_session.commit()
    assert await _apply_broker_binding(db_session, exchange, old_unbind, WorkerSettings()) == "stale_generation"
    await db_session.commit()
    assert exchange.queue.channel_bindings == {f"channel.{channel.channel_slug}"}


@pytest.mark.asyncio
async def test_duplicate_current_generation_is_idempotent(db_session) -> None:
    owner = await _register(db_session, "phase4_duplicate_owner")
    channel = await _channel(db_session, owner, "Phase4 duplicate")
    payload = (await _binding_payloads(db_session, channel.id, owner.id))[-1]
    exchange = _BrokerExchange()

    assert await _apply_broker_binding(db_session, exchange, payload, WorkerSettings()) == "applied_bound"
    await db_session.commit()
    assert await _apply_broker_binding(db_session, exchange, payload, WorkerSettings()) == "applied_bound"
    await db_session.commit()
    assert exchange.queue.channel_bindings == {f"channel.{channel.channel_slug}"}


@pytest.mark.asyncio
async def test_worker_crash_after_rabbit_action_retries_full_projection_safely(db_session) -> None:
    owner = await _register(db_session, "phase4_crash_owner")
    channel = await _channel(db_session, owner, "Phase4 crash retry")
    payload = (await _binding_payloads(db_session, channel.id, owner.id))[-1]
    channel_id = channel.id
    owner_id = owner.id
    routing_key = f"channel.{channel.channel_slug}"
    exchange = _BrokerExchange()

    assert await _apply_broker_binding(db_session, exchange, payload, WorkerSettings()) == "applied_bound"
    assert exchange.queue.channel_bindings == {routing_key}
    await db_session.rollback()  # Rabbit succeeded; DB/outbox acknowledgement did not.

    assert await _apply_broker_binding(db_session, exchange, payload, WorkerSettings()) == "applied_bound"
    await db_session.commit()
    state = await db_session.get(BrokerBindingState, {"channel_id": channel_id, "user_id": owner_id})
    assert state is not None
    assert state.reconciled_generation == state.generation
    assert exchange.queue.channel_bindings == {routing_key}


@pytest.mark.asyncio
async def test_missed_membership_event_cannot_deliver_or_decrypt_post_removal_message(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase4_socket_owner")
    member = await _register(db_session, "phase4_socket_member")
    channel = await _channel(db_session, owner, "Phase4 socket removal")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    await db_session.refresh(channel)
    old_generation = int(channel.membership_generation)

    session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    manager = WSManager(session_factory, None, None)
    websocket = _RecordingWebSocket()
    channel_key = str(channel.id)
    manager._subscriptions[id(websocket)] = {channel_key}
    manager._subscription_generations[id(websocket)] = {channel_key: old_generation}
    manager._subscription_checked_at[id(websocket)] = {channel_key: time.monotonic()}

    decrypted = False

    def fail_if_decrypted(event: dict) -> dict:
        nonlocal decrypted
        decrypted = True
        return event

    monkeypatch.setattr(manager, "_decrypt_event_payload", fail_if_decrypted)
    await ChannelService.remove_member(db_session, _NoDirectAmqp(), channel.id, owner.id, member.id)
    await db_session.refresh(channel)

    delivered = await manager._forward_event(
        websocket,
        member.id,
        {
            "type": "message",
            "channel_id": channel_key,
            "membership_generation": int(channel.membership_generation),
            "content_type": "text",
            "content_text": "encrypted-sensitive-value",
        },
    )
    assert delivered is False
    assert decrypted is False
    assert websocket.sent == []
    assert channel_key not in manager._subscriptions[id(websocket)]


@pytest.mark.asyncio
async def test_active_member_refreshes_generation_and_receives_realtime_message(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase4_active_owner")
    member = await _register(db_session, "phase4_active_member")
    newcomer = await _register(db_session, "phase4_active_newcomer")
    channel = await _channel(db_session, owner, "Phase4 active delivery")
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, member.id, JoinRequest())
    await db_session.refresh(channel)
    cached_generation = int(channel.membership_generation)

    session_factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    manager = WSManager(session_factory, None, None)
    websocket = _RecordingWebSocket()
    channel_key = str(channel.id)
    manager._subscriptions[id(websocket)] = {channel_key}
    manager._subscription_generations[id(websocket)] = {channel_key: cached_generation}
    manager._subscription_checked_at[id(websocket)] = {channel_key: time.monotonic()}
    await ChannelService.join_channel(db_session, _NoDirectAmqp(), channel.id, newcomer.id, JoinRequest())
    await db_session.refresh(channel)

    def decrypt(event: dict) -> dict:
        event["content_text"] = "authorized plaintext"
        return event

    monkeypatch.setattr(manager, "_decrypt_event_payload", decrypt)
    delivered = await manager._forward_event(
        websocket,
        member.id,
        {
            "type": "message",
            "channel_id": channel_key,
            "membership_generation": int(channel.membership_generation),
            "content_type": "text",
            "content_text": "encrypted-value",
        },
    )
    assert delivered is True
    assert websocket.sent[0]["payload"]["content_text"] == "authorized plaintext"
    assert manager._subscription_generations[id(websocket)][channel_key] == int(channel.membership_generation)


@pytest.mark.asyncio
async def test_slug_delete_and_restore_use_same_versioned_reconciliation(db_session) -> None:
    owner = await _register(db_session, "phase4_topology_owner")
    channel = await _channel(db_session, owner, "Phase4 topology")
    state = await db_session.get(BrokerBindingState, {"channel_id": channel.id, "user_id": owner.id})
    assert state is not None
    original_key = state.desired_routing_key

    await ChannelService.update_channel(
        db_session,
        channel.id,
        owner.id,
        ChannelPatchRequest(channel_slug="phase4-topology-renamed"),
        _NoDirectAmqp(),
    )
    await db_session.refresh(state)
    assert original_key in state.routing_keys
    assert "channel.phase4-topology-renamed" in state.routing_keys
    assert state.desired_bound is True

    await ChannelService.delete_channel(db_session, channel.id, owner.id, _NoDirectAmqp())
    await db_session.refresh(state)
    assert state.desired_bound is False
    await AdminService.restore_channel(db_session, _NoDirectAmqp(), owner, channel.id)
    await db_session.refresh(state)
    assert state.desired_bound is True


@pytest.mark.asyncio
async def test_sync_large_single_channel_materializes_only_global_limit(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase4_sync_large")
    channel = await _channel(db_session, owner, "Phase4 sync ten thousand")
    await _insert_messages(db_session, channel.id, owner.id, 10_000)

    calls: list[tuple[int, int]] = []
    original = MessageService._fetch_sync_message_page

    async def record_page(db, channel_id, after_seq_id, limit):
        page = await original(db, channel_id, after_seq_id, limit)
        calls.append((int(limit), len(page)))
        return page

    monkeypatch.setattr(MessageService, "_fetch_sync_message_page", staticmethod(record_page))
    result = await MessageService.sync(
        db_session,
        owner.id,
        SyncRequest(channels=[SyncChannelCursor(channel_id=channel.id, last_seen_seq_id=0)], limit=100),
    )
    assert len(result["messages"]) == 100
    assert calls == [(100, 100)]
    assert [message.seq_id for message in result["messages"]] == list(range(1, 101))


@pytest.mark.asyncio
async def test_sync_many_channels_uses_one_decreasing_global_row_budget(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "phase4_sync_many")
    channels: list[Channel] = []
    encrypted = encrypt_message("many channel payload")
    for index in range(100):
        channel = Channel(
            owner_user_id=owner.id,
            name=f"Sync channel {index:03d}",
            channel_slug=f"sync-{index:03d}",
            visibility=ChannelVisibility.private,
            join_mode=ChannelJoinMode.open,
            last_seq_id=20,
        )
        db_session.add(channel)
        channels.append(channel)
    await db_session.flush()
    for channel in channels:
        db_session.add(
            ChannelMembership(
                channel_id=channel.id,
                user_id=owner.id,
                role=MembershipRole.owner,
                approved_at=utcnow(),
                created_by_user_id=owner.id,
            )
        )
        for seq_id in range(1, 21):
            db_session.add(
                Message(
                    channel_id=channel.id,
                    sender_user_id=owner.id,
                    seq_id=seq_id,
                    content_type=ContentType.text,
                    content_text=encrypted,
                )
            )
    await db_session.commit()

    calls: list[tuple[int, int]] = []
    original = MessageService._fetch_sync_message_page

    async def record_page(db, channel_id, after_seq_id, limit):
        page = await original(db, channel_id, after_seq_id, limit)
        calls.append((int(limit), len(page)))
        return page

    monkeypatch.setattr(MessageService, "_fetch_sync_message_page", staticmethod(record_page))
    result = await MessageService.sync(
        db_session,
        owner.id,
        SyncRequest(
            channels=[SyncChannelCursor(channel_id=channel.id, last_seen_seq_id=0) for channel in channels],
            limit=500,
        ),
    )
    pairs = [(str(message.channel_id), int(message.seq_id)) for message in result["messages"]]
    assert len(pairs) == 500
    assert pairs == sorted(pairs)
    assert sum(materialized for _, materialized in calls) == 500
    assert calls[0][0] == 500
    assert all(next_limit == previous_limit - previous_rows for (previous_limit, previous_rows), (next_limit, _) in zip(calls, calls[1:]))


@pytest.mark.asyncio
async def test_sync_next_cursor_has_no_skip_or_duplicate(db_session) -> None:
    owner = await _register(db_session, "phase4_sync_cursor")
    channel = await _channel(db_session, owner, "Phase4 sync cursor")
    await _insert_messages(db_session, channel.id, owner.id, 250)

    first = await MessageService.sync(
        db_session,
        owner.id,
        SyncRequest(channels=[SyncChannelCursor(channel_id=channel.id, last_seen_seq_id=0)], limit=100),
    )
    first_sequences = [int(message.seq_id) for message in first["messages"]]
    second = await MessageService.sync(
        db_session,
        owner.id,
        SyncRequest(
            channels=[SyncChannelCursor(channel_id=channel.id, last_seen_seq_id=first_sequences[-1])],
            limit=100,
        ),
    )
    second_sequences = [int(message.seq_id) for message in second["messages"]]
    assert first_sequences == list(range(1, 101))
    assert second_sequences == list(range(101, 201))
    assert set(first_sequences).isdisjoint(second_sequences)


@pytest.mark.asyncio
async def test_sync_arbitrary_pending_removed_and_outsider_cursors_return_no_history(db_session) -> None:
    owner = await _register(db_session, "phase4_sync_auth_owner")
    pending = await _register(db_session, "phase4_sync_auth_pending")
    removed = await _register(db_session, "phase4_sync_auth_removed")
    outsider = await _register(db_session, "phase4_sync_auth_outsider")
    channel = await _channel(db_session, owner, "Phase4 sync authorization")
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=pending.id,
            role=MembershipRole.pending,
            created_by_user_id=pending.id,
        )
    )
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=removed.id,
            role=MembershipRole.member,
            approved_at=utcnow(),
            created_by_user_id=owner.id,
        )
    )
    await db_session.commit()
    await _insert_messages(db_session, channel.id, owner.id, 3)
    await ChannelService.remove_member(db_session, _NoDirectAmqp(), channel.id, owner.id, removed.id)

    request = SyncRequest(channels=[SyncChannelCursor(channel_id=channel.id, last_seen_seq_id=0)], limit=10)
    for actor in (pending, removed, outsider):
        result = await MessageService.sync(db_session, actor.id, request)
        assert result["messages"] == []
        assert result["channel_updates"] == []


@pytest.mark.asyncio
async def test_protected_download_uses_chunked_file_response_without_read_bytes(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    owner = await _register(db_session, "phase4_stream_owner")
    content = (b"phase4-stream-" * 25_000)[:300_000]
    upload = Upload(
        owner_user_id=owner.id,
        filename="large.bin",
        content_type="application/octet-stream",
        size_bytes=len(content),
        storage_path=f"{owner.id}/large.bin",
        public_url=f"/v1/uploads/{uuid4()}/content",
    )
    db_session.add(upload)
    await db_session.commit()
    path = tmp_path / upload.storage_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    def forbidden_read_bytes(self):
        raise AssertionError("full-file Path.read_bytes buffering must not be used")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    response = await get_upload_content(upload.id, db_session, owner, _RateRedis())
    assert isinstance(response, LeasedFileResponse)
    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    await response(_http_scope(), _receive_request, send)
    body_chunks = [message.get("body", b"") for message in sent if message["type"] == "http.response.body"]
    nonempty_chunks = [chunk for chunk in body_chunks if chunk]
    assert b"".join(nonempty_chunks) == content
    assert len(nonempty_chunks) > 1
    assert max(map(len, nonempty_chunks)) <= response.chunk_size
    assert await protected_download_limiter.active_for(owner.id) == 0


@pytest.mark.asyncio
async def test_protected_download_authorization_blocks_pending_removed_and_outsider_before_stream(db_session, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    owner = await _register(db_session, "phase4_download_owner")
    pending = await _register(db_session, "phase4_download_pending")
    removed = await _register(db_session, "phase4_download_removed")
    outsider = await _register(db_session, "phase4_download_outsider")
    channel = await _channel(db_session, owner, "Phase4 protected download")
    db_session.add_all(
        [
            ChannelMembership(channel_id=channel.id, user_id=pending.id, role=MembershipRole.pending),
            ChannelMembership(
                channel_id=channel.id,
                user_id=removed.id,
                role=MembershipRole.member,
                approved_at=utcnow(),
            ),
        ]
    )
    upload = Upload(
        owner_user_id=owner.id,
        filename="private.bin",
        content_type="application/octet-stream",
        size_bytes=7,
        storage_path=f"{owner.id}/private.bin",
        public_url="stored",
    )
    db_session.add(upload)
    await db_session.flush()
    message = Message(
        channel_id=channel.id,
        sender_user_id=owner.id,
        seq_id=1,
        content_type=ContentType.text,
        content_text=encrypt_message("private"),
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(MessageAttachment(message_id=message.id, upload_id=upload.id, channel_id=channel.id))
    await db_session.commit()
    await ChannelService.remove_member(db_session, _NoDirectAmqp(), channel.id, owner.id, removed.id)

    for actor in (pending, removed, outsider):
        with pytest.raises(HTTPException) as exc_info:
            await get_upload_content(upload.id, db_session, actor, _RateRedis())
        assert exc_info.value.status_code == 403
        assert await protected_download_limiter.active_for(actor.id) == 0


@pytest.mark.asyncio
async def test_download_concurrency_limit_allows_boundary_and_rejects_one_above() -> None:
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()
    first = await limiter.try_acquire(user_id, 2)
    second = await limiter.try_acquire(user_id, 2)
    third = await limiter.try_acquire(user_id, 2)
    assert first is not None
    assert second is not None
    assert third is None
    assert await limiter.active_for(user_id) == 2
    await first.release()
    replacement = await limiter.try_acquire(user_id, 2)
    assert replacement is not None
    await second.release()
    await replacement.release()
    assert await limiter.active_for(user_id) == 0


@pytest.mark.asyncio
async def test_aborted_stream_releases_download_slot(tmp_path) -> None:
    path = tmp_path / "aborted.bin"
    path.write_bytes(b"x" * 200_000)
    limiter = DownloadConcurrencyLimiter()
    user_id = uuid4()
    lease = await limiter.try_acquire(user_id, 1)
    assert lease is not None
    response = LeasedFileResponse(path, lease, media_type="application/octet-stream")

    async def abort_on_body(message: dict) -> None:
        if message["type"] == "http.response.body":
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await response(_http_scope(), _receive_request, abort_on_body)
    assert await limiter.active_for(user_id) == 0
    replacement = await limiter.try_acquire(user_id, 1)
    assert replacement is not None
    await replacement.release()
