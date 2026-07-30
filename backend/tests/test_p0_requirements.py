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


# Stores fake amqp channel state for the verification flow; pytest runs it as a regression check.
class _FakeAmqpChannel:
    # Closes; pytest runs it as a regression check.
    async def close(self) -> None:
        return None


# Stores fake amqp connection state for the verification flow; pytest runs it as a regression check.
class _FakeAmqpConnection:
    # Creates a mocked broker channel; pytest runs it as a regression check.
    async def channel(self) -> _FakeAmqpChannel:
        return _FakeAmqpChannel()


# Verifies channel creation generates slug and logs event; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_channel_creation_generates_slug_and_logs_event(db_session, monkeypatch):
    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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


# Verifies message encryption round trip and authz and event; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_message_encryption_round_trip_and_authz_and_event(db_session, monkeypatch):
    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
    with pytest.raises(AppError) as publish_err:
        await MessageService.publish_message(
            db_session,
            channel.id,
            outsider.id,
            PublishMessageRequest(content_text="no access"),
        )
    assert publish_err.value.status_code == 403

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
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


# Verifies username validation accepts safe identifiers; pytest runs it as a regression check.
@pytest.mark.parametrize("username", ["alice_01", "User-02", "abc123"])
def test_username_validation_accepts_safe_identifiers(username):
    req = RegisterRequest(username=username, email=f"{username.lower()}@example.com", password="password123")
    assert req.username == username.strip()


# Verifies username validation rejects unsafe identifiers; pytest runs it as a regression check.
@pytest.mark.parametrize("username", ["ab", "bad.name", "bad name", "bad/name", "bad\\name", "bad#name", "bad\tname"])
def test_username_validation_rejects_unsafe_identifiers(username):
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, email="x@example.com", password="password123")


# Verifies channel slug validation accepts safe identifiers; pytest runs it as a regression check.
@pytest.mark.parametrize("slug", ["news-room", "team_01", "abc123"])
def test_channel_slug_validation_accepts_safe_identifiers(slug):
    req = ChannelCreateRequest(name="Channel", channel_slug=slug, visibility="public", join_mode="open")
    assert req.channel_slug == slug.strip().lower()


# Verifies channel slug validation rejects unsafe identifiers; pytest runs it as a regression check.
@pytest.mark.parametrize("slug", ["ab", "bad.name", "bad name", "bad/name", "bad\\name", "bad#name", "bad\tname"])
def test_channel_slug_validation_rejects_unsafe_identifiers(slug):
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        ChannelCreateRequest(name="Channel", channel_slug=slug, visibility="public", join_mode="open")


# Verifies avatar url validation rejects unsafe values; pytest runs it as a regression check.
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
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        UpdateMeRequest(avatar_url=avatar_url)
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        UpdateMeRequest(wallpaper_url=avatar_url)
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        ChannelPatchRequest(avatar_url=avatar_url)


# Verifies avatar url validation accepts safe values; pytest runs it as a regression check.
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


# Verifies upload download requires channel membership; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_upload_download_requires_channel_membership(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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

    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
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


# Verifies media attachments can be published without text and synced; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_media_attachments_can_be_published_without_text_and_synced(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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
    # Process each `(filename, content_type, content)` from `media_files` to apply this step to the full collection.
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


# Verifies publishing attachment requires stored upload content; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_publishing_attachment_requires_stored_upload_content(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
    with pytest.raises(AppError) as exc_info:
        await MessageService.publish_message(
            db_session,
            channel.id,
            owner.id,
            PublishMessageRequest(attachments=[{"file_id": str(upload.id)}]),
        )
    assert exc_info.value.status_code == 400


# Verifies publish request rejects duplicate attachment references; pytest runs it as a regression check.
def test_publish_request_rejects_duplicate_attachment_references():
    file_id = "00000000-0000-0000-0000-000000000001"
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        PublishMessageRequest(attachments=[{"file_id": file_id}, {"file_id": file_id}])


# Verifies publish request rejects extra attachment metadata; pytest runs it as a regression check.
def test_publish_request_rejects_extra_attachment_metadata():
    # Keep `pytest.raises(ValidationError)` active while this scoped operation is performed.
    with pytest.raises(ValidationError):
        PublishMessageRequest(
            attachments=[
                {
                    "file_id": "00000000-0000-0000-0000-000000000001",
                    "url": "https://example.com/not-trusted.png",
                }
            ]
        )


# Verifies upload store errors are logged and do not mark content stored; pytest runs it as a regression check.
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

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
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


# Verifies upload checksum mismatch is logged and keeps upload pending; pytest runs it as a regression check.
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

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
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


# Verifies svg uploads are rejected for protected media; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_svg_uploads_are_rejected_for_protected_media(db_session):
    owner = await AuthService.register(db_session, RegisterRequest(username="media_svg", email="media_svg@x.com", password="password123"))

    # Keep `pytest.raises(AppError)` active while this scoped operation is performed.
    with pytest.raises(AppError) as exc_info:
        await MessageService.create_upload(
            db_session,
            owner.id,
            UploadCreateRequest(filename="script.svg", content_type="image/svg+xml", size_bytes=10),
        )
    assert exc_info.value.status_code == 400


# Verifies profile avatar upload is accessible to authenticated users; pytest runs it as a regression check.
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


# Verifies profile wallpaper upload is saved to current user; pytest runs it as a regression check.
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


# Verifies avatar update rejects unowned or non image uploads; pytest runs it as a regression check.
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
    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
    with pytest.raises(HTTPException) as non_image_exc:
        await update_me(UpdateMeRequest(avatar_url=stored_text.public_url), db_session, owner)
    assert non_image_exc.value.status_code == 400
    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
    with pytest.raises(HTTPException) as wallpaper_non_image_exc:
        await update_me(UpdateMeRequest(wallpaper_url=stored_text.public_url), db_session, owner)
    assert wallpaper_non_image_exc.value.status_code == 400

    other_upload = await MessageService.create_upload(
        db_session,
        other.id,
        UploadCreateRequest(filename="other.png", content_type="image/png", size_bytes=5),
    )
    stored_other = await MessageService.store_upload_content(db_session, other.id, other_upload.id, b"12345")
    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
    with pytest.raises(HTTPException) as unowned_exc:
        await update_me(UpdateMeRequest(avatar_url=stored_other.public_url), db_session, owner)
    assert unowned_exc.value.status_code == 404
    # Keep `pytest.raises(HTTPException)` active while this scoped operation is performed.
    with pytest.raises(HTTPException) as wallpaper_unowned_exc:
        await update_me(UpdateMeRequest(wallpaper_url=stored_other.public_url), db_session, owner)
    assert wallpaper_unowned_exc.value.status_code == 404


# Verifies private channel avatar upload requires channel membership; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_private_channel_avatar_upload_requires_channel_membership(db_session, monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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


# Verifies upload storage path sanitizes filename and stays within base dir; pytest runs it as a regression check.
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


# Verifies smoke flow channel join publish sync and events; pytest runs it as a regression check.
@pytest.mark.asyncio
async def test_smoke_flow_channel_join_publish_sync_and_events(db_session, monkeypatch):
    # Provides a no-op broker binding for isolated tests; pytest runs it as a regression check.
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
