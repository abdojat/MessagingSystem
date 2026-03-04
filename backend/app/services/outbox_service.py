from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Outbox, OutboxStatus


async def enqueue_message_outbox(
    db: AsyncSession,
    message_id: UUID,
    channel_id: UUID,
    payload: dict,
) -> Outbox:
    row = Outbox(
        aggregate_type="message",
        aggregate_id=message_id,
        channel_id=channel_id,
        payload=payload,
        type=str(payload.get("type", "message")),
        routing_key=f"channel.{channel_id}",
        status=OutboxStatus.pending,
    )
    db.add(row)
    await db.flush()
    return row


async def enqueue_channel_event_outbox(
    db: AsyncSession,
    aggregate_id: UUID,
    channel_id: UUID,
    event_type: str,
    payload: dict,
) -> Outbox:
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=payload,
        type=event_type,
        routing_key=f"channel.{channel_id}",
        status=OutboxStatus.pending,
    )
    db.add(row)
    await db.flush()
    return row


async def enqueue_user_event_outbox(
    db: AsyncSession,
    aggregate_id: UUID,
    channel_id: UUID,
    user_id: UUID,
    event_type: str,
    payload: dict,
) -> Outbox:
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=payload,
        type=event_type,
        routing_key=f"user.{user_id}",
        status=OutboxStatus.pending,
    )
    db.add(row)
    await db.flush()
    return row
