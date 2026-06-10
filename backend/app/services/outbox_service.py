from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.identifiers import normalize_channel_slug, normalize_username
from app.db.models import Channel, Outbox, OutboxStatus, User


async def _get_channel_slug(db: AsyncSession, channel_id: UUID) -> str:
    row = await db.execute(select(Channel.channel_slug).where(Channel.id == channel_id))
    channel_slug = row.scalar_one_or_none()
    if channel_slug is None:
        raise ValueError(f"channel not found for outbox routing: {channel_id}")
    return normalize_channel_slug(str(channel_slug))


async def _get_username(db: AsyncSession, user_id: UUID) -> str:
    row = await db.execute(select(User.username).where(User.id == user_id))
    username = row.scalar_one_or_none()
    if username is None:
        raise ValueError(f"user not found for outbox routing: {user_id}")
    return normalize_username(str(username))


async def enqueue_message_outbox(
    db: AsyncSession,
    message_id: UUID,
    channel_id: UUID,
    payload: dict,
) -> Outbox:
    settings = get_settings()
    channel_slug = await _get_channel_slug(db, channel_id)
    row = Outbox(
        aggregate_type="message",
        aggregate_id=message_id,
        channel_id=channel_id,
        payload=payload,
        type=str(payload.get("type", "message")),
        routing_key=f"channel.{channel_slug}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
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
    settings = get_settings()
    channel_slug = await _get_channel_slug(db, channel_id)
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=payload,
        type=event_type,
        routing_key=f"channel.{channel_slug}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
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
    settings = get_settings()
    username = await _get_username(db, user_id)
    row = Outbox(
        aggregate_type=event_type,
        aggregate_id=aggregate_id,
        channel_id=channel_id,
        payload=payload,
        type=event_type,
        routing_key=f"user.{username}",
        status=OutboxStatus.pending,
        max_attempts=settings.outbox_max_attempts,
    )
    db.add(row)
    await db.flush()
    return row
