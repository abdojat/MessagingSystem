from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event


async def log_event(
    db: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    channel_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> Event:
    event = Event(
        channel_id=channel_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event
