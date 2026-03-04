import pytest

from app.core.errors import AppError
from app.db.models import ChannelMembership, MembershipRole, User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest, SyncRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_message_seq_pagination_contract(db_session):
    owner = User(username="owner_pg", email="owner_pg@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="pg", visibility="public", join_mode="open"),
        DummyAMQP(),
    )
    for i in range(1, 7):
        await MessageService.publish_message(db_session, channel.id, owner.id, PublishMessageRequest(content_text=f"m{i}"))

    desc_items, next_before, next_after, has_more = await MessageService.list_messages(
        db_session, channel.id, owner.id, before_seq_id=None, after_seq_id=None, limit=3, order="desc"
    )
    assert [m.seq_id for m in desc_items] == [6, 5, 4]
    assert next_before == 4
    assert next_after is None
    assert has_more is True

    asc_items, next_before_asc, next_after_asc, _ = await MessageService.list_messages(
        db_session, channel.id, owner.id, before_seq_id=None, after_seq_id=2, limit=2, order="asc"
    )
    assert [m.seq_id for m in asc_items] == [3, 4]
    assert next_before_asc is None
    assert next_after_asc == 4

    with pytest.raises(AppError) as exc:
        await MessageService.list_messages(
            db_session, channel.id, owner.id, before_seq_id=10, after_seq_id=1, limit=10, order="desc"
        )
    assert exc.value.code == "PAGINATION_INVALID"


@pytest.mark.asyncio
async def test_sync_returns_missed_messages_deterministically(db_session):
    owner = User(username="owner_sync2", email="owner_sync2@example.com", password_hash="x")
    member = User(username="member_sync2", email="member_sync2@example.com", password_hash="x")
    db_session.add_all([owner, member])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(member)

    amqp = DummyAMQP()
    c1 = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="sync-c1", visibility="public", join_mode="open"),
        amqp,
    )
    c2 = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="sync-c2", visibility="public", join_mode="open"),
        amqp,
    )
    db_session.add_all(
        [
            ChannelMembership(channel_id=c1.id, user_id=member.id, role=MembershipRole.admin, created_by_user_id=owner.id),
            ChannelMembership(channel_id=c2.id, user_id=member.id, role=MembershipRole.admin, created_by_user_id=owner.id),
        ]
    )
    await db_session.commit()

    await MessageService.publish_message(db_session, c1.id, owner.id, PublishMessageRequest(content_text="c1-1"))
    await MessageService.publish_message(db_session, c2.id, owner.id, PublishMessageRequest(content_text="c2-1"))
    await MessageService.publish_message(db_session, c1.id, owner.id, PublishMessageRequest(content_text="c1-2"))

    payload = await MessageService.sync(
        db_session,
        member.id,
        SyncRequest(
            channels=[
                {"channel_id": c1.id, "last_seen_seq_id": 0},
                {"channel_id": c2.id, "last_seen_seq_id": 0},
            ],
            limit=50,
        ),
    )
    actual = [(str(m.channel_id), m.seq_id) for m in payload["messages"]]
    assert actual == sorted(actual)
