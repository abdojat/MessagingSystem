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

    joined = await ChannelService.join_channel(db_session, amqp, open_channel.id, u.id, JoinRequest())
    assert joined.role == MembershipRole.member

    pending = await ChannelService.join_channel(db_session, amqp, approval_channel.id, u.id, JoinRequest())
    assert pending.role == MembershipRole.pending

    invite = await ChannelService.create_invite(
        db_session,
        invite_channel.id,
        owner.id,
        InviteRequest(invited_user_id=u.id, expires_in_hours=24),
    )
    accepted = await ChannelService.accept_invite(db_session, amqp, invite.token, u.id)
    assert accepted.role == MembershipRole.member
