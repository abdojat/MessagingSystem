import pytest

from app.core.errors import AppError
from app.db.models import ChannelMembership, MembershipRole, User
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest, InviteRequest
from app.schemas.messages import PublishMessageRequest
from app.services.channel_service import ChannelService
from app.services.message_service import MessageService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_rbac_forbidden_matrix(db_session):
    owner = User(username="owner_mx", email="owner_mx@example.com", password_hash="x")
    admin = User(username="admin_mx", email="admin_mx@example.com", password_hash="x")
    member = User(username="member_mx", email="member_mx@example.com", password_hash="x")
    pending = User(username="pending_mx", email="pending_mx@example.com", password_hash="x")
    outsider = User(username="outsider_mx", email="outsider_mx@example.com", password_hash="x")
    db_session.add_all([owner, admin, member, pending, outsider])
    await db_session.commit()
    for u in [owner, admin, member, pending, outsider]:
        await db_session.refresh(u)

    amqp = DummyAMQP()
    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="rbac", visibility="public", join_mode="approval_required"),
        amqp,
    )
    db_session.add_all(
        [
            ChannelMembership(channel_id=channel.id, user_id=admin.id, role=MembershipRole.admin, created_by_user_id=owner.id),
            ChannelMembership(channel_id=channel.id, user_id=member.id, role=MembershipRole.member, created_by_user_id=owner.id),
            ChannelMembership(channel_id=channel.id, user_id=pending.id, role=MembershipRole.pending, created_by_user_id=owner.id),
        ]
    )
    await db_session.commit()

    with pytest.raises(AppError):
        await ChannelService.promote_member(db_session, channel.id, admin.id, member.id)
    with pytest.raises(AppError):
        await ChannelService.demote_member(db_session, channel.id, admin.id, admin.id)
    with pytest.raises(AppError):
        await ChannelService.remove_member(db_session, amqp, channel.id, member.id, pending.id)
    with pytest.raises(AppError):
        await ChannelService.approve_member(db_session, amqp, channel.id, member.id, pending.id)
    with pytest.raises(AppError):
        await ChannelService.create_invite(db_session, channel.id, member.id, InviteRequest(invited_user_id=outsider.id))
    with pytest.raises(AppError):
        await ChannelService.update_channel(db_session, channel.id, admin.id, ChannelPatchRequest(name="x"), amqp)
    with pytest.raises(AppError):
        await ChannelService.delete_channel(db_session, channel.id, admin.id, amqp)
    with pytest.raises(AppError):
        await MessageService.publish_message(
            db_session,
            channel.id,
            member.id,
            PublishMessageRequest(content_text="forbidden"),
        )
