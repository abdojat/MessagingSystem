from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes.messages import get_upload_content
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import ChannelMembership, ChannelVisibility, Event, MembershipRole, Message, Outbox
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
async def test_list_channels_scopes_pagination_and_preview_permissions(db_session, monkeypatch):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(
        db_session,
        RegisterRequest(username="list_owner", email="list_owner@x.com", password="password123"),
    )
    member = await AuthService.register(
        db_session,
        RegisterRequest(username="list_member", email="list_member@x.com", password="password123"),
    )
    pending_user = await AuthService.register(
        db_session,
        RegisterRequest(username="list_pending", email="list_pending@x.com", password="password123"),
    )
    outsider = await AuthService.register(
        db_session,
        RegisterRequest(username="list_outsider", email="list_outsider@x.com", password="password123"),
    )
    amqp = _FakeAmqpConnection()

    private_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Private List Room", visibility="private", join_mode="invite_only"),
        amqp,
    )
    older_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Older List Room", visibility="public", join_mode="open"),
        amqp,
    )
    fresh_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Fresh List Room", visibility="public", join_mode="open"),
        amqp,
    )
    approval_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Approval List Room", visibility="public", join_mode="approval_required"),
        amqp,
    )

    await ChannelService.join_channel(db_session, amqp, fresh_channel.id, member.id, JoinRequest())
    pending_status, pending_membership, _ = await ChannelService.join_channel(
        db_session,
        amqp,
        approval_channel.id,
        pending_user.id,
        JoinRequest(),
    )
    assert pending_status == "pending"
    assert pending_membership is not None
    assert pending_membership.role == MembershipRole.pending

    older_message = await MessageService.publish_message(
        db_session,
        older_channel.id,
        owner.id,
        PublishMessageRequest(content_text="older visible preview"),
    )
    fresh_message = await MessageService.publish_message(
        db_session,
        fresh_channel.id,
        owner.id,
        PublishMessageRequest(content_text="fresh member preview"),
    )
    approval_message = await MessageService.publish_message(
        db_session,
        approval_channel.id,
        owner.id,
        PublishMessageRequest(content_text="approval-only preview"),
    )
    now = utcnow()
    older_message.created_at = now - timedelta(minutes=20)
    fresh_message.created_at = now - timedelta(minutes=10)
    approval_message.created_at = now
    await db_session.commit()

    member_items, member_cursor, member_has_more = await ChannelService.list_channels(
        db_session,
        member.id,
        cursor=None,
        limit=10,
        scope="my",
    )
    assert member_cursor is None
    assert member_has_more is False
    assert [item["id"] for item in member_items] == [fresh_channel.id]
    assert member_items[0]["last_message"]["content_text"] == "fresh member preview"
    assert member_items[0]["unread_count"] == 1

    discover_items, _, _ = await ChannelService.list_channels(
        db_session,
        outsider.id,
        cursor=None,
        limit=10,
        scope="discover",
    )
    discover_by_id = {item["id"]: item for item in discover_items}
    assert private_channel.id not in discover_by_id
    assert {older_channel.id, fresh_channel.id, approval_channel.id}.issubset(discover_by_id)
    assert all(item["last_message"] is None for item in discover_by_id.values())
    assert discover_by_id[fresh_channel.id]["last_message_at"] == fresh_message.created_at

    pending_items, _, _ = await ChannelService.list_channels(
        db_session,
        pending_user.id,
        cursor=None,
        limit=10,
        scope="my",
    )
    assert [item["id"] for item in pending_items] == [approval_channel.id]
    assert pending_items[0]["my_role"] == MembershipRole.pending
    assert pending_items[0]["last_message"] is None
    assert pending_items[0]["unread_count"] == 0
    assert pending_items[0]["pending_count"] == 0

    first_page, next_cursor, has_more = await ChannelService.list_channels(
        db_session,
        owner.id,
        cursor=None,
        limit=2,
        scope="my",
    )
    assert has_more is True
    assert next_cursor is not None
    assert [item["id"] for item in first_page] == [approval_channel.id, fresh_channel.id]

    second_page, final_cursor, final_has_more = await ChannelService.list_channels(
        db_session,
        owner.id,
        cursor=next_cursor,
        limit=10,
        scope="my",
    )
    assert final_has_more is False
    assert final_cursor is None
    assert [item["id"] for item in second_page] == [older_channel.id, private_channel.id]


