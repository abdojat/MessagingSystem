from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserDep, DBDep
from app.core.errors import AppError, to_http_exception
from app.schemas.messages import (
    MessageAroundResponse,
    MessageListResponse,
    MessageResponse,
    PublishMessageRequest,
    SeenRequest,
    SeenResponse,
)
from app.services.message_service import MessageService

router = APIRouter(tags=["messages"])


def _to_message_response(message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        channel_id=message.channel_id,
        sender_user_id=message.sender_user_id,
        seq_id=message.seq_id,
        content_type=message.content_type.value,
        content_text=message.content_text,
        content_json=message.content_json,
        client_msg_id=message.client_msg_id,
        created_at=message.created_at,
    )


@router.post("/channels/{channel_id}/messages", response_model=MessageResponse, status_code=201)
async def publish_message(channel_id: UUID, req: PublishMessageRequest, db: DBDep, user: CurrentUserDep) -> MessageResponse:
    try:
        message = await MessageService.publish_message(db, channel_id, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return _to_message_response(message)


@router.get("/channels/{channel_id}/messages", response_model=MessageListResponse)
async def list_messages(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    before_seq_id: int | None = Query(default=None, ge=1),
    after_seq_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> MessageListResponse:
    try:
        messages, next_before, next_after, has_more = await MessageService.list_messages(
            db,
            channel_id,
            user.id,
            before_seq_id,
            after_seq_id,
            limit,
        )
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return MessageListResponse(
        items=[_to_message_response(m) for m in messages],
        next_before_seq_id=next_before,
        next_after_seq_id=next_after,
        has_more=has_more,
        order="asc" if after_seq_id is not None else "desc",
    )


@router.get("/channels/{channel_id}/messages/around", response_model=MessageAroundResponse)
async def list_messages_around(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    seq_id: int = Query(ge=1),
    limit: int = Query(default=40, ge=3, le=200),
) -> MessageAroundResponse:
    try:
        items = await MessageService.messages_around(db, channel_id, user.id, seq_id, limit)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return MessageAroundResponse(seq_id=seq_id, items=[_to_message_response(m) for m in items])


@router.get("/channels/{channel_id}/messages/{message_id}", response_model=MessageResponse)
async def get_message(channel_id: UUID, message_id: UUID, db: DBDep, user: CurrentUserDep) -> MessageResponse:
    try:
        message = await MessageService.get_message(db, channel_id, user.id, message_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return _to_message_response(message)


@router.post("/channels/{channel_id}/seen", response_model=SeenResponse)
async def seen(channel_id: UUID, req: SeenRequest, db: DBDep, user: CurrentUserDep) -> SeenResponse:
    try:
        state = await MessageService.mark_seen(db, channel_id, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return SeenResponse(
        channel_id=state.channel_id,
        user_id=state.user_id,
        last_seen_seq_id=state.last_seen_seq_id,
        last_seen_message_id=state.last_seen_message_id,
        last_seen_at=state.last_seen_at,
        unread_count=state.unread_count,
    )
