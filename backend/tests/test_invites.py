import pytest

from app.db.models import User
from app.schemas.channels import ChannelCreateRequest, InviteRequest
from app.services.channel_service import ChannelService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_invite_preview_revoke_and_accept_behaviors(db_session):
    owner = User(username="owner_inv", email="owner_inv@example.com", password_hash="x")
    target = User(username="target_inv", email="target_inv@example.com", password_hash="x")
    db_session.add_all([owner, target])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(target)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="c_inv", visibility="private", join_mode="invite_only"),
        DummyAMQP(),
    )

    invite = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target.id),
    )
    preview = await ChannelService.get_invite_preview(db_session, invite.token)
    assert preview["is_valid"] is True

    await ChannelService.revoke_invite(db_session, channel.id, invite.id, owner.id)
    revoked_preview = await ChannelService.get_invite_preview(db_session, invite.token)
    assert revoked_preview["is_valid"] is False
    assert revoked_preview["reason"] == "revoked"

    invite2 = await ChannelService.create_invite(
        db_session,
        channel.id,
        owner.id,
        InviteRequest(invited_user_id=target.id),
    )
    membership = await ChannelService.accept_invite(db_session, DummyAMQP(), invite2.token, target.id)
    assert membership.role.value == "member"

    second = await ChannelService.accept_invite(db_session, DummyAMQP(), invite2.token, target.id)
    assert second.role.value == "member"