@pytest.mark.asyncio
async def test_list_channels_scope_visibility_and_search_filters(db_session, monkeypatch):
    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(
        db_session,
        RegisterRequest(username="filter_owner", email="filter_owner@x.com", password="password123"),
    )
    member = await AuthService.register(
        db_session,
        RegisterRequest(username="filter_member", email="filter_member@x.com", password="password123"),
    )
    outsider = await AuthService.register(
        db_session,
        RegisterRequest(username="filter_outsider", email="filter_outsider@x.com", password="password123"),
    )
    amqp = _FakeAmqpConnection()

    public_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Release Board",
            channel_slug="release-board",
            visibility="public",
            join_mode="open",
        ),
        amqp,
    )
    private_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Private Board",
            channel_slug="private-board",
            visibility="private",
            join_mode="invite_only",
        ),
        amqp,
    )
    literal_percent_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Coverage 100%",
            channel_slug="coverage-board",
            visibility="public",
            join_mode="open",
        ),
        amqp,
    )
    literal_underscore_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="Team_Room Updates",
            channel_slug="team_room",
            visibility="public",
            join_mode="open",
        ),
        amqp,
    )
    await ChannelService.join_channel(db_session, amqp, public_channel.id, member.id, JoinRequest())

    member_items, _, _ = await ChannelService.list_channels(
        db_session,
        member.id,
        cursor=None,
        limit=10,
        q="#release-board",
        visibility=ChannelVisibility.public,
        scope="my",
    )
    assert [item["id"] for item in member_items] == [public_channel.id]

    owner_private_items, _, _ = await ChannelService.list_channels(
        db_session,
        owner.id,
        cursor=None,
        limit=10,
        visibility=ChannelVisibility.private,
        scope="my",
    )
    assert [item["id"] for item in owner_private_items] == [private_channel.id]

    discover_private_items, _, _ = await ChannelService.list_channels(
        db_session,
        outsider.id,
        cursor=None,
        limit=10,
        visibility=ChannelVisibility.private,
        scope="discover",
    )
    assert discover_private_items == []

    discover_hash_items, _, _ = await ChannelService.list_channels(
        db_session,
        outsider.id,
        cursor=None,
        limit=10,
        q="#team_room",
        scope="discover",
    )
    assert [item["id"] for item in discover_hash_items] == [literal_underscore_channel.id]

    literal_percent_items, _, _ = await ChannelService.list_channels(
        db_session,
        outsider.id,
        cursor=None,
        limit=10,
        q="%",
        scope="discover",
    )
    assert [item["id"] for item in literal_percent_items] == [literal_percent_channel.id]

    literal_underscore_items, _, _ = await ChannelService.list_channels(
        db_session,
        outsider.id,
        cursor=None,
        limit=10,
        q="_",
        scope="discover",
    )
    assert [item["id"] for item in literal_underscore_items] == [literal_underscore_channel.id]


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
    assert events[0].payload["message_id"] == str(published.id)
    assert events[0].payload["seq_id"] == published.seq_id
    assert "content_text" not in events[0].payload
    assert "content_json" not in events[0].payload
    assert "attachments" not in events[0].payload
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
        UpdateMeRequest(wallpaper_url=avatar_url)
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
    assert UpdateMeRequest(wallpaper_url=avatar_url).wallpaper_url == avatar_url
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

    owner_response = await get_upload_content(upload.id, db_session, owner)
    assert owner_response.body == b"hello world"

    unauthorized_events = (
        await db_session.execute(select(Event).where(Event.event_type == "security.unauthorized_upload_access"))
    ).scalars().all()
    assert len(unauthorized_events) == 1
    accessed_events = (
        await db_session.execute(select(Event).where(Event.event_type == "upload.accessed"))
    ).scalars().all()
    assert len(accessed_events) == 1
    assert accessed_events[0].payload["upload_id"] == str(upload.id)


