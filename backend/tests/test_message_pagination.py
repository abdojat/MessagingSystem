import pytest

from app.db.models import User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_message_list_supports_after_seq_id(db_session):
    owner = User(username="owner_msgs", email="owner_msgs@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="c_msgs", visibility="public", join_mode="open"),
        DummyAMQP(),
    )
    for i in range(1, 6):
        await MessageService.publish_message(
            db_session,
            channel.id,
            owner.id,
            PublishMessageRequest(content_text=f"m{i}"),
        )

    items, next_before, next_after, has_more = await MessageService.list_messages(
        db_session, channel.id, owner.id, before_seq_id=None, after_seq_id=2, limit=2
    )
    assert [m.seq_id for m in items] == [3, 4]
    assert next_after == 4
    assert next_before is None
    assert has_more is True
