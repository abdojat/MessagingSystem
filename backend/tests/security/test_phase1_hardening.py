from datetime import timedelta
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes.messages import put_upload_content
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.upload_encryption import iter_decrypted_upload_file
from app.core.utils import utcnow
from app.db.models import UserChannelState
from app.realtime.ws_manager import WSManager
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, JoinRequest
from app.schemas.messages import PublishMessageRequest, SeenRequest, SyncRequest, UploadCreateRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService


SECURE_JWT_SECRET = "phase1-security-test-A1b2C3d4E5f6G7h8I9j0K1l2"
SECURE_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


class _FakeAmqpChannel:
    async def close(self) -> None:
        return None


class _FakeAmqpConnection:
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _StreamingOnlyRequest:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.body_called = False

    async def body(self) -> bytes:
        self.body_called = True
        raise AssertionError("the upload route must not buffer request.body()")

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk

    def stream(self):
        return self._stream()


class _AllowRateRedis:
    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 60


async def _chunks(*values: bytes):
    for value in values:
        yield value


async def _register(db_session, username: str):
    return await AuthService.register(
        db_session,
        RegisterRequest(username=username, email=f"{username}@example.com", password="Password123!"),
    )


async def _create_private_channel(db_session, monkeypatch, owner, name: str, *, join_mode: str = "invite_only"):
    async def _noop_binding(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_binding)
    monkeypatch.setattr("app.services.channel_service.unbind_user_channel", _noop_binding)
    return await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name=name, visibility="private", join_mode=join_mode),
        _FakeAmqpConnection(),
    )


def _assert_no_upload_artifacts(base_dir: Path, storage_path: str) -> None:
    target = MessageService._resolve_upload_path(str(base_dir), storage_path)
    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.*.uploading")) == []


def test_development_and_test_configuration_allow_explicit_test_convenience() -> None:
    for environment in ("development", "test"):
        settings = Settings(
            _env_file=None,
            environment=environment,
            jwt_secret="change-me",
            message_encryption_enabled=True,
            message_encryption_key="",
        )
        assert settings.environment == environment


def test_production_rejects_missing_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET is required"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="",
            message_encryption_enabled=False,
        )


@pytest.mark.parametrize("environment", ["production", "prod", "staging"])
@pytest.mark.parametrize("jwt_secret", ["change-me", "change-this-jwt-secret"])
def test_production_like_environments_reject_known_default_jwt_secrets(
    environment: str,
    jwt_secret: str,
) -> None:
    with pytest.raises(ValidationError, match="known development placeholder"):
        Settings(
            _env_file=None,
            environment=environment,
            jwt_secret=jwt_secret,
            message_encryption_enabled=False,
        )


def test_production_rejects_missing_data_encryption_key_ring() -> None:
    with pytest.raises(ValidationError, match="DATA_ENCRYPTION_KEYS"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret=SECURE_JWT_SECRET,
            message_encryption_enabled=True,
            message_encryption_key="",
            data_encryption_active_key_id="",
            data_encryption_keys="",
        )


def test_production_accepts_securely_configured_secrets() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret=SECURE_JWT_SECRET,
        message_encryption_enabled=True,
        message_encryption_key=SECURE_FERNET_KEY,
    )
    assert settings.jwt_secret == SECURE_JWT_SECRET
    assert settings.message_encryption_key == SECURE_FERNET_KEY


@pytest.mark.asyncio
async def test_upload_route_streams_request_without_calling_body(monkeypatch) -> None:
    request = _StreamingOnlyRequest([b"first", b"second"])
    user = SimpleNamespace(id=uuid4())
    file_id = uuid4()
    received = bytearray()

    async def _store(db, actor_user_id, requested_file_id, stream):
        assert actor_user_id == user.id
        assert requested_file_id == file_id
        async for chunk in stream:
            received.extend(chunk)
        return SimpleNamespace(id=file_id, public_url=f"/v1/uploads/{file_id}/content")

    monkeypatch.setattr(MessageService, "store_upload_content", _store)

    response = await put_upload_content(file_id, request, object(), user, _AllowRateRedis())

    assert request.body_called is False
    assert bytes(received) == b"firstsecond"
    assert response["public_url"].endswith(f"/{file_id}/content")