@pytest.mark.asyncio
async def test_media_attachments_can_be_published_without_text_and_synced(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="media_owner", email="media_owner@x.com", password="password123"))
    subscriber = await AuthService.register(db_session, RegisterRequest(username="media_sub", email="media_sub@x.com", password="password123"))
    amqp = _FakeAmqpConnection()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Media Channel", visibility="public", join_mode="open"),
        amqp,
    )
    await ChannelService.join_channel(db_session, amqp, channel.id, subscriber.id, JoinRequest())

    media_files = [
        ("photo.png", "image/png", b"pngdata"),
        ("clip.mp4", "video/mp4", b"mp4data"),
        ("song.mp3", "audio/mpeg", b"mp3data"),
    ]
    upload_ids = []
    for filename, content_type, content in media_files:
        upload = await MessageService.create_upload(
            db_session,
            owner.id,
            UploadCreateRequest(filename=filename, content_type=content_type, size_bytes=len(content)),
        )
        stored = await MessageService.store_upload_content(db_session, owner.id, upload.id, content)
        assert stored.public_url == f"/v1/uploads/{upload.id}/content"
        upload_ids.append(upload.id)

    published = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(attachments=[{"file_id": str(file_id)} for file_id in upload_ids]),
    )

    assert published.content_type.value == "text"
    assert published.content_text is None
    assert [item["content_type"] for item in published.attachments] == ["image/png", "video/mp4", "audio/mpeg"]
    assert all(item["url"].startswith("/v1/uploads/") for item in published.attachments)
    assert await MessageService.can_access_upload(db_session, subscriber.id, upload_ids[0]) is True

    sync = await MessageService.sync(
        db_session,
        subscriber.id,
        SyncRequest(channels=[{"channel_id": channel.id, "last_seen_seq_id": 0}], limit=20),
    )
    synced_message = next((message for message in sync["messages"] if message.id == published.id), None)
    assert synced_message is not None
    assert synced_message.attachments and len(synced_message.attachments) == 3

    upload_event_types = {
        event.event_type
        for event in (await db_session.execute(select(Event).where(Event.actor_user_id == owner.id))).scalars().all()
    }
    assert {"upload.created", "upload.content_stored", "message.published"}.issubset(upload_event_types)


@pytest.mark.asyncio
async def test_publishing_attachment_requires_stored_upload_content(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    async def _noop_bind(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.channel_service.bind_user_channel", _noop_bind)

    owner = await AuthService.register(db_session, RegisterRequest(username="media_pending", email="media_pending@x.com", password="password123"))
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="Pending Media", visibility="public", join_mode="open"),
        _FakeAmqpConnection(),
    )
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="pending.mp4", content_type="video/mp4", size_bytes=7),
    )

    with pytest.raises(AppError) as exc_info:
        await MessageService.publish_message(
            db_session,
            channel.id,
            owner.id,
            PublishMessageRequest(attachments=[{"file_id": str(upload.id)}]),
        )
    assert exc_info.value.status_code == 400


def test_publish_request_rejects_duplicate_attachment_references():
    file_id = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(ValidationError):
        PublishMessageRequest(attachments=[{"file_id": file_id}, {"file_id": file_id}])


def test_publish_request_rejects_extra_attachment_metadata():
    with pytest.raises(ValidationError):
        PublishMessageRequest(
            attachments=[
                {
                    "file_id": "00000000-0000-0000-0000-000000000001",
                    "url": "https://example.com/not-trusted.png",
                }
            ]
        )


