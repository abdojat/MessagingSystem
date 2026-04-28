import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import Event, MembershipRole, Message, Outbox
from app.schemas.auth import RegisterRequest
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest
from app.services.auth_service import AuthService
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService


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
