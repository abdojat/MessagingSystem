import uuid

import pytest
from sqlalchemy import select, func

from app.core.errors import AppError
from app.db.models import ChannelMembership, MembershipRole, Message, User
from app.schemas.channels import ChannelCreateRequest
from app.schemas.messages import MessagePatchRequest, PublishMessageRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_publish_idempotency_by_client_msg_id(db_session):
    owner = User(username="owner_idmp", email="owner_idmp@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="idmp", visibility="public", join_mode="open"),
        DummyAMQP(),
    )

    client_msg_id = uuid.uuid4()
    first = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="same", client_msg_id=client_msg_id),
    )
    second = await MessageService.publish_message(
        db_session,
        channel.id,
        owner.id,
        PublishMessageRequest(content_text="same", client_msg_id=client_msg_id),
    )
    assert first.id == second.id
    assert first.seq_id == second.seq_id == 1
    count_result = await db_session.execute(select(func.count(Message.id)).where(Message.channel_id == channel.id))
    assert int(count_result.scalar_one() or 0) == 1


@pytest.mark.asyncio
async def test_message_edit_delete_permissions(db_session):
    owner = User(username="owner_mut", email="owner_mut@example.com", password_hash="x")
    admin = User(username="admin_mut", email="admin_mut@example.com", password_hash="x")
    sender = User(username="sender_mut", email="sender_mut@example.com", password_hash="x")
    outsider = User(username="outsider_mut", email="outsider_mut@example.com", password_hash="x")
    db_session.add_all([owner, admin, sender, outsider])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(admin)
    await db_session.refresh(sender)
    await db_session.refresh(outsider)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="mut", visibility="public", join_mode="open"),
        DummyAMQP(),
    )
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=admin.id,
            role=MembershipRole.admin,
            created_by_user_id=owner.id,
        )
    )
    db_session.add(
        ChannelMembership(
            channel_id=channel.id,
            user_id=sender.id,
            role=MembershipRole.admin,
            created_by_user_id=owner.id,
        )
    )
    await db_session.commit()

    msg = await MessageService.publish_message(
        db_session,
        channel.id,
        sender.id,
        PublishMessageRequest(content_text="before"),
    )

    with pytest.raises(AppError):
        await MessageService.edit_message(
            db_session,
            channel.id,
            outsider.id,
            msg.id,
            MessagePatchRequest(content_text="blocked"),
        )

    edited = await MessageService.edit_message(
        db_session,
        channel.id,
        admin.id,
        msg.id,
        MessagePatchRequest(content_text="after"),
    )
    assert edited.content_text == "after"
    assert edited.edited_at is not None

    deleted = await MessageService.delete_message(db_session, channel.id, admin.id, msg.id)
    assert deleted.deleted_at is not None