@pytest.mark.asyncio
async def test_streamed_upload_is_immutable_and_attachment_reference_still_works(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "immutable_owner")
    channel = await _create_private_channel(db_session, monkeypatch, owner, "Immutable uploads")
    original = b"original-content"
    replacement = b"tampered-content"
    assert len(original) == len(replacement)
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(
            filename="history.txt",
            content_type="text/plain",
            size_bytes=len(original),
            checksum=hashlib.sha256(original).hexdigest(),
        ),
    )

    stored = await MessageService.store_upload_content(
        db_session,
        owner.id,
        upload.id,
        _chunks(original[:3], original[3:9], original[9:]),
    )
    target = MessageService._resolve_upload_path(str(tmp_path), upload.storage_path)
    assert stored.public_url == f"/v1/uploads/{upload.id}/content"
    finalized_ciphertext = target.read_bytes()
    assert original not in finalized_ciphertext
    assert b"".join(
        iter_decrypted_upload_file(
            target,
            expected_upload_id=upload.id,
            expected_key_id=stored.storage_key_id,
            expected_plaintext_size=len(original),
        )
    ) == original

    message = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(attachments=[{"file_id": str(upload.id)}]),
    )
    assert message.attachments and message.attachments[0]["file_id"] == str(upload.id)
    owner_id = owner.id
    upload_id = upload.id

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(
            db_session,
            owner_id,
            upload_id,
            _chunks(replacement),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "UPLOAD_IMMUTABLE"
    assert target.read_bytes() == finalized_ciphertext
    assert await MessageService.can_access_upload(db_session, owner_id, upload_id) is True


@pytest.mark.asyncio
async def test_streamed_upload_aborts_at_configured_max_and_cleans_partial_file(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("UPLOAD_MAX_SIZE_BYTES", "4")
    get_settings.cache_clear()
    owner = await _register(db_session, "upload_limit_owner")
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="bounded.txt", content_type="text/plain", size_bytes=4),
    )

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, _chunks(b"1234", b"5"))

    assert exc_info.value.status_code == 413
    await db_session.refresh(upload)
    assert upload.public_url is None
    _assert_no_upload_artifacts(Path(tmp_path), upload.storage_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared_size", "content"),
    [(3, b"four"), (4, b"tri")],
    ids=["larger-than-declared", "smaller-than-declared"],
)
async def test_streamed_upload_rejects_declared_size_mismatch_without_finalizing(
    db_session,
    monkeypatch,
    tmp_path,
    declared_size: int,
    content: bytes,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, f"size_owner_{declared_size}")
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="size.txt", content_type="text/plain", size_bytes=declared_size),
    )

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, _chunks(content))

    assert exc_info.value.status_code == 400
    await db_session.refresh(upload)
    assert upload.public_url is None
    _assert_no_upload_artifacts(Path(tmp_path), upload.storage_path)


@pytest.mark.asyncio
async def test_streamed_upload_rejects_checksum_mismatch_without_finalizing(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "checksum_owner")
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(
            filename="checksum.txt",
            content_type="text/plain",
            size_bytes=4,
            checksum="0" * 64,
        ),
    )

    with pytest.raises(AppError, match="checksum mismatch"):
        await MessageService.store_upload_content(db_session, owner.id, upload.id, _chunks(b"data"))

    await db_session.refresh(upload)
    assert upload.public_url is None
    _assert_no_upload_artifacts(Path(tmp_path), upload.storage_path)


@pytest.mark.asyncio
async def test_interrupted_stream_cleans_partial_upload_and_keeps_pending(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "partial_owner")
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="partial.txt", content_type="text/plain", size_bytes=8),
    )

    async def _interrupted_stream():
        yield b"part"
        raise RuntimeError("client disconnected")

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, _interrupted_stream())

    assert exc_info.value.status_code == 500
    await db_session.refresh(upload)
    assert upload.public_url is None
    _assert_no_upload_artifacts(Path(tmp_path), upload.storage_path)


