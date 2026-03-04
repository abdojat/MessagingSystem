import pytest
from pydantic import ValidationError

from app.db.models import User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest, SeenRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_seen_request_requires_exactly_one_marker():
    with pytest.raises(ValidationError):
        SeenRequest()
    with pytest.raises(ValidationError):
        SeenRequest(last_seen_message_id="00000000-0000-0000-0000-000000000001", last_seen_seq_id=1)


@pytest.mark.asyncio
async def test_mark_seen_with_message_id_sets_seq_and_unread(db_session):
    owner = User(username="owner_seen", email="owner_seen@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="seen-order", visibility="public", join_mode="open"),
        DummyAMQP(),
    )

    msg1 = await MessageService.publish_message(
        db_session, channel.id, owner.id, PublishMessageRequest(content_text="one")
    )
    await MessageService.publish_message(
        db_session, channel.id, owner.id, PublishMessageRequest(content_text="two")
    )

    state = await MessageService.mark_seen(db_session, channel.id, owner.id, SeenRequest(last_seen_message_id=msg1.id))
    assert state.last_seen_seq_id == msg1.seq_id
    assert state.unread_count == 1


@pytest.mark.asyncio
async def test_list_messages_honors_order(db_session):
    owner = User(username="owner_order", email="owner_order@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="order", visibility="public", join_mode="open"),
        DummyAMQP(),
    )

    for content in ("a", "b", "c"):
        await MessageService.publish_message(
            db_session, channel.id, owner.id, PublishMessageRequest(content_text=content)
        )

    desc_items, *_ = await MessageService.list_messages(db_session, channel.id, owner.id, None, None, 50, order="desc")
    asc_items, *_ = await MessageService.list_messages(db_session, channel.id, owner.id, None, None, 50, order="asc")

    assert [m.seq_id for m in desc_items] == [3, 2, 1]
    assert [m.seq_id for m in asc_items] == [1, 2, 3]
