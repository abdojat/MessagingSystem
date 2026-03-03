from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError
from app.schemas.messages import MessageResponse, PublishMessageRequest, SeenRequest, SeenResponse
from app.services.message_service import MessageService

router = APIRouter(tags=["messages"])


@router.post("/channels/{channel_id}/messages", response_model=MessageResponse, status_code=201)
async def publish_message(channel_id: UUID, req: PublishMessageRequest, db: DBDep, user: CurrentUserDep) -> MessageResponse:
    try:
        message = await MessageService.publish_message(db, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return MessageResponse(
        id=message.id,
        channel_id=message.channel_id,
        sender_user_id=message.sender_user_id,
        seq_id=message.seq_id,
        content_type=message.content_type.value,
        content_text=message.content_text,
        content_json=message.content_json,
        created_at=message.created_at,
    )


@router.get("/channels/{channel_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    before_seq_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MessageResponse]:
    try:
        messages = await MessageService.list_messages(db, channel_id, user.id, before_seq_id, limit)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return [
        MessageResponse(
            id=m.id,
            channel_id=m.channel_id,
            sender_user_id=m.sender_user_id,
            seq_id=m.seq_id,
            content_type=m.content_type.value,
            content_text=m.content_text,
            content_json=m.content_json,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/channels/{channel_id}/seen", response_model=SeenResponse)
async def seen(channel_id: UUID, req: SeenRequest, db: DBDep, user: CurrentUserDep) -> SeenResponse:
    try:
        state = await MessageService.mark_seen(db, channel_id, user.id, req)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return SeenResponse(
        channel_id=state.channel_id,
        user_id=state.user_id,
        last_seen_seq_id=state.last_seen_seq_id,
        unread_count=state.unread_count,
    )
