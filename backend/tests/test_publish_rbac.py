import pytest

from app.core.errors import AppError
from app.db.models import ChannelCounter, ChannelMembership, MembershipRole, User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import PublishMessageRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_publish_requires_owner_or_admin(db_session):
    owner = User(username="owner", email="owner@example.com", password_hash="x")
    member = User(username="member", email="member@example.com", password_hash="x")
    pending = User(username="pending", email="pending@example.com", password_hash="x")
    db_session.add_all([owner, member, pending])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(member)
    await db_session.refresh(pending)

    amqp = DummyAMQP()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="c1", visibility="public", join_mode="open"),
        amqp,
    )

    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=member.id,
            role=MembershipRole.member,
            created_by_user_id=owner.id,
        )
    )
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=pending.id,
            role=MembershipRole.pending,
            created_by_user_id=owner.id,
        )
    )
    await db_session.commit()

    with pytest.raises(AppError):
        await MessageService.publish_message(
            db_session,
            channel.id,
            member.id,
            PublishMessageRequest(content_text="blocked"),
        )

    with pytest.raises(AppError):
        await MessageService.publish_message(
            db_session,
            channel.id,
            pending.id,
            PublishMessageRequest(content_text="blocked"),
        )

    msg = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="allowed"),
    )
    assert msg.seq_id == 1
