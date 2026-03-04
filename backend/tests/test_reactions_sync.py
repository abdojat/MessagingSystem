import pytest

from app.db.models import ChannelMembership, MembershipRole, User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest, SyncRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_reactions_add_remove(db_session):
    owner = User(username="owner_react", email="owner_react@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="react", visibility="public", join_mode="open"),
        DummyAMQP(),
    )
    message = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="hello"),
    )

    added = await MessageService.add_reaction(db_session, channel.id, message.id, owner.id, ":+1:")
    assert added["counts"][":+1:"] == 1
    assert ":+1:" in added["my_reaction"]

    removed = await MessageService.remove_reaction(db_session, channel.id, message.id, owner.id, ":+1:")
    assert removed["counts"].get(":+1:", 0) == 0
    assert ":+1:" not in removed["my_reaction"]


@pytest.mark.asyncio
async def test_sync_respects_limit_and_seen_seq(db_session):
    owner = User(username="owner_sync", email="owner_sync@example.com", password_hash="x")
    member = User(username="member_sync", email="member_sync@example.com", password_hash="x")
    db_session.add_all([owner, member])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(member)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="sync", visibility="public", join_mode="open"),
        DummyAMQP(),
    )
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=member.id,
            role=MembershipRole.admin,
            created_by_user_id=owner.id,
        )
    )
    await db_session.commit()

    for idx in range(5):
        await MessageService.publish_message(
            db_session,
            channel.id,
            owner.id,
            PublishMessageRequest(content_text=f"m{idx}"),
        )

    payload = await MessageService.sync(
        db_session,
        member.id,
        SyncRequest(
            channels=[{"channel_id": channel.id, "last_seen_seq_id": 2}],
            limit=2,
        ),
    )
    assert len(payload["messages"]) == 2
    assert payload["messages"][0].seq_id == 3
    assert payload["messages"][1].seq_id == 4
