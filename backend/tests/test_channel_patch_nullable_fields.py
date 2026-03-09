import pytest

from app.db.models import User
from app.schemas.channels import ChannelCreateRequest, ChannelPatchRequest
from app.services.channel_service import ChannelService
from tests.test_utils import DummyAMQP


@pytest.mark.asyncio
async def test_owner_can_clear_avatar_and_description_with_null_patch(db_session):
    owner = User(username="owner_patch_nullable", email="owner_patch_nullable@example.com", password_hash="x")
    db_session.add(owner)
    await db_session.commit()
    await db_session.refresh(owner)

    channel = await ChannelService.create_channel(
        db_session,
        owner.id,
        ChannelCreateRequest(
            name="nullable_patch_channel",
            description="has description",
            avatar_url="https://example.com/avatar.png",
            visibility="public",
            join_mode="open",
        ),
        DummyAMQP(),
    )

    updated = await ChannelService.update_channel(
        db_session,
        channel.id,
        owner.id,
        ChannelPatchRequest(avatar_url=None, description=None),
        DummyAMQP(),
    )

    assert updated.avatar_url is None
    assert updated.description is None
