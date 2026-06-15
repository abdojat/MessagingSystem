from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes.messages import get_upload_content
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import ChannelMembership, Event, MembershipRole, Message, Outbox
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest
from app.schemas.messages import PublishMessageRequest, SyncRequest, UploadCreateRequest
from app.schemas.channels import JoinRequest
from app.schemas.users import UpdateMeRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from app.api.routes.users import update_me
from app.core.utils import utcnow


class _FakeAmqpChannel:
    async def close(self) -> None:
        return None


class _FakeAmqpConnection:
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


@pytest.mark.asyncio
async def test_channel_creation_generates_slug_and_logs_event(db_session, monkeypatch):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="owner", email="owner@x.com", password="password123"))
    amqp = _FakeAmqpConnection()

    first = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="News Room", visibility="public", join_mode="open"),
        amqp,
    )
    second = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="News Room", channel_slug="news-room", visibility="public", join_mode="open"),
        amqp,
    )

    assert first.channel_slug == "news-room"
    assert second.channel_slug == "news-room-2"

    events = (await db_session.execute(select(Event).where(Event.event_type == "channel.created"))).scalars().all()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_message_encryption_round_trip_and_authz_and_event(db_session, monkeypatch):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="alice", email="alice@x.com", password="password123"))
    outsider = await AuthService.register(db_session, RegisterRequest(username="bob", email="bob@x.com", password="password123"))
    amqp = _FakeAmqpConnection()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="security", visibility="private", join_mode="invite_only"),
        amqp,
    )

    plaintext = "Top secret message"
    published = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text=plaintext),
    )

    stored = await db_session.get(Message, published.id)
    assert stored is not None
    assert stored.content_text != plaintext

    outbox = (await db_session.execute(select(Outbox).where(Outbox.aggregate_id == published.id))).scalars().first()
    assert outbox is not None
    assert outbox.payload["content_text"] != plaintext

    fetched = await MessageService.get_message(db_session, channel.id, owner.id, published.id)
    content_text, content_json = MessageService._decrypt_message_content(fetched)
    assert content_text == plaintext
    assert content_json is None

    with pytest.raises(AppError) as publish_err:
        await MessageService.publish_message(
            db_session,
            channel.id,
            outsider.id,
            PublishMessageRequest(content_text="no access"),
        )
    assert publish_err.value.status_code == 403

    with pytest.raises(AppError) as read_err:
        await MessageService.list_messages(db_session, channel.id, outsider.id, None, None, 20)
    assert read_err.value.status_code == 403

    events = (await db_session.execute(select(Event).where(Event.event_type == "message.published"))).scalars().all()
    assert len(events) == 1
    unauthorized_publish_events = (
        await db_session.execute(select(Event).where(Event.event_type == "security.unauthorized_publish"))
    ).scalars().all()
    unauthorized_read_events = (
        await db_session.execute(select(Event).where(Event.event_type == "security.unauthorized_read"))
    ).scalars().all()
    assert len(unauthorized_publish_events) == 1
    assert len(unauthorized_read_events) == 1


@pytest.mark.parametrize("username", ["alice_01", "User-02", "abc123"])
def test_username_validation_accepts_safe_identifiers(username):
    req = RegisterRequest(username=username, email=f"{username.lower()}@example.com", password="password123")
    assert req.username == username.strip()


@pytest.mark.parametrize("username", ["ab", "bad.name", "bad name", "bad/name", "bad\\name", "bad#name", "bad\tname"])
def test_username_validation_rejects_unsafe_identifiers(username):
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, email="x@example.com", password="password123")


@pytest.mark.parametrize("slug", ["news-room", "team_01", "abc123"])
def test_channel_slug_validation_accepts_safe_identifiers(slug):
    req = ChannelCreateRequest(name="Channel", channel_slug=slug, visibility="public", join_mode="open")
    assert req.channel_slug == slug.strip().lower()


@pytest.mark.parametrize("slug", ["ab", "bad.name", "bad name", "bad/name", "bad\\name", "bad#name", "bad\tname"])
def test_channel_slug_validation_rejects_unsafe_identifiers(slug):
    with pytest.raises(ValidationError):
        ChannelCreateRequest(name="Channel", channel_slug=slug, visibility="public", join_mode="open")


@pytest.mark.parametrize(
    "avatar_url",
    [
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "file:///tmp/avatar.png",
        "//example.com/avatar.png",
        "/uploads/not-a-uuid/content",
        "/v1/uploads/00000000-0000-0000-0000-000000000000/content?token=x",
        "/static/avatar.png",
    ],
)
def test_avatar_url_validation_rejects_unsafe_values(avatar_url):
    with pytest.raises(ValidationError):
        UpdateMeRequest(avatar_url=avatar_url)
    with pytest.raises(ValidationError):
        ChannelPatchRequest(avatar_url=avatar_url)


@pytest.mark.parametrize(
    "avatar_url",
    [
        "https://example.com/avatar.png",
        "http://localhost:8000/v1/uploads/00000000-0000-0000-0000-000000000000/content",
        "/v1/uploads/00000000-0000-0000-0000-000000000000/content",
        "/uploads/00000000-0000-0000-0000-000000000000/content",
    ],
)
def test_avatar_url_validation_accepts_safe_values(avatar_url):
    assert UpdateMeRequest(avatar_url=avatar_url).avatar_url == avatar_url
    assert ChannelPatchRequest(avatar_url=avatar_url).avatar_url == avatar_url


