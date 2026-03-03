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
        routing_key=f"channel.{channel_id}",
        status=OutboxStatus.pending,
    )
    db.add(row)
    await db.flush()
    return row
