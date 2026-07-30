from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.db.models import Event
from app.services.event_integrity_service import EventIntegrityService


async def log_event(
    db: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    channel_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> Event:
    scope = EventIntegrityService.scope_for_event(channel_id)
    # Integrity metadata is written inside the caller's transaction so the
    # event row and its hash-chain link commit or roll back together.
    await EventIntegrityService.lock_scope(db, scope)
    event = Event(
        channel_id=channel_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload=payload,
        created_at=utcnow(),
    )
    db.add(event)
    await db.flush()
    await EventIntegrityService.attach_integrity(db, event, scope)
    await db.flush()
    return event
