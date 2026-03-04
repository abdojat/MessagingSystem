import pytest

from app.db.models import User
from app.schemas.channels import ChannelCreateRequest
from app.services.channel_service import ChannelService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_channel_responses_include_role_and_permissions(db_session):
    owner = User(username="owner_payload", email="owner_payload@example.com", password_hash="x")
    outsider = User(username="outsider_payload", email="outsider_payload@example.com", password_hash="x")
    db_session.add_all([owner, outsider])
    await db_session.commit()
    await db_session.refresh(owner)
    await db_session.refresh(outsider)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(name="c_payload", visibility="public", join_mode="open"),
        DummyAMQP(),
    )

    owner_view = await ChannelService.get_channel_view(db_session, channel.id, owner.id)
    assert owner_view["my_role"].value == "owner"
    assert owner_view["permissions"]["can_manage_members"] is True
    assert owner_view["permissions"]["can_publish"] is True
    assert owner_view["permissions"]["can_edit_channel"] is True
    assert owner_view["permissions"]["can_delete_channel"] is True

    channels_for_outsider = await ChannelService.list_channels(db_session, outsider.id)
    outsider_view = next(ch for ch in channels_for_outsider if ch["id"] == channel.id)
    assert outsider_view["my_role"] == "none"
    assert outsider_view["permissions"]["can_publish"] is False
    assert outsider_view["permissions"]["can_edit_channel"] is False
