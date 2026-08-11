import asyncio
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CurrentUserDep, DBDep, RedisDep
from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.errors import AppError, to_http_exception
from app.core.upload_encryption import (
    UploadEncryptionError,
    file_has_encrypted_upload_magic,
    read_upload_encryption_header_from_path,
)
from app.db.models import Upload, User
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
from app.services.download_service import LeasedEncryptedFileResponse, LeasedFileResponse, protected_download_limiter
from app.services.rate_limit_service import enforce_rate_limit
from app.services.event_service import log_event

router = APIRouter(tags=["messages"])


async def _enforce_message_write(redis: RedisDep, user_id: UUID, operation: str) -> None:
    _ = operation
    settings = get_settings()
    await enforce_rate_limit(
        redis,
        f"rl:message-write:{user_id}:burst",
        limit=settings.rate_limit_message_write_burst_per_second,
        window_seconds=1,
    )
    await enforce_rate_limit(
        redis,
        f"rl:message-write:{user_id}:sustained",
        limit=settings.rate_limit_message_write_per_10_seconds,
        window_seconds=10,
    )


async def _enforce_media(redis: RedisDep, user_id: UUID, operation: str) -> None:
    _ = operation
    await enforce_rate_limit(
        redis,
        f"rl:media:{user_id}",
        limit=get_settings().rate_limit_media_per_minute,
        window_seconds=60,
    )


def _to_message_response(
    message,
    *,
    sender_username: str | None = None,
    sender_display_name: str | None = None,
    sender_avatar_url: str | None = None,
) -> MessageResponse:
    is_deleted = message.deleted_at is not None
    content_text = None
    content_json = None
    if not is_deleted:
        # The route response decrypts only after the service has authorized the
        # caller and returned a message they may read.
        content_text, content_json = MessageService._decrypt_message_content(message)
    return MessageResponse(
        id=message.id,
        channel_id=message.channel_id,
        sender_user_id=message.sender_user_id,
        sender_username=sender_username,
        sender_display_name=sender_display_name,
        sender_avatar_url=sender_avatar_url,
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


async def _to_message_response_with_reactions(
    db: DBDep,
    user_id: UUID,
    message,
    sender_cache: dict[UUID, User | None] | None = None,
) -> MessageResponse:
    sender: User | None
    if sender_cache is not None and message.sender_user_id in sender_cache:
        sender = sender_cache[message.sender_user_id]
    else:
        sender = await db.get(User, message.sender_user_id)
        if sender_cache is not None:
            sender_cache[message.sender_user_id] = sender

    try:
        response = _to_message_response(
            message,
            sender_username=sender.username if sender else None,
            sender_display_name=sender.display_name if sender else None,
            sender_avatar_url=sender.avatar_url if sender else None,
        )
    except AppError:
        # Decryption failures are audit events because they can indicate key
        # mismatch, corrupt ciphertext, or tampering with stored message fields.
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


async def _to_message_responses_with_reactions(
    db: DBDep,
    user_id: UUID,
    messages: list,
) -> list[MessageResponse]:
    if not messages:
        return []
    sender_ids = list({message.sender_user_id for message in messages})
    sender_rows = await db.execute(select(User).where(User.id.in_(sender_ids)))
    senders = {sender.id: sender for sender in sender_rows.scalars().all()}
    summaries = await MessageService._reaction_summaries(db, [message.id for message in messages], user_id)
    responses: list[MessageResponse] = []
    for message in messages:
        sender = senders.get(message.sender_user_id)
        try:
            response = _to_message_response(
                message,
                sender_username=sender.username if sender else None,
                sender_display_name=sender.display_name if sender else None,
                sender_avatar_url=sender.avatar_url if sender else None,
            )
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
        response.reactions_summary = summaries[message.id]
        responses.append(response)
    return responses


@router.post("/channels/{channel_id}/messages", response_model=MessageResponse, status_code=201)
async def publish_message(
    channel_id: UUID,
    req: PublishMessageRequest,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> MessageResponse:
    await _enforce_message_write(redis, user.id, "publish")
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
    # Keep route adapters tolerant of odd query parsing while the service owns
    # the actual sequence-window pagination rules.
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
        items=await _to_message_responses_with_reactions(db, user.id, messages),
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
        items=await _to_message_responses_with_reactions(db, user.id, items),
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
    redis: RedisDep,
) -> MessageResponse:
    await _enforce_message_write(redis, user.id, "edit")
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
    redis: RedisDep,
) -> MessageResponse:
    await _enforce_message_write(redis, user.id, "delete")
    try:
        message = await MessageService.delete_message(db, channel_id, user.id, message_id)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return await _to_message_response_with_reactions(db, user.id, message)