@pytest.mark.asyncio
async def test_finalization_rolls_back_if_success_audit_event_cannot_be_stored(
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()
    owner = await _register(db_session, "audit_failure_owner")
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="audit.txt", content_type="text/plain", size_bytes=4),
    )

    async def _fail_audit(*args, **kwargs):
        raise RuntimeError("audit database unavailable")

    monkeypatch.setattr("app.services.message_service.log_event", _fail_audit)

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, _chunks(b"data"))

    assert exc_info.value.status_code == 500
    await db_session.refresh(upload)
    assert upload.public_url is None
    _assert_no_upload_artifacts(Path(tmp_path), upload.storage_path)


@pytest.mark.asyncio
async def test_subscribed_channel_event_is_delivered() -> None:
    user_id = uuid4()
    channel_id = uuid4()
    websocket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._subscriptions = {id(websocket): {str(channel_id)}}
    manager._subscription_generations = {id(websocket): {str(channel_id): 1}}
    manager._subscription_checked_at = {id(websocket): {str(channel_id): time.monotonic()}}
    manager._decrypt_event_payload = lambda event: event

    delivered = await manager._forward_event(
        websocket,
        user_id,
        {
            "type": "message",
            "channel_id": str(channel_id),
            "membership_generation": 1,
            "content_text": "allowed",
        },
    )

    assert delivered is True
    assert len(websocket.sent) == 1


@pytest.mark.asyncio
async def test_unsubscribed_channel_event_is_not_delivered() -> None:
    websocket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._subscriptions = {id(websocket): {str(uuid4())}}

    delivered = await manager._forward_event(
        websocket,
        uuid4(),
        {"type": "message", "channel_id": str(uuid4()), "content_text": "blocked"},
    )

    assert delivered is False
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_empty_subscription_does_not_receive_other_users_membership_updates() -> None:
    user_id = uuid4()
    websocket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._subscriptions = {id(websocket): set()}

    delivered = await manager._forward_event(
        websocket,
        user_id,
        {
            "type": "membership_update",
            "channel_id": str(uuid4()),
            "user_id": str(uuid4()),
            "new_role": "member",
            "reason": "added",
        },
    )

    assert delivered is False
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_unsubscribing_final_channel_blocks_ordinary_channel_events() -> None:
    user_id = uuid4()
    channel_id = uuid4()
    websocket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._subscriptions = {id(websocket): {str(channel_id)}}
    manager._subscription_generations = {id(websocket): {str(channel_id): 1}}
    manager._subscription_checked_at = {id(websocket): {str(channel_id): time.monotonic()}}

    await manager._handle_unsubscribe(
        websocket,
        {"channel_ids": [str(channel_id)]},
        request_id=None,
    )
    delivered = await manager._forward_event(
        websocket,
        user_id,
        {"type": "message", "channel_id": str(channel_id), "content_text": "blocked"},
    )

    assert manager._subscriptions[id(websocket)] == set()
    assert delivered is False
    assert len(websocket.sent) == 1  # Unsubscribe acknowledgement only.


@pytest.mark.asyncio
async def test_targeted_membership_removal_reaches_affected_unsubscribed_user() -> None:
    user_id = uuid4()
    channel_id = uuid4()
    websocket = _RecordingWebSocket()
    manager = WSManager.__new__(WSManager)
    manager._subscriptions = {id(websocket): set()}
    manager._subscription_generations = {id(websocket): {}}
    manager._subscription_checked_at = {id(websocket): {}}

    delivered = await manager._forward_event(
        websocket,
        user_id,
        {
            "type": "membership_update",
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "new_role": "none",
            "reason": "removed",
        },
    )

    assert delivered is True
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["payload"]["reason"] == "removed"


@pytest.mark.asyncio
async def test_sync_member_cannot_receive_membership_events_from_unrelated_channel(
    db_session,
    monkeypatch,
) -> None:
    owner_a = await _register(db_session, "sync_owner_a")
    requester = await _register(db_session, "sync_requester")
    owner_b = await _register(db_session, "sync_owner_b")
    member_b = await _register(db_session, "sync_member_b")
    channel_a = await _create_private_channel(db_session, monkeypatch, owner_a, "Sync A")
    channel_b = await _create_private_channel(db_session, monkeypatch, owner_b, "Sync B")
    since = utcnow() - timedelta(minutes=1)
    await ChannelService.add_member_direct(db_session, _FakeAmqpConnection(), channel_a.id, owner_a.id, requester.id)
    await ChannelService.add_member_direct(db_session, _FakeAmqpConnection(), channel_b.id, owner_b.id, member_b.id)
    await ChannelService.promote_member(db_session, channel_b.id, owner_b.id, member_b.id)

    result = await MessageService.sync(db_session, requester.id, SyncRequest(since=since, limit=100))

    assert any(update["channel_id"] == channel_a.id for update in result["membership_updates"])
    assert all(update["channel_id"] != channel_b.id for update in result["membership_updates"])