@pytest.mark.asyncio
async def test_upload_download_requires_channel_membership(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="owner1", email="owner1@x.com", password="password123"))
    outsider = await AuthService.register(db_session, RegisterRequest(username="outsider1", email="outsider1@x.com", password="password123"))
    amqp = _FakeAmqpConnection()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Private Uploads", visibility="private", join_mode="invite_only"),
        amqp,
    )

    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="secret.txt", content_type="text/plain", size_bytes=11),
    )
    await MessageService.store_upload_content(db_session, owner.id, upload.id, b"hello world")
    await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(
            content_text="attachment test",
            attachments=[{"file_id": str(upload.id)}],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_upload_content(upload.id, db_session, outsider)
    assert exc_info.value.status_code == 403

    unauthorized_events = (
        await db_session.execute(select(Event).where(Event.event_type == "security.unauthorized_upload_access"))
    ).scalars().all()
    assert len(unauthorized_events) == 1


@pytest.mark.asyncio
async def test_profile_avatar_upload_is_accessible_to_authenticated_users(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(db_session, RegisterRequest(username="avatar_owner", email="avatar_owner@x.com", password="password123"))
    viewer = await AuthService.register(db_session, RegisterRequest(username="avatar_viewer", email="avatar_viewer@x.com", password="password123"))
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="avatar.png", content_type="image/png", size_bytes=7),
    )
    stored = await MessageService.store_upload_content(db_session, owner.id, upload.id, b"pngdata")

    updated = await update_me(UpdateMeRequest(avatar_url=stored.public_url), db_session, owner)

    assert updated.avatar_url == stored.public_url
    assert await MessageService.can_access_upload(db_session, viewer.id, upload.id) is True


@pytest.mark.asyncio
async def test_avatar_update_rejects_unowned_or_non_image_uploads(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(db_session, RegisterRequest(username="image_owner", email="image_owner@x.com", password="password123"))
    other = await AuthService.register(db_session, RegisterRequest(username="image_other", email="image_other@x.com", password="password123"))

    text_upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="notes.txt", content_type="text/plain", size_bytes=5),
    )
    stored_text = await MessageService.store_upload_content(db_session, owner.id, text_upload.id, b"hello")
    with pytest.raises(HTTPException) as non_image_exc:
        await update_me(UpdateMeRequest(avatar_url=stored_text.public_url), db_session, owner)
    assert non_image_exc.value.status_code == 400

    other_upload = await MessageService.create_upload(
        db_session,
        other.id,
        UploadCreateRequest(filename="other.png", content_type="image/png", size_bytes=5),
    )
    stored_other = await MessageService.store_upload_content(db_session, other.id, other_upload.id, b"12345")
    with pytest.raises(HTTPException) as unowned_exc:
        await update_me(UpdateMeRequest(avatar_url=stored_other.public_url), db_session, owner)
    assert unowned_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_private_channel_avatar_upload_requires_channel_membership(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="chan_owner", email="chan_owner@x.com", password="password123"))
    member = await AuthService.register(db_session, RegisterRequest(username="chan_member", email="chan_member@x.com", password="password123"))
    outsider = await AuthService.register(db_session, RegisterRequest(username="chan_outside", email="chan_outside@x.com", password="password123"))
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="channel.jpg", content_type="image/jpeg", size_bytes=6),
    )
    stored = await MessageService.store_upload_content(db_session, owner.id, upload.id, b"jpgjpg")

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Private Avatar",
            avatar_url=stored.public_url,
            visibility="private",
            join_mode="invite_only",
        ),
        _FakeAmqpConnection(),
    )

    assert await MessageService.can_access_upload(db_session, outsider.id, upload.id) is False

    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=member.id,
            role=MembershipRole.member,
            created_by_user_id=owner.id,
            approved_at=utcnow(),
        )
    )
    await db_session.commit()

    assert await MessageService.can_access_upload(db_session, member.id, upload.id) is True


@pytest.mark.asyncio
async def test_upload_storage_path_sanitizes_filename_and_stays_within_base_dir(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(db_session, RegisterRequest(username="owner2", email="owner2@x.com", password="password123"))
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="../../private/secret.txt", content_type="text/plain", size_bytes=5),
    )

    assert upload.storage_path.startswith(f"{owner.id}/")
    assert ".." not in upload.storage_path

    target = (Path(tmp_path) / upload.storage_path).resolve()
    assert str(target).startswith(str(Path(tmp_path).resolve()))


@pytest.mark.asyncio
async def test_smoke_flow_channel_join_publish_sync_and_events(db_session, monkeypatch):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="smoke_owner", email="smoke_owner@x.com", password="password123"))
    subscriber = await AuthService.register(db_session, RegisterRequest(username="smoke_sub", email="smoke_sub@x.com", password="password123"))
    amqp = _FakeAmqpConnection()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Smoke Flow", visibility="public", join_mode="open"),
        amqp,
    )
    await ChannelService.join_channel(db_session, amqp, channel.id, subscriber.id, JoinRequest())

    published = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="smoke test message"),
    )

    sync = await MessageService.sync(
        db_session,
        subscriber.id,
        SyncRequest(channels=[{"channel_id": channel.id, "last_seen_seq_id": 0}], limit=20),
    )
    assert any(message.id == published.id for message in sync["messages"])

    event_types = {
        event.event_type
        for event in (await db_session.execute(select(Event).where(Event.channel_id == channel.id))).scalars().all()
    }
    assert {"channel.created", "membership.joined", "message.published"}.issubset(event_types)
