from uuid import UUID

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.api.deps import CurrentUserDep, DBDep, RedisDep
from app.core.config import get_settings
from app.core.errors import AppError, to_http_exception
from app.db.models import Upload
from app.schemas.messages import (
    MessageAroundResponse,
    MessageListResponse,
    MessagePatchRequest,
    MessageResponse,
    PinListResponse,
    PublishMessageRequest,
    ReactionRequest,
    ReactionSummaryResponse,
    SeenRequest,
    SeenResponse,
    SyncRequest,
    SyncResponse,
    UploadCreateRequest,
    UploadCreateResponse,
)
from app.services.message_service import MessageService
from app.services.rate_limit_service import RateLimitService
from app.services.event_service import log_event

router = APIRouter(tags=["messages"])


def _to_message_response(message) -> MessageResponse:
    is_deleted = message.deleted_at is not None
    content_text = None
    content_json = None
    if not is_deleted:
        content_text, content_json = MessageService._decrypt_message_content(message)
    return MessageResponse(
        id=message.id,
        channel_id=message.channel_id,
        sender_user_id=message.sender_user_id,
        seq_id=message.seq_id,
        content_type=message.content_type.value,
        content_text=content_text,
        content_json=content_json,
        reply_to_message_id=message.reply_to_message_id,
        reply_to_seq_id=message.reply_to_seq_id,
        attachments=None if is_deleted else message.attachments,
        is_pinned=message.is_pinned,
        client_msg_id=message.client_msg_id,
        created_at=message.created_at,
        updated_at=message.updated_at,
        edited_at=message.edited_at,
        deleted_at=message.deleted_at,
        reactions_summary={"counts": {}, "my_reaction": []},
    )


async def _to_message_response_with_reactions(db: DBDep, user_id: UUID, message) -> MessageResponse:
    try:
        response = _to_message_response(message)
    except AppError:
        await log_event(
            db,
            "message.decryption_failed",
            {"channel_id": str(message.channel_id), "message_id": str(message.id)},
            channel_id=message.channel_id,
            actor_user_id=user_id,
        )
        await db.commit()
        raise
    response.reactions_summary = await MessageService._reaction_summary(db, message.id, user_id)
    return response


