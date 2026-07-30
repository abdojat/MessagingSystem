from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChannelMembership, MembershipRole


# Retrieves membership role; the application startup and service layers use it for database access.
async def get_membership_role(db: AsyncSession, channel_id: UUID, user_id: UUID) -> MembershipRole | None:
    result = await db.execute(
        select(ChannelMembership.role).where(
            ChannelMembership.channel_id == channel_id,
            ChannelMembership.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