@router.post("/channels/{channel_id}/seen", response_model=SeenResponse)
async def seen(channel_id: UUID, req: SeenRequest, db: DBDep, user: CurrentUserDep, redis: RedisDep) -> SeenResponse:
    await _enforce_message_write(redis, user.id, "seen")
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
    redis: RedisDep,
) -> ReactionSummaryResponse:
    await _enforce_message_write(redis, user.id, "reaction")
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
    redis: RedisDep,
) -> ReactionSummaryResponse:
    await _enforce_message_write(redis, user.id, "reaction")
    try:
        summary = await MessageService.remove_reaction(db, channel_id, message_id, user.id, emoji)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return ReactionSummaryResponse.model_validate(summary)


@router.post("/channels/{channel_id}/pins/{message_id}", status_code=204)
async def pin_message(
    channel_id: UUID,
    message_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> None:
    await _enforce_message_write(redis, user.id, "pin")
    try:
        await MessageService.pin_message(db, channel_id, message_id, user.id)
    except AppError as exc:
        raise to_http_exception(exc) from exc


@router.delete("/channels/{channel_id}/pins/{message_id}", status_code=204)
async def unpin_message(
    channel_id: UUID,
    message_id: UUID,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> None:
    await _enforce_message_write(redis, user.id, "pin")
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
    items = await _to_message_responses_with_reactions(db, user.id, messages)
    return PinListResponse(items=items)


@router.post("/uploads", response_model=UploadCreateResponse, status_code=201)
async def create_upload(req: UploadCreateRequest, db: DBDep, user: CurrentUserDep, redis: RedisDep) -> UploadCreateResponse:
    await _enforce_media(redis, user.id, "create")
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
async def put_upload_content(
    file_id: UUID,
    request: Request,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> dict:
    await _enforce_media(redis, user.id, "put")
    try:
        upload = await MessageService.store_upload_content(db, user.id, file_id, request.stream())
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return {"file_id": str(upload.id), "public_url": upload.public_url}


@router.get("/uploads/{file_id}/content")
async def get_upload_content(
    file_id: UUID,
    request: Request,
    db: DBDep,
    user: CurrentUserDep,
    redis: RedisDep,
) -> Response:
    await _enforce_media(redis, user.id, "get")
    # Upload bytes are private by default. Access is inherited from ownership or
    # from a message/channel that references the upload.
    upload = await db.get(Upload, file_id)
    if not upload:
        raise to_http_exception(AppError("upload not found", 404, code="NOT_FOUND"))
    if not await MessageService.can_access_upload(db, user.id, file_id):
        await log_event(
            db,
            "security.unauthorized_upload_access",
            {"upload_id": str(file_id)},
            actor_user_id=user.id,
        )
        await db.commit()
        raise to_http_exception(AppError("forbidden", 403, code="FORBIDDEN"))
    settings = get_settings()
    # The storage path is database-managed, but resolution still enforces that
    # files stay under the configured uploads directory.
    path = MessageService._resolve_upload_path(settings.uploads_base_dir, upload.storage_path)
    if not path.exists():
        raise to_http_exception(AppError("upload content not found", 404, code="NOT_FOUND"))

    storage_version = int(upload.storage_encryption_version or 0)
    encrypted_storage = storage_version == 1
    encrypted_key_id = upload.storage_key_id if encrypted_storage else None
    if storage_version not in {0, 1} or (encrypted_storage and not encrypted_key_id):
        await MessageService._safe_log_event(
            db,
            "security.upload_storage_integrity_failure",
            {"upload_id": str(file_id), "reason": "invalid_database_metadata"},
            actor_user_id=user.id,
            commit=True,
        )
        raise to_http_exception(AppError("upload storage metadata is invalid", 500, code="DECRYPTION_FAILED"))

    # A valid encrypted header is self-identifying so the migration command can
    # recover the crash window where the file replacement completed before the
    # version-0 database row committed its new metadata.
    if storage_version == 0:
        encrypted_storage = await asyncio.to_thread(file_has_encrypted_upload_magic, path)
        if not encrypted_storage and not settings.allow_legacy_plaintext_uploads:
            await MessageService._safe_log_event(
                db,
                "security.upload_storage_integrity_failure",
                {"upload_id": str(file_id), "reason": "legacy_plaintext_disabled"},
                actor_user_id=user.id,
                commit=True,
            )
            raise to_http_exception(AppError("plaintext upload storage is not permitted", 500, code="DECRYPTION_FAILED"))

    if encrypted_storage and request.headers.get("range"):
        raise to_http_exception(
            AppError(
                "range requests are not supported for encrypted uploads",
                416,
                code="RANGE_NOT_SUPPORTED",
            )
        )

    if encrypted_storage:
        try:
            header = await asyncio.to_thread(
                read_upload_encryption_header_from_path,
                path,
                expected_upload_id=file_id,
                expected_key_id=encrypted_key_id,
            )
            if header.plaintext_size != int(upload.size_bytes):
                raise UploadEncryptionError("encrypted upload size metadata mismatch")
            # Version-0 crash recovery takes the authenticated header key ID.
            encrypted_key_id = header.key_id
        except (UploadEncryptionError, OSError):
            await MessageService._safe_log_event(
                db,
                "security.upload_storage_integrity_failure",
                {"upload_id": str(file_id), "reason": "header_validation_failed"},
                actor_user_id=user.id,
                commit=True,
            )
            raise to_http_exception(AppError("upload storage integrity validation failed", 500, code="DECRYPTION_FAILED"))

    lease = await protected_download_limiter.try_acquire(
        user.id,
        get_client_ip(request),
        per_user_limit=settings.max_concurrent_downloads_per_user,
        per_ip_limit=settings.max_concurrent_downloads_per_ip,
        global_limit=settings.max_concurrent_downloads_global,
    )
    if lease is None:
        raise to_http_exception(
            AppError(
                "concurrent download limit exceeded",
                429,
                code="DOWNLOAD_CONCURRENCY_LIMIT",
            )
        )
    try:
        await MessageService._safe_log_event(
            db,
            "upload.accessed",
            {
                "upload_id": str(file_id),
                "content_type": upload.content_type,
                "size_bytes": int(upload.size_bytes),
            },
            actor_user_id=user.id,
            commit=True,
        )
        # Authorization/audit DB work is complete before a potentially slow
        # client starts consuming bytes; release the pooled connection now.
        await db.close()
    except BaseException:
        await lease.release()
        raise
    try:
        if encrypted_storage:
            async def log_stream_integrity_failure(reason: str) -> None:
                # The request-scoped session was deliberately closed before the
                # slow stream. Use a short independent best-effort transaction.
                from app.db.session import SessionLocal

                async with SessionLocal() as event_db:
                    await MessageService._safe_log_event(
                        event_db,
                        "security.upload_storage_integrity_failure",
                        {"upload_id": str(file_id), "reason": reason},
                        actor_user_id=user.id,
                        commit=True,
                    )

            return LeasedEncryptedFileResponse(
                path,
                lease,
                upload_id=file_id,
                key_id=encrypted_key_id,
                plaintext_size=int(upload.size_bytes),
                media_type=upload.content_type,
                on_integrity_failure=log_stream_integrity_failure,
            )
        return LeasedFileResponse(path, lease, media_type=upload.content_type)
    except BaseException:
        # Constructor/header failures occur before ASGI invokes the response's
        # finally block, so release the complete multi-dimensional lease here.
        await lease.release()
        raise


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
async def sync(req: SyncRequest, db: DBDep, user: CurrentUserDep, redis: RedisDep) -> SyncResponse:
    await enforce_rate_limit(
        redis,
        f"rl:sync:{user.id}",
        limit=get_settings().rate_limit_sync_per_minute,
        window_seconds=60,
    )
    try:
        payload = await MessageService.sync(db, user.id, req)
    except AppError as exc:
        raise to_http_exception(exc) from exc
    return SyncResponse(
        server_time=payload["server_time"],
        channel_updates=payload["channel_updates"],
        membership_updates=payload["membership_updates"],
        messages=await _to_message_responses_with_reactions(db, user.id, payload["messages"]),
    )
