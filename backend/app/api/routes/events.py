from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError
from app.schemas.events import EventListResponse, EventResponse
from app.services.channel_service import ChannelService

router = APIRouter(tags=["events"])


@router.get("/channels/{channel_id}/events", response_model=EventListResponse)
async def list_channel_events(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> EventListResponse:
    try:
        events, next_cursor, has_more = await ChannelService.get_events(db, channel_id, user.id, cursor, limit)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return EventListResponse(
        items=[
            EventResponse(
                id=e.id,
                channel_id=e.channel_id,
                actor_user_id=e.actor_user_id,
                event_type=e.event_type,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in events
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )
