import pytest

from app.api.routes.memberships import create_invite as create_invite_route
from app.api.routes.memberships import list_invites as list_invites_route
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
    route_created = await create_invite_route(channel.id, InviteRequest(invited_user_id=target.id), db_session, owner)
    assert route_created.token
    preview = await ChannelService.get_invite_preview(db_session, invite.token)
    assert preview["is_valid"] is True

    listed = await list_invites_route(channel.id, db_session, owner)
    assert listed.items
    assert all(not hasattr(item, "token") for item in listed.items)
    assert listed.items[0].masked_token != invite.token
    assert listed.items[0].masked_token == listed.items[0].token_masked

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