@pytest.mark.asyncio
async def test_sync_outsider_cannot_receive_private_membership_activity(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "outsider_owner")
    member = await _register(db_session, "outsider_member")
    outsider = await _register(db_session, "sync_outsider")
    channel = await _create_private_channel(db_session, monkeypatch, owner, "Outsider private")
    since = utcnow() - timedelta(minutes=1)
    await ChannelService.add_member_direct(db_session, _FakeAmqpConnection(), channel.id, owner.id, member.id)
    await ChannelService.promote_member(db_session, channel.id, owner.id, member.id)

    result = await MessageService.sync(db_session, outsider.id, SyncRequest(since=since, limit=100))

    assert result["channel_updates"] == []
    assert result["membership_updates"] == []
    assert result["messages"] == []


@pytest.mark.asyncio
async def test_sync_removed_user_receives_own_removal_event(db_session, monkeypatch) -> None:
    owner = await _register(db_session, "remove_owner")
    removed_user = await _register(db_session, "removed_target")
    channel = await _create_private_channel(db_session, monkeypatch, owner, "Removal private")
    await ChannelService.add_member_direct(
        db_session,
        _FakeAmqpConnection(),
        channel.id,
        owner.id,
        removed_user.id,
    )
    since = utcnow() - timedelta(seconds=1)
    await ChannelService.remove_member(
        db_session,
        _FakeAmqpConnection(),
        channel.id,
        owner.id,
        removed_user.id,
    )

    result = await MessageService.sync(db_session, removed_user.id, SyncRequest(since=since, limit=100))

    assert any(
        update["channel_id"] == channel.id
        and update["user_id"] == removed_user.id
        and update["new_role"] == "none"
        and update["reason"] == "member.removed"
        for update in result["membership_updates"]
    )


@pytest.mark.asyncio
async def test_pending_member_cannot_access_private_read_derived_state(
    db_session,
    monkeypatch,
) -> None:
    owner = await _register(db_session, "pending_owner")
    pending_user = await _register(db_session, "pending_reader")
    channel = await _create_private_channel(
        db_session,
        monkeypatch,
        owner,
        "Pending private",
        join_mode="approval_required",
    )
    message = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="private history"),
    )
    status, membership, _ = await ChannelService.join_channel(
        db_session,
        _FakeAmqpConnection(),
        channel.id,
        pending_user.id,
        JoinRequest(),
    )
    assert status == "pending"
    assert membership is not None

    with pytest.raises(AppError) as seen_error:
        await MessageService.mark_seen(
            db_session,
            channel.id,
            pending_user.id,
            SeenRequest(last_seen_seq_id=message.seq_id),
        )
    assert seen_error.value.status_code == 403
    assert await db_session.get(
        UserChannelState,
        {"channel_id": channel.id, "user_id": pending_user.id},
    ) is None

    with pytest.raises(AppError) as stats_error:
        await ChannelService.get_channel_stats(db_session, channel.id, pending_user.id)
    assert stats_error.value.status_code == 403

    with pytest.raises(AppError) as history_error:
        await MessageService.list_messages(
            db_session,
            channel.id,
            pending_user.id,
            before_seq_id=None,
            after_seq_id=None,
            limit=50,
        )
    assert history_error.value.status_code == 403

    sync_result = await MessageService.sync(
        db_session,
        pending_user.id,
        SyncRequest(channels=[{"channel_id": channel.id, "last_seen_seq_id": 0}], limit=100),
    )
    assert sync_result["channel_updates"] == []
    assert sync_result["messages"] == []

    manager = WSManager.__new__(WSManager)
    manager._session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert str(channel.id) not in await manager._member_channel_ids(pending_user.id)