@pytest.mark.asyncio
async def test_upload_store_errors_are_logged_and_do_not_mark_content_stored(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(db_session, RegisterRequest(username="media_error", email="media_error@x.com", password="password123"))
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="clip.mp4", content_type="video/mp4", size_bytes=7),
    )

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, b"short")
    assert exc_info.value.status_code == 400

    await db_session.refresh(upload)
    assert upload.public_url is None
    assert not MessageService._resolve_upload_path(str(tmp_path), upload.storage_path).exists()
    failed_event = (
        await db_session.execute(select(Event).where(Event.event_type == "upload.store_failed"))
    ).scalars().one()
    assert failed_event.payload["upload_id"] == str(upload.id)
    assert failed_event.payload["reason"] == "size_mismatch"


@pytest.mark.asyncio
async def test_upload_checksum_mismatch_is_logged_and_keeps_upload_pending(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(
        db_session,
        RegisterRequest(username="media_checksum", email="media_checksum@x.com", password="password123"),
    )
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="song.mp3", content_type="audio/mpeg", size_bytes=4, checksum="0" * 64),
    )

    with pytest.raises(AppError) as exc_info:
        await MessageService.store_upload_content(db_session, owner.id, upload.id, b"data")
    assert exc_info.value.status_code == 400

    await db_session.refresh(upload)
    assert upload.public_url is None
    failed_event = (
        await db_session.execute(select(Event).where(Event.event_type == "upload.store_failed"))
    ).scalars().one()
    assert failed_event.payload["upload_id"] == str(upload.id)
    assert failed_event.payload["reason"] == "checksum_mismatch"


@pytest.mark.asyncio
async def test_svg_uploads_are_rejected_for_protected_media(db_session):
    owner = await AuthService.register(db_session, RegisterRequest(username="media_svg", email="media_svg@x.com", password="password123"))

    with pytest.raises(AppError) as exc_info:
        await MessageService.create_upload(
            db_session,
            owner.id,
            UploadCreateRequest(filename="script.svg", content_type="image/svg+xml", size_bytes=10),
        )
    assert exc_info.value.status_code == 400


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
async def test_profile_wallpaper_upload_is_saved_to_current_user(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    owner = await AuthService.register(db_session, RegisterRequest(username="wall_owner", email="wall_owner@x.com", password="password123"))
    viewer = await AuthService.register(db_session, RegisterRequest(username="wall_viewer", email="wall_viewer@x.com", password="password123"))
    upload = await MessageService.create_upload(
        db_session,
        owner.id,
        UploadCreateRequest(filename="wallpaper.webp", content_type="image/webp", size_bytes=8),
    )
    stored = await MessageService.store_upload_content(db_session, owner.id, upload.id, b"webpdata")

    updated = await update_me(UpdateMeRequest(wallpaper_url=stored.public_url), db_session, owner)

    assert updated.wallpaper_url == stored.public_url
    await db_session.refresh(owner)
    assert owner.wallpaper_url == stored.public_url
    assert await MessageService.can_access_upload(db_session, owner.id, upload.id) is True
    assert await MessageService.can_access_upload(db_session, viewer.id, upload.id) is False


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
    with pytest.raises(HTTPException) as wallpaper_non_image_exc:
        await update_me(UpdateMeRequest(wallpaper_url=stored_text.public_url), db_session, owner)
    assert wallpaper_non_image_exc.value.status_code == 400

    other_upload = await MessageService.create_upload(
        db_session,
        other.id,
        UploadCreateRequest(filename="other.png", content_type="image/png", size_bytes=5),
    )
    stored_other = await MessageService.store_upload_content(db_session, other.id, other_upload.id, b"12345")
    with pytest.raises(HTTPException) as unowned_exc:
        await update_me(UpdateMeRequest(avatar_url=stored_other.public_url), db_session, owner)
    assert unowned_exc.value.status_code == 404
    with pytest.raises(HTTPException) as wallpaper_unowned_exc:
        await update_me(UpdateMeRequest(wallpaper_url=stored_other.public_url), db_session, owner)
    assert wallpaper_unowned_exc.value.status_code == 404


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