@router.post("/channels/{channel_id}/messages", response_model=MessageResponse, status_code=201)
async def publish_message(
    channel_id: UUID,
    req: PublishMessageRequest,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> MessageResponse:
    burst_retry = await RateLimitService.hit(
        redis,
        f"rl:msg:{user.id}:{channel_id}:burst",
        limit=40,
        window_seconds=1,
    )
    if burst_retry is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "rate limit exceeded", "details": {"retry_after_seconds": burst_retry}},
            headers={"Retry-After": str(burst_retry)},
        )
    sustained_retry = await RateLimitService.hit(
        redis,
        f"rl:msg:{user.id}:{channel_id}:sustained",
        limit=200,
        window_seconds=10,
    )
    if sustained_retry is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "rate limit exceeded", "details": {"retry_after_seconds": sustained_retry}},
            headers={"Retry-After": str(sustained_retry)},
        )
    try:
        message = await MessageService.publish_message(db, channel_id, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return await _to_message_response_with_reactions(db, user.id, message)


@router.get(
    "/channels/{channel_id}/messages",
    response_model=MessageListResponse,
    openapi_extra={
        "description": (
            "Seq-based pagination. If both before_seq_id and after_seq_id are supplied, "
            "the server applies a bounded window (after_seq_id, before_seq_id). "
            "For order=desc use next_before_seq_id; for order=asc use next_after_seq_id."
        ),
        "examples": {
            "before_seq": {
                "summary": "Fetch older messages",
                "value": {"before_seq_id": 120, "limit": 50, "order": "desc"},
            },
            "after_seq": {
                "summary": "Fetch newer messages",
                "value": {"after_seq_id": 120, "limit": 50, "order": "asc"},
            },
        }
    },
)
async def list_messages(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    before_seq_id: int | None = Query(default=None, ge=1),
    after_seq_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> MessageListResponse:
    if not isinstance(before_seq_id, int):
        before_seq_id = None
    if not isinstance(after_seq_id, int):
        after_seq_id = None
    if not isinstance(order, str):
        order = "desc"
    try:
        messages, next_before, next_after, has_more = await MessageService.list_messages(
            db,
            channel_id,
            user.id,
            before_seq_id,
            after_seq_id,
            limit,
            order,
        )
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return MessageListResponse(
        items=[await _to_message_response_with_reactions(db, user.id, m) for m in messages],
        next_before_seq_id=next_before,
        next_after_seq_id=next_after,
        has_more=has_more,
        order=order,
    )


@router.get("/channels/{channel_id}/messages/around", response_model=MessageAroundResponse)
async def list_messages_around(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    seq_id: int = Query(ge=1),
    limit: int | None = Query(default=None, ge=3, le=200),
    limit_before: int = Query(default=30, ge=0, le=100),
    limit_after: int = Query(default=30, ge=0, le=100),
) -> MessageAroundResponse:
    if not isinstance(limit_before, int):
        limit_before = 30
    if not isinstance(limit_after, int):
        limit_after = 30
    if limit is not None:
        side = max(1, limit // 2)
        limit_before = side
        limit_after = side
    try:
        items = await MessageService.messages_around(db, channel_id, user.id, seq_id, limit_before, limit_after)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return MessageAroundResponse(
        seq_id=seq_id,
        items=[await _to_message_response_with_reactions(db, user.id, m) for m in items],
    )


@router.get("/channels/{channel_id}/messages/{message_id}", response_model=MessageResponse)
async def get_message(channel_id: UUID, message_id: UUID, db: DBDep, user: CurrentUserDep) -> MessageResponse:
    try:
        message = await MessageService.get_message(db, channel_id, user.id, message_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return await _to_message_response_with_reactions(db, user.id, message)


@router.patch("/channels/{channel_id}/messages/{message_id}", response_model=MessageResponse)
async def edit_message(
    channel_id: UUID,
    message_id: UUID,
    req: MessagePatchRequest,
    db: DBDep,
    user: CurrentUserDep,
) -> MessageResponse:
    try:
        message = await MessageService.edit_message(db, channel_id, user.id, message_id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return await _to_message_response_with_reactions(db, user.id, message)


@router.delete("/channels/{channel_id}/messages/{message_id}", response_model=MessageResponse)
async def delete_message(
    channel_id: UUID,
    message_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
) -> MessageResponse:
    try:
        message = await MessageService.delete_message(db, channel_id, user.id, message_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return await _to_message_response_with_reactions(db, user.id, message)


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


@router.post("/channels/{channel_id}/messages/{message_id}/reactions", response_model=ReactionSummaryResponse)
async def add_reaction(
    channel_id: UUID,
    message_id: UUID,
    req: ReactionRequest,
    db: DBDep,
    user: CurrentUserDep,
) -> ReactionSummaryResponse:
    try:
        summary = await MessageService.add_reaction(db, channel_id, message_id, user.id, req.emoji)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ReactionSummaryResponse.model_validate(summary)


@router.delete("/channels/{channel_id}/messages/{message_id}/reactions/{emoji}", response_model=ReactionSummaryResponse)
async def remove_reaction(
    channel_id: UUID,
    message_id: UUID,
    emoji: str,
    db: DBDep,
    user: CurrentUserDep,
) -> ReactionSummaryResponse:
    try:
        summary = await MessageService.remove_reaction(db, channel_id, message_id, user.id, emoji)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ReactionSummaryResponse.model_validate(summary)


@router.post("/channels/{channel_id}/pins/{message_id}", status_code=204)
async def pin_message(channel_id: UUID, message_id: UUID, db: DBDep, user: CurrentUserDep) -> None:
    try:
        await MessageService.pin_message(db, channel_id, message_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc


@router.delete("/channels/{channel_id}/pins/{message_id}", status_code=204)
async def unpin_message(channel_id: UUID, message_id: UUID, db: DBDep, user: CurrentUserDep) -> None:
    try:
        await MessageService.unpin_message(db, channel_id, message_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc


@router.get("/channels/{channel_id}/pins", response_model=PinListResponse)
async def list_pins(
    channel_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> PinListResponse:
    try:
        messages = await MessageService.list_pins(db, channel_id, user.id, limit)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    items = [await _to_message_response_with_reactions(db, user.id, m) for m in messages]
    return PinListResponse(items=items)


@router.post("/uploads", response_model=UploadCreateResponse, status_code=201)
async def create_upload(req: UploadCreateRequest, db: DBDep, user: CurrentUserDep) -> UploadCreateResponse:
    try:
        upload = await MessageService.create_upload(db, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return UploadCreateResponse(
        file_id=upload.id,
        upload_url=f"/v1/uploads/{upload.id}/content",
        method="PUT",
        headers={},
        public_url=upload.public_url,
    )


@router.put("/uploads/{file_id}/content")
async def put_upload_content(file_id: UUID, request: Request, db: DBDep, user: CurrentUserDep) -> dict:
    try:
        body = await request.body()
        upload = await MessageService.store_upload_content(db, user.id, file_id, body)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"file_id": str(upload.id), "public_url": upload.public_url}


@router.get("/uploads/{file_id}/content")
async def get_upload_content(file_id: UUID, db: DBDep) -> Response:
    upload = await db.get(Upload, file_id)
    if not upload:
        raise to_http_exception(AppError("upload not found", 404, code="NOT_FOUND"))
    settings = get_settings()
    path = Path(settings.uploads_base_dir) / upload.storage_path
    if not path.exists():
        raise to_http_exception(AppError("upload content not found", 404, code="NOT_FOUND"))
    return Response(content=path.read_bytes(), media_type=upload.content_type)


@router.post(
    "/sync",
    response_model=SyncResponse,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "example": {
                        "channels": [{"channel_id": "00000000-0000-0000-0000-000000000001", "last_seen_seq_id": 42}],
                        "since": None,
                        "limit": 200,
                    }
                }
            }
        }
    },
)
async def sync(req: SyncRequest, db: DBDep, user: CurrentUserDep) -> SyncResponse:
    try:
        payload = await MessageService.sync(db, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return SyncResponse(
        server_time=payload["server_time"],
        channel_updates=payload["channel_updates"],
        membership_updates=payload["membership_updates"],
        messages=[await _to_message_response_with_reactions(db, user.id, m) for m in payload["messages"]],
    )
