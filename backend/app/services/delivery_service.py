from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.utils import utcnow
from app.db.models import Channel, ChannelMembership, MembershipRole, Outbox, OutboxStatus
from app.schemas.delivery import DeliveryItemResponse, DeliveryRetryResponse, DeliveryStatsResponse
from app.services.event_service import log_event
from app.services.rbac import normalize_admin_permissions


class DeliveryService:
    MANUAL_RETRY_STATUSES = {
        OutboxStatus.failed,
        OutboxStatus.retry_scheduled,
        OutboxStatus.dead_lettered,
    }

    @staticmethod
    def _status_value(status: OutboxStatus | str) -> str:
        return status.value if isinstance(status, OutboxStatus) else str(status)

    @staticmethod
    def _can_manage_delivery(role: MembershipRole, admin_permissions: dict | None) -> bool:
        if role == MembershipRole.owner:
            return True
        if role == MembershipRole.admin:
            return normalize_admin_permissions(admin_permissions)["can_manage_members"]
        return False

    @staticmethod
    async def get_managed_channel_ids(db: AsyncSession, actor_user_id: UUID) -> list[UUID]:
        rows = (
            await db.execute(
                select(ChannelMembership.channel_id, ChannelMembership.role, ChannelMembership.admin_permissions)
                .where(ChannelMembership.user_id == actor_user_id)
                .where(ChannelMembership.role.in_([MembershipRole.owner, MembershipRole.admin]))
            )
        ).all()
        channel_ids = [
            row.channel_id
            for row in rows
            if DeliveryService._can_manage_delivery(row.role, row.admin_permissions)
        ]
        if not channel_ids:
            raise AppError(
                "delivery monitor requires channel owner/admin permissions",
                403,
                code="FORBIDDEN",
            )
        return channel_ids

    @staticmethod
    def _to_item(outbox: Outbox, channel_slug: str | None = None) -> DeliveryItemResponse:
        status = DeliveryService._status_value(outbox.status)
        event_type = None if outbox.aggregate_type == "message" else (outbox.type or outbox.aggregate_type)
        message_id = outbox.aggregate_id if outbox.aggregate_type == "message" else None
        return DeliveryItemResponse(
            id=outbox.id,
            channel_id=outbox.channel_id,
            channel_slug=channel_slug,
            message_id=message_id,
            event_type=event_type,
            payload_type=outbox.type,
            routing_key=outbox.routing_key,
            status=status,
            attempt_count=outbox.attempts,
            max_attempts=outbox.max_attempts,
            next_attempt_at=outbox.next_retry_at,
            last_error=outbox.last_error,
            created_at=outbox.created_at,
            updated_at=outbox.updated_at,
            published_at=outbox.published_at,
            dead_lettered_at=outbox.dead_lettered_at,
        )

    @staticmethod
    async def get_stats(db: AsyncSession, actor_user_id: UUID) -> DeliveryStatsResponse:
        channel_ids = await DeliveryService.get_managed_channel_ids(db, actor_user_id)
        rows = (
            await db.execute(
                select(Outbox.status, func.count(Outbox.id))
                .where(Outbox.channel_id.in_(channel_ids))
                .group_by(Outbox.status)
            )
        ).all()
        counts = DeliveryStatsResponse().model_dump()
        for status, count in rows:
            status_value = DeliveryService._status_value(status)
            if status_value == "sent":
                counts["published"] += int(count)
            elif status_value in counts:
                counts[status_value] = int(count)
        return DeliveryStatsResponse(**counts)

    @staticmethod
    async def list_failed(db: AsyncSession, actor_user_id: UUID, limit: int = 100) -> list[DeliveryItemResponse]:
        return await DeliveryService._list_by_statuses(
            db,
            actor_user_id,
            [OutboxStatus.retry_scheduled, OutboxStatus.failed],
            limit,
        )

    @staticmethod
    async def list_dead_lettered(db: AsyncSession, actor_user_id: UUID, limit: int = 100) -> list[DeliveryItemResponse]:
        return await DeliveryService._list_by_statuses(
            db,
            actor_user_id,
            [OutboxStatus.dead_lettered],
            limit,
        )

    @staticmethod
    async def _list_by_statuses(
        db: AsyncSession,
        actor_user_id: UUID,
        statuses: list[OutboxStatus],
        limit: int,
    ) -> list[DeliveryItemResponse]:
        channel_ids = await DeliveryService.get_managed_channel_ids(db, actor_user_id)
        rows = (
            await db.execute(
                select(Outbox, Channel.channel_slug)
                .join(Channel, Channel.id == Outbox.channel_id)
                .where(Outbox.channel_id.in_(channel_ids))
                .where(Outbox.status.in_(statuses))
                .order_by(Outbox.updated_at.desc(), Outbox.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [DeliveryService._to_item(outbox, channel_slug) for outbox, channel_slug in rows]

    @staticmethod
    async def retry_one(db: AsyncSession, actor_user_id: UUID, outbox_id: UUID) -> DeliveryRetryResponse:
        channel_ids = await DeliveryService.get_managed_channel_ids(db, actor_user_id)
        row = (
            await db.execute(
                select(Outbox, Channel.channel_slug)
                .join(Channel, Channel.id == Outbox.channel_id)
                .where(Outbox.id == outbox_id)
                .where(Outbox.channel_id.in_(channel_ids))
            )
        ).first()
        if row is None:
            raise AppError("delivery record not found", 404, code="NOT_FOUND")

        outbox, channel_slug = row
        retried_count = 0
        if outbox.status in DeliveryService.MANUAL_RETRY_STATUSES:
            previous_status = DeliveryService._status_value(outbox.status)
            previous_attempt_count = outbox.attempts
            DeliveryService._reset_for_manual_retry(outbox)
            await log_event(
                db,
                "broker.manual_retry_requested",
                {
                    "outbox_id": str(outbox.id),
                    "previous_status": previous_status,
                    "previous_attempt_count": previous_attempt_count,
                    "manual_retry": True,
                },
                channel_id=outbox.channel_id,
                actor_user_id=actor_user_id,
            )
            retried_count = 1
            await db.commit()
            await db.refresh(outbox)
        else:
            await db.rollback()

        return DeliveryRetryResponse(
            retried_count=retried_count,
            items=[DeliveryService._to_item(outbox, channel_slug)],
        )

    @staticmethod
    async def retry_all(db: AsyncSession, actor_user_id: UUID, limit: int = 200) -> DeliveryRetryResponse:
        channel_ids = await DeliveryService.get_managed_channel_ids(db, actor_user_id)
        rows = (
            await db.execute(
                select(Outbox, Channel.channel_slug)
                .join(Channel, Channel.id == Outbox.channel_id)
                .where(Outbox.channel_id.in_(channel_ids))
                .where(Outbox.status.in_(list(DeliveryService.MANUAL_RETRY_STATUSES)))
                .order_by(Outbox.updated_at.asc(), Outbox.created_at.asc())
                .limit(limit)
            )
        ).all()

        items: list[DeliveryItemResponse] = []
        for outbox, channel_slug in rows:
            previous_status = DeliveryService._status_value(outbox.status)
            previous_attempt_count = outbox.attempts
            DeliveryService._reset_for_manual_retry(outbox)
            await log_event(
                db,
                "broker.manual_retry_requested",
                {
                    "outbox_id": str(outbox.id),
                    "previous_status": previous_status,
                    "previous_attempt_count": previous_attempt_count,
                    "manual_retry": True,
                },
                channel_id=outbox.channel_id,
                actor_user_id=actor_user_id,
            )
            items.append(DeliveryService._to_item(outbox, channel_slug))

        if rows:
            await db.commit()
            for outbox, _ in rows:
                await db.refresh(outbox)
            items = [DeliveryService._to_item(outbox, channel_slug) for outbox, channel_slug in rows]
        else:
            await db.rollback()

        return DeliveryRetryResponse(retried_count=len(rows), items=items)

    @staticmethod
    def _reset_for_manual_retry(outbox: Outbox) -> None:
        outbox.status = OutboxStatus.pending
        outbox.attempts = 0
        outbox.next_retry_at = None
        outbox.last_error = None
        outbox.dead_lettered_at = None
        outbox.updated_at = utcnow()
