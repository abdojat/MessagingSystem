from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.schemas.events import EventIntegrityResponse, EventListResponse, EventResponse
from app.services.channel_service import ChannelService
from app.services.event_integrity_service import EventIntegrityService

router = APIRouter(tags=["events"])


# Lists channel events; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/channels/{channel_id}/events", response_model=EventListResponse)
async def list_channel_events(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> EventListResponse:
    # Run this conditional step only when `not isinstance(cursor, str)` is true.
    if not isinstance(cursor, str):
        cursor = None
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        events, next_cursor, has_more = await ChannelService.get_events(db, channel_id, user.id, cursor, limit)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return EventListResponse(
        items=[
            EventResponse(
                id=e.id,
                channel_id=e.channel_id,
                actor_user_id=e.actor_user_id,
                event_type=e.event_type,
                payload=e.payload,
                created_at=e.created_at,
                previous_hash=e.previous_hash,
                event_hash=e.event_hash,
                hash_algorithm=e.hash_algorithm,
                integrity_version=e.integrity_version,
                integrity_scope=e.integrity_scope,
            )
            for e in events
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# Verifies channel event integrity; FastAPI calls it to serve the corresponding HTTP or WebSocket flow.
@router.get("/channels/{channel_id}/events/integrity", response_model=EventIntegrityResponse)
async def verify_channel_event_integrity(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
) -> EventIntegrityResponse:
    # Attempt this operation and handle expected failures in the exception branches below.
    try:
        await ChannelService._assert_manage_membership_access(db, channel_id, user.id)
        result = await EventIntegrityService.verify_channel_scope(db, channel_id)
    # Handle `AppError` here so this workflow can recover or report the failure consistently.
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return EventIntegrityResponse(**result)
