from uuid import UUID

import aio_pika
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import (
    Channel,
    ChannelMembership,
    Event,
    MembershipRole,
    Message,
    Outbox,
    OutboxStatus,
    User,
    UserSession,
)
from app.mq.publisher import bind_user_channel
from app.schemas.admin import (
    AdminChannelItem,
    AdminEventItem,
    AdminOverviewResponse,
    AdminUserItem,
)
from app.services.event_service import log_event
from app.services.outbox_service import enqueue_channel_event_outbox


class AdminService:
    @staticmethod
    async def overview(db: AsyncSession) -> AdminOverviewResponse:
        async def count(stmt) -> int:
            return int((await db.execute(stmt)).scalar_one() or 0)

        delivery_failure_statuses = [
            OutboxStatus.failed,
            OutboxStatus.retry_scheduled,
            OutboxStatus.dead_lettered,
        ]
        return AdminOverviewResponse(
            total_users=await count(select(func.count(User.id))),
            active_users=await count(select(func.count(User.id)).where(User.is_active.is_(True))),
            total_channels=await count(select(func.count(Channel.id))),
            active_channels=await count(select(func.count(Channel.id)).where(Channel.deleted_at.is_(None))),
            total_messages=await count(select(func.count(Message.id))),
            total_events=await count(select(func.count(Event.id))),
            delivery_failures=await count(select(func.count(Outbox.id)).where(Outbox.status.in_(delivery_failure_statuses))),
        )

    @staticmethod
    async def list_users(
        db: AsyncSession,
        *,
        q: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminUserItem], int]:
        filters = []
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(User.username.ilike(pattern), User.email.ilike(pattern), User.display_name.ilike(pattern)))
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))

        active_sessions = (
            select(UserSession.user_id, func.count(UserSession.id).label("active_session_count"))
            .where(UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
            .group_by(UserSession.user_id)
            .subquery()
        )
        stmt = select(User, func.coalesce(active_sessions.c.active_session_count, 0)).outerjoin(
            active_sessions, active_sessions.c.user_id == User.id
        )
        total_stmt = select(func.count(User.id))
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))

        rows = (await db.execute(stmt.order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        return [
            AdminUserItem(
                id=user.id,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                is_superadmin=user.is_superadmin,
                is_active=user.is_active,
                active_session_count=int(session_count or 0),
                created_at=user.created_at,
                updated_at=user.updated_at,
                deactivated_at=user.deactivated_at,
                deactivated_by_user_id=user.deactivated_by_user_id,
            )
            for user, session_count in rows
        ], total

    @staticmethod
    async def set_user_active(db: AsyncSession, actor: User, target_user_id: UUID, is_active: bool) -> int:
        target = await db.get(User, target_user_id)
        if not target:
            raise AppError("user not found", 404, code="USER_NOT_FOUND")
        if target.id == actor.id:
            raise AppError("a superadmin cannot change their own account status", 409, code="SELF_ADMIN_ACTION")
        if target.is_superadmin:
            raise AppError("other superadmin accounts cannot be changed here", 403, code="PROTECTED_SUPERADMIN")
        if target.is_active == is_active:
            return 0

        target.is_active = is_active
        target.deactivated_at = None if is_active else utcnow()
        target.deactivated_by_user_id = None if is_active else actor.id
        revoked_count = 0
        if not is_active:
            result = await db.execute(
                update(UserSession)
                .where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            revoked_count = int(result.rowcount or 0)

        await log_event(
            db,
            "superadmin.user_reactivated" if is_active else "superadmin.user_deactivated",
            {
                "target_user_id": str(target.id),
                "target_username": target.username,
                "revoked_sessions": revoked_count,
            },
            actor_user_id=actor.id,
        )
        await db.commit()
        return revoked_count

    @staticmethod
    async def revoke_user_sessions(db: AsyncSession, actor: User, target_user_id: UUID) -> int:
        target = await db.get(User, target_user_id)
        if not target:
            raise AppError("user not found", 404, code="USER_NOT_FOUND")
        if target.is_superadmin and target.id != actor.id:
            raise AppError("other superadmin sessions cannot be revoked here", 403, code="PROTECTED_SUPERADMIN")
        result = await db.execute(
            update(UserSession)
            .where(UserSession.user_id == target.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        count = int(result.rowcount or 0)
        await log_event(
            db,
            "superadmin.user_sessions_revoked",
            {"target_user_id": str(target.id), "target_username": target.username, "revoked_sessions": count},
            actor_user_id=actor.id,
        )
        await db.commit()
        return count

    @staticmethod
    async def list_channels(
        db: AsyncSession,
        *,
        q: str | None,
        include_deleted: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminChannelItem], int]:
        member_counts = (
            select(ChannelMembership.channel_id, func.count(ChannelMembership.user_id).label("member_count"))
            .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]))
            .group_by(ChannelMembership.channel_id)
            .subquery()
        )
        message_counts = (
            select(Message.channel_id, func.count(Message.id).label("message_count"))
            .group_by(Message.channel_id)
            .subquery()
        )
        filters = []
        if not include_deleted:
            filters.append(Channel.deleted_at.is_(None))
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(Channel.name.ilike(pattern), Channel.channel_slug.ilike(pattern), User.username.ilike(pattern)))

        stmt = (
            select(
                Channel,
                User.username,
                func.coalesce(member_counts.c.member_count, 0),
                func.coalesce(message_counts.c.message_count, 0),
            )
            .join(User, User.id == Channel.owner_user_id)
            .outerjoin(member_counts, member_counts.c.channel_id == Channel.id)
            .outerjoin(message_counts, message_counts.c.channel_id == Channel.id)
        )
        total_stmt = select(func.count(Channel.id)).join(User, User.id == Channel.owner_user_id)
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))
        rows = (await db.execute(stmt.order_by(Channel.created_at.desc()).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        return [
            AdminChannelItem(
                id=channel.id,
                name=channel.name,
                channel_slug=channel.channel_slug,
                owner_user_id=channel.owner_user_id,
                owner_username=owner_username,
                visibility=channel.visibility.value,
                join_mode=channel.join_mode.value,
                member_count=int(member_count or 0),
                message_count=int(message_count or 0),
                created_at=channel.created_at,
                updated_at=channel.updated_at,
                deleted_at=channel.deleted_at,
            )
            for channel, owner_username, member_count, message_count in rows
        ], total

    @staticmethod
    async def list_events(
        db: AsyncSession,
        *,
        event_type: str | None,
        channel_id: UUID | None,
        actor_user_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AdminEventItem], int]:
        filters = []
        if event_type:
            filters.append(Event.event_type.ilike(f"%{event_type.strip()}%"))
        if channel_id:
            filters.append(Event.channel_id == channel_id)
        if actor_user_id:
            filters.append(Event.actor_user_id == actor_user_id)

        stmt = (
            select(Event, User.username, Channel.name)
            .outerjoin(User, User.id == Event.actor_user_id)
            .outerjoin(Channel, Channel.id == Event.channel_id)
        )
        total_stmt = select(func.count(Event.id))
        if filters:
            stmt = stmt.where(and_(*filters))
            total_stmt = total_stmt.where(and_(*filters))
        rows = (await db.execute(stmt.order_by(Event.created_at.desc(), Event.id.desc()).offset(offset).limit(limit))).all()
        total = int((await db.execute(total_stmt)).scalar_one() or 0)
        return [
            AdminEventItem(
                id=event.id,
                channel_id=event.channel_id,
                channel_name=channel_name,
                actor_user_id=event.actor_user_id,
                actor_username=actor_username,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
                event_hash=event.event_hash,
                integrity_scope=event.integrity_scope,
            )
            for event, actor_username, channel_name in rows
        ], total

    @staticmethod
    async def restore_channel(db: AsyncSession, amqp: aio_pika.RobustConnection, actor: User, channel_id: UUID) -> None:
        channel = await db.get(Channel, channel_id)
        if not channel:
            raise AppError("channel not found", 404, code="CHANNEL_NOT_FOUND")
        if channel.deleted_at is None:
            raise AppError("channel is already active", 409, code="CONFLICT")

        channel.deleted_at = None
        await log_event(
            db,
            "superadmin.channel_restored",
            {"channel_id": str(channel.id), "channel_slug": channel.channel_slug},
            channel_id=channel.id,
            actor_user_id=actor.id,
        )
        await enqueue_channel_event_outbox(
            db,
            channel.id,
            channel.id,
            "channel_restored",
            {"type": "channel_restored", "channel_id": str(channel.id)},
        )
        await db.commit()

        usernames = (
            await db.execute(
                select(User.username)
                .join(ChannelMembership, ChannelMembership.user_id == User.id)
                .where(
                    ChannelMembership.channel_id == channel.id,
                    ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin, MembershipRole.member]),
                )
            )
        ).scalars().all()
        amqp_channel = await amqp.channel()
        try:
            for username in usernames:
                await bind_user_channel(amqp_channel, username, channel.channel_slug)
        finally:
            await amqp_channel.close()
