import pytest

from app.db.models import MembershipRole, User
from app.schemas.channels import ChannelCreateRequest, InviteRequest, JoinRequest
from app.services.channel_service import ChannelService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_join_modes_behavior(db_session):
    owner = User(username="owner2", email="owner2@example.com", password_hash="x")
    u = User(username="user2", email="u2@example.com", password_hash="x")
    db_session.add_all([owner, u])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(u)

    amqp = DummyAMQP()
    open_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="open", visibility="public", join_mode="open"),
        amqp,
    )
    approval_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="approval", visibility="private", join_mode="approval_required"),
        amqp,
    )
    invite_channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="invite", visibility="private", join_mode="invite_only"),
        amqp,
    )

    status_joined, joined, _ = await ChannelService.join_channel(db_session, amqp, open_channel.id, u.id, JoinRequest())
    assert status_joined == "joined"
    assert joined.role == MembershipRole.member
    status_already, already_member, _ = await ChannelService.join_channel(db_session, amqp, open_channel.id, u.id, JoinRequest())
    assert status_already == "already_member"
    assert already_member.role == MembershipRole.member

    u3 = User(username="user3", email="u3@example.com", password_hash="x")
    db_session.add(u3)
    await db_session.commit()
    await db_session.refresh(u3)

    status_pending, pending, _ = await ChannelService.join_channel(db_session, amqp, approval_channel.id, u3.id, JoinRequest())
    assert status_pending == "pending"
    assert pending.role == MembershipRole.pending

    u4 = User(username="user4", email="u4@example.com", password_hash="x")
    db_session.add(u4)
    await db_session.commit()
    await db_session.refresh(u4)

    requires_invite_status, requires_invite_membership, _ = await ChannelService.join_channel(
        db_session, amqp, invite_channel.id, u4.id, JoinRequest()
    )
    assert requires_invite_status == "requires_invite"
    assert requires_invite_membership is None

    invite, invite_token = await ChannelService.create_invite(
        db_session,
        invite_channel.id,
        owner.id,
        InviteRequest(invited_user_id=u4.id, expires_in_hours=24),
    )
    status_invite_join, accepted, _ = await ChannelService.join_channel(
        db_session, amqp, invite_channel.id, u4.id, JoinRequest(invite_token=invite_token)
    )
    assert status_invite_join == "joined"
    assert accepted.role == MembershipRole.member
